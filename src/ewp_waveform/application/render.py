"""Render orchestration: workdir, envelope scroll, experimental spectrum, publish."""

from __future__ import annotations

import multiprocessing
import shutil as shutil
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor as ProcessPoolExecutor
from concurrent.futures import as_completed as as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

from ewp_waveform import __version__ as __version__
from ewp_waveform.analysis.cache import (
    analysis_cache_digest,
    analysis_cache_payload,
    load_analysis_cache,
    store_analysis_cache,
)
from ewp_waveform.analysis.envelope import (
    bin_peak as bin_peak,
)
from ewp_waveform.analysis.envelope import (
    envelope_aa_from_signal as envelope_aa_from_signal,
)
from ewp_waveform.analysis.envelope import (
    envelope_context_bins as envelope_context_bins,
)
from ewp_waveform.analysis.envelope import (
    envelope_oversample_from_signal as envelope_oversample_from_signal,
)
from ewp_waveform.analysis.envelope import (
    envelope_preroll_seconds as envelope_preroll_seconds,
)
from ewp_waveform.analysis.envelope import (
    hop_samples as hop_samples,
)
from ewp_waveform.analysis.envelope import (
    motion_cutoff_cyc_px as motion_cutoff_cyc_px,
)
from ewp_waveform.analysis.envelope import (
    motion_lpf_from_signal as motion_lpf_from_signal,
)
from ewp_waveform.analysis.envelope import (
    normalize_bins as normalize_bins,
)
from ewp_waveform.analysis.envelope import (
    process_envelope_bins as process_envelope_bins,
)
from ewp_waveform.analysis.envelope import (
    published_bin_slice as published_bin_slice,
)
from ewp_waveform.analysis.envelope import (
    rms_bins_from_wav as rms_bins_from_wav,
)
from ewp_waveform.analysis.envelope import (
    viewport_left_px as viewport_left_px,
)
from ewp_waveform.analysis.envelope import (
    window_from_origin as window_from_origin,
)
from ewp_waveform.analysis.frames import AnalysisSequence
from ewp_waveform.analysis.spectrum import (
    PIVOT_TAU_SECONDS,
    FrequencySpan,
    apply_edge_taper,
    apply_spectrum_spatial,
    blend_columns,
    build_analysis_sequence,
    dominant_band_pivot,
    ema_alpha,
    fold_bands_center_out,
    gaussian_smooth,
    load_mono_pcm,
    resolve_frequency_span_from_pcm,
    spectrum_bands,
    spectrum_columns,
    spectrum_peak,
    upsample_bands,
)
from ewp_waveform.analysis.temporal import (
    TEMPORAL_BINS,
    TEMPORAL_PEAK_MIX,
    TEMPORAL_WINDOW_SECONDS,
    load_mono_f32,
    temporal_envelope_columns,
    temporal_envelope_peak,
)
from ewp_waveform.application import render_lifecycle, render_scroll
from ewp_waveform.application.appearance import (
    FixedAxisAppearance,
)
from ewp_waveform.application.appearance import (
    normalize_spatial_filter as _spectrum_spatial_filter,
)
from ewp_waveform.application.appearance import (
    resolve_fixed_axis_appearance as resolve_fixed_axis_appearance,
)
from ewp_waveform.application.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION as CHECKPOINT_SCHEMA_VERSION,
)
from ewp_waveform.application.checkpoint import (
    Checkpoint as Checkpoint,
)
from ewp_waveform.application.checkpoint import (
    ChunkRecord as ChunkRecord,
)
from ewp_waveform.application.checkpoint import (
    checkpoint_path as checkpoint_path,
)
from ewp_waveform.application.checkpoint import (
    identity_matches as identity_matches,
)
from ewp_waveform.application.checkpoint import (
    load_checkpoint as load_checkpoint,
)
from ewp_waveform.application.checkpoint import (
    png_chunk_complete as png_chunk_complete,
)
from ewp_waveform.application.checkpoint import (
    reset_workdir as reset_workdir,
)
from ewp_waveform.application.checkpoint import (
    resolve_workdir as resolve_workdir,
)
from ewp_waveform.application.checkpoint import (
    reusable_chunk_indices as reusable_chunk_indices,
)
from ewp_waveform.application.checkpoint import (
    workdir_key as workdir_key,
)
from ewp_waveform.application.checkpoint import (
    write_checkpoint as write_checkpoint,
)
from ewp_waveform.application.chunks import (
    ProcessingWindow,
)
from ewp_waveform.application.chunks import (
    bin_origin as bin_origin,
)
from ewp_waveform.application.chunks import (
    plan_chunks as plan_chunks,
)
from ewp_waveform.application.chunks import (
    processing_window as processing_window,
)
from ewp_waveform.application.evidence import fingerprint_from_plan
from ewp_waveform.application.formats import validate_output_formats as validate_output_formats
from ewp_waveform.application.render_scroll import (
    ChunkEncodeTask as ChunkEncodeTask,
)
from ewp_waveform.application.render_scroll import (
    EnvelopeSettings as EnvelopeSettings,
)
from ewp_waveform.application.render_scroll import (
    PreparedChunk as PreparedChunk,
)
from ewp_waveform.application.render_types import RenderContext, RendererOutcome, RenderOptions
from ewp_waveform.application.results import elapsed_seconds as elapsed_seconds
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import (
    Diagnostic,
)
from ewp_waveform.domain.diagnostics import (
    DiagnosticCode as DiagnosticCode,
)
from ewp_waveform.domain.diagnostics import (
    Severity as Severity,
)
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.concat import concat_videos as concat_videos
from ewp_waveform.ffmpeg.decode import DecodeError
from ewp_waveform.ffmpeg.decode import decode_mono_wav as decode_mono_wav
from ewp_waveform.ffmpeg.draw import (
    CLASSIC_SCROLL_ALTERNATE_OPACITY as CLASSIC_SCROLL_ALTERNATE_OPACITY,
)
from ewp_waveform.ffmpeg.draw import (
    RIBBON_SUPERSAMPLE,
    draw_spectrum_frame,
)
from ewp_waveform.ffmpeg.draw import (
    SCROLL_SUPERSAMPLE as SCROLL_SUPERSAMPLE,
)
from ewp_waveform.ffmpeg.draw import (
    draw_envelope_frame as draw_envelope_frame,
)
from ewp_waveform.ffmpeg.draw import (
    glow_overscan as glow_overscan,
)
from ewp_waveform.ffmpeg.encode import (
    EncodeError,
    glow_sigma,
)
from ewp_waveform.ffmpeg.encode import (
    encode_rgba_stream as encode_rgba_stream,
)
from ewp_waveform.ffmpeg.probe import ProbeError
from ewp_waveform.ffmpeg.probe import probe_media as probe_media
from ewp_waveform.ffmpeg.probe import probe_png_sequence as probe_png_sequence
from ewp_waveform.ffmpeg.probe import probe_video as probe_video
from ewp_waveform.identity import (
    VISUAL_CONTRACT_VERSION as VISUAL_CONTRACT_VERSION,
)
from ewp_waveform.identity import (
    render_signature as render_signature,
)
from ewp_waveform.identity import (
    sha256_file as sha256_file,
)
from ewp_waveform.identity import (
    short_signature as short_signature,
)
from ewp_waveform.visual.bars import BarStyle
from ewp_waveform.visual.mapping import CENTER_OUT_SLOTS, CenterOutMapping
from ewp_waveform.visual.plan import RenderPlan, resolve_render_plan
from ewp_waveform.visual.raster import raster_field_columns
from ewp_waveform.visual.ribbon import field_to_columns
from ewp_waveform.visual.style_defaults import (
    BAR_GEOMETRIES,
    default_glow_level,
)


def _glow_sigma(preset: VisualPreset) -> float:
    raw = preset.effects.get("glow")
    if not isinstance(raw, dict):
        return 0.0
    return glow_sigma(str(raw.get("level") or "none"), bool(raw.get("enabled", False)))


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lifecycle_hooks() -> render_lifecycle.LifecycleHooks:
    """Expose live module helpers without copying callbacks or importing render back."""
    return cast(render_lifecycle.LifecycleHooks, sys.modules[__name__])


def _scroll_hooks() -> render_scroll.ScrollHooks:
    """Keep helper and worker lookups live without a reverse pipeline import."""
    return cast(render_scroll.ScrollHooks, sys.modules[__name__])


def output_root(source: Path, configured: Path | None, directory_name: str) -> Path:
    return render_lifecycle.output_root(source, configured, directory_name)


def next_version_path(path: Path) -> Path:
    return render_lifecycle.next_version_path(path)


def output_is_complete(path: Path) -> bool:
    return render_lifecycle.output_is_complete(path)


def publish_path(
    dest: Path,
    *,
    force: bool,
) -> tuple[Path, bool]:
    return render_lifecycle.publish_path(_lifecycle_hooks(), dest, force=force)


def planned_destinations(
    job: PlannedJob,
    preset: VisualPreset,
    *,
    source_sha256: str,
    output_dir: Path,
    formats: Sequence[str],
    clip_start: float = 0.0,
    clip_duration: float | None = None,
    fixed_axis_recipe: dict[str, Any] | None = None,
) -> tuple[str, Path | None, Path | None]:
    return render_lifecycle.planned_destinations(
        _lifecycle_hooks(),
        job,
        preset,
        source_sha256=source_sha256,
        output_dir=output_dir,
        formats=formats,
        clip_start=clip_start,
        clip_duration=clip_duration,
        fixed_axis_recipe=fixed_axis_recipe,
    )


def _tick_frames(
    frames: Iterator[bytes],
    *,
    n_frames: int,
    note: Callable[[str], None],
    label: str,
) -> Iterator[bytes]:
    for index, frame in enumerate(frames, start=1):
        if index == 1 or index == n_frames or index % 300 == 0:
            note(f"{label} frame {index}/{n_frames}")
        yield frame


def iter_scroll_frames(
    bins: list[float],
    *,
    duration: float,
    preset: VisualPreset,
    fps: float,
    glow: float = 0.0,
    first_frame: int = 0,
    n_frames: int | None = None,
    origin: float = 0.0,
) -> Iterator[bytes]:
    return render_scroll.iter_scroll_frames(
        _scroll_hooks(),
        bins,
        duration=duration,
        preset=preset,
        fps=fps,
        glow=glow,
        first_frame=first_frame,
        n_frames=n_frames,
        origin=origin,
    )


def iter_spectrum_frames(
    path: Path,
    *,
    n_frames: int,
    preset: VisualPreset,
    fps: float,
    glow: float,
    span: FrequencySpan,
    peak: float | None,
    scale: str,
    tau_seconds: float,
    soft_clip: bool,
    contour: bool = False,
    spatial_sigma: float = 0.0,
    spatial_filter: str = "box",
    n_bands: int | None = None,
    tilt_db_per_octave: float = 0.0,
    compress: float = 1.0,
    recenter: bool = False,
    edge_taper: float = 0.0,
    layout: str = "linear",
    slot_sigma: float = 0.0,
    supersample: int = RIBBON_SUPERSAMPLE,
) -> Iterator[bytes]:
    """Fixed-axis frames: X is log-Hz, motion is vertical only.

    ``contour`` is a visual-target experiment: PCHIP filled silhouette instead
    of independent column spans. ``spatial_sigma`` / ``spatial_filter`` are
    log-Hz LPF experiments; FFT, span, EMA, and gain are unchanged.
    ``recenter`` / ``edge_taper`` are layout-only (not analysis or gain).
    ``layout="center_out"`` is a static fold; X slots never move between frames.
    """
    width = preset.canvas.width
    height = preset.canvas.height
    stroke = preset.waveform.stroke_width or 3.0
    center = bool(preset.waveform.center_line)
    pad = glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    alpha = ema_alpha(fps, tau_seconds)
    pivot_alpha = ema_alpha(fps, PIVOT_TAU_SECONDS)
    previous: list[float] | None = None
    pivot: float | None = None
    filt = _spectrum_spatial_filter(spatial_filter)
    taper = edge_taper if edge_taper > 0.0 else 0.0
    ss = max(1, int(supersample))
    for i in range(n_frames):
        if n_bands is not None:
            bands = spectrum_bands(
                path,
                frame_index=i,
                fps=fps,
                span=span,
                scale=scale,
                n_bands=n_bands,
                tilt_db_per_octave=tilt_db_per_octave,
                compress=compress,
            )
            if layout == "center_out":
                slots = fold_bands_center_out(bands)
                if slot_sigma > 0.0:
                    slots = gaussian_smooth(slots, sigma=slot_sigma)
                raw = upsample_bands(slots, draw_w, pivot=None)
            else:
                layout_pivot: float | None = None
                if recenter:
                    instant = dominant_band_pivot(bands)
                    if pivot is None:
                        pivot = instant
                    else:
                        pivot = pivot_alpha * instant + (1.0 - pivot_alpha) * pivot
                    layout_pivot = pivot
                raw = upsample_bands(bands, draw_w, pivot=layout_pivot)
            raw = apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        else:
            raw = spectrum_columns(
                path,
                frame_index=i,
                fps=fps,
                width=draw_w,
                span=span,
                scale=scale,
                smoothing_sigma=spatial_sigma,
                spatial_filter=filt,
            )
        if peak is not None and peak > 0.0:
            raw = normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = blend_columns(previous, raw, alpha)
        previous = blended
        if taper > 0.0:
            blended = apply_edge_taper(
                blended,
                content_width=width,
                pad=pad,
                fraction=taper,
            )
        if contour:
            yield draw_spectrum_frame(
                blended,
                width=draw_w,
                height=draw_h,
                color=preset.waveform.color,
                amplitude=preset.waveform.amplitude,
                center_line=center,
                content_height=height,
                supersample=ss,
                glow_sigma=glow,
            )
        else:
            yield draw_envelope_frame(
                blended,
                width=draw_w,
                height=draw_h,
                color=preset.waveform.color,
                amplitude=preset.waveform.amplitude,
                stroke_width=stroke,
                style=preset.waveform.style,
                center_line=center,
                scroll_phase=0.0,
                content_height=height,
                supersample=ss,
                glow_sigma=glow,
                envelope_oversample=1,
            )


def _visual_field_peak(
    sequence: AnalysisSequence,
    *,
    width: int,
    spatial_sigma: float,
    spatial_filter: str,
    mapping: CenterOutMapping,
) -> float:
    collected: list[float] = []
    n_frames = len(sequence)
    step = 1 if n_frames <= 240 else max(1, n_frames // 120)
    filt = _spectrum_spatial_filter(spatial_filter)
    for i in range(0, n_frames, step):
        field = mapping.apply(sequence[i])
        columns = field_to_columns(field, width)
        columns = apply_spectrum_spatial(columns, sigma=spatial_sigma, kind=filt)
        collected.extend(columns)
    return bin_peak(collected)


def iter_field_frames(
    sequence: AnalysisSequence,
    *,
    n_frames: int,
    preset: VisualPreset,
    fps: float,
    glow: float,
    peak: float | None,
    tau_seconds: float,
    soft_clip: bool,
    spatial_sigma: float,
    spatial_filter: str,
    mapping: CenterOutMapping,
    supersample: int = RIBBON_SUPERSAMPLE,
    plan: RenderPlan | None = None,
    bar_style: BarStyle | None = None,
    phases: PhaseTimes | None = None,
) -> Iterator[bytes]:
    """AnalysisFrame -> static VisualField -> style geometry. X slots never move."""
    height = preset.canvas.height
    pad = glow_overscan(glow)
    draw_w = preset.canvas.width + 2 * pad
    draw_h = height + 2 * pad
    alpha = ema_alpha(fps, tau_seconds)
    filt = _spectrum_spatial_filter(spatial_filter)
    previous: list[float] | None = None
    resolved = plan or resolve_render_plan(
        preset,
        layout="field_center_out",
        field_geometry="ribbon",
        ribbon_supersample=supersample,
    )
    # Bars: no decorative center line until that styling pass.
    center = bool(preset.waveform.center_line) and resolved.geometry not in BAR_GEOMETRIES
    count = min(n_frames, len(sequence))
    for i in range(count):
        t0 = time.perf_counter()
        field = mapping.apply(sequence[i])
        raw = field_to_columns(field, draw_w)
        raw = apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        if peak is not None and peak > 0.0:
            raw = normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = blend_columns(previous, raw, alpha)
        previous = blended
        t1 = time.perf_counter()
        frame = raster_field_columns(
            blended,
            plan=resolved,
            width=draw_w,
            height=draw_h,
            color=preset.waveform.color,
            amplitude=preset.waveform.amplitude,
            center_line=center,
            content_height=preset.canvas.height,
            glow_sigma=glow,
            bar_style=bar_style,
        )
        t2 = time.perf_counter()
        if phases is not None:
            phases.add("visual_field", t1 - t0)
            phases.add("raster", t2 - t1)
        yield frame


# Spawn+concat loses to the fused generator on short clips (8 s @ 60 fps).
_FIELD_POOL_MIN_FRAMES = 1800


def _field_frame_ranges(n_frames: int, workers: int) -> list[tuple[int, int]]:
    """Split ``[0, n_frames)`` into contiguous ranges. Order is concat order."""
    count = max(1, n_frames)
    n_workers = min(max(1, workers), count)
    base, extra = divmod(count, n_workers)
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(n_workers):
        size = base + (1 if index < extra else 0)
        ranges.append((start, size))
        start += size
    return ranges


@dataclass(frozen=True)
class FieldChunkTask:
    """Pickleable payload for one independent field-ribbon encode range."""

    chunk_index: int
    n_chunks: int
    first_frame: int
    n_frames: int
    columns_path: str
    width: int
    height: int
    fps: float
    color: str
    amplitude: float
    center_line: bool
    content_height: int
    glow: float
    png_dir: str | None
    prores_path: str | None
    ffmpeg_threads: int
    overscan: int
    supersample: int
    pix_fmt: str
    aa_taps: int
    plan_path: str
    geometry: str
    bar_width: float
    bar_gap: float
    bar_count: int
    bar_fill: float
    bar_align: str
    bar_alternate: bool
    bar_color_b: str
    bar_center_line_width: float


def encode_field_chunk(task: FieldChunkTask) -> Path | None:
    """Raster and encode one precomputed column range. Spawn-pool safe."""
    columns = np.load(task.columns_path, mmap_mode="r")
    slc = columns[task.first_frame : task.first_frame + task.n_frames]
    pad = task.overscan
    draw_w = task.width + 2 * pad
    draw_h = task.height + 2 * pad

    plan = RenderPlan(
        path="mask_fast" if task.plan_path == "mask_fast" else "rgba_2d",
        pix_fmt="gray" if task.pix_fmt == "gray" else "rgba",
        bytes_per_pixel=1 if task.pix_fmt == "gray" else 4,
        supersample=task.supersample,
        aa_mode="coverage_taps" if task.aa_taps > 1 and task.supersample == 1 else "physical_ss",
        aa_taps=task.aa_taps,
        colorize=task.pix_fmt == "gray",
        geometry=task.geometry,
    )
    bars = BarStyle(
        width=task.bar_width,
        gap=task.bar_gap,
        count=task.bar_count if task.bar_count > 0 else None,
        fill=task.bar_fill,
        align=task.bar_align,
        alternate=task.bar_alternate,
        color_b=task.bar_color_b,
        center_line_width=task.bar_center_line_width,
    )

    def frames() -> Iterator[bytes]:
        for row in slc:
            yield raster_field_columns(
                row.tolist(),
                plan=plan,
                width=draw_w,
                height=draw_h,
                color=task.color,
                amplitude=task.amplitude,
                center_line=task.center_line,
                content_height=task.content_height,
                glow_sigma=task.glow,
                bar_style=bars,
            )

    png_dir = Path(task.png_dir) if task.png_dir is not None else None
    prores_path = Path(task.prores_path) if task.prores_path is not None else None
    encode_rgba_stream(
        frames(),
        width=task.width,
        height=task.height,
        fps=task.fps,
        glow=task.glow,
        png_dir=png_dir,
        prores_path=prores_path,
        ffmpeg_threads=task.ffmpeg_threads,
        overscan=task.overscan,
        supersample=task.supersample,
        png_start_number=task.first_frame + 1,
        pix_fmt=task.pix_fmt,
        color=task.color if task.pix_fmt == "gray" else None,
        n_frames=task.n_frames,
    )
    return prores_path


def _precompute_field_columns(
    sequence: AnalysisSequence,
    *,
    n_frames: int,
    draw_w: int,
    peak: float | None,
    tau_seconds: float,
    fps: float,
    soft_clip: bool,
    spatial_sigma: float,
    spatial_filter: str,
    mapping: CenterOutMapping,
    phases: PhaseTimes | None = None,
) -> list[list[float]]:
    alpha = ema_alpha(fps, tau_seconds)
    filt = _spectrum_spatial_filter(spatial_filter)
    previous: list[float] | None = None
    rows: list[list[float]] = []
    count = min(n_frames, len(sequence))
    for i in range(count):
        t0 = time.perf_counter()
        field = mapping.apply(sequence[i])
        raw = field_to_columns(field, draw_w)
        raw = apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        if peak is not None and peak > 0.0:
            raw = normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = blend_columns(previous, raw, alpha)
        previous = blended
        if phases is not None:
            phases.add("visual_field", time.perf_counter() - t0)
        rows.append(blended)
    return rows


def iter_temporal_frames(
    samples: list[float],
    rate: int,
    *,
    n_frames: int,
    preset: VisualPreset,
    fps: float,
    glow: float,
    peak: float | None,
    tau_seconds: float,
    soft_clip: bool,
    origin_seconds: float,
    peak_mix: float,
) -> Iterator[bytes]:
    """Centered temporal envelope: X is time in a local window, current time at mid."""
    width = preset.canvas.width
    height = preset.canvas.height
    center = bool(preset.waveform.center_line)
    pad = glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    alpha = ema_alpha(fps, tau_seconds)
    previous: list[float] | None = None
    for i in range(n_frames):
        time_seconds = origin_seconds + (i / fps if fps > 0 else 0.0)
        raw = temporal_envelope_columns(
            samples,
            rate,
            time_seconds=time_seconds,
            width=draw_w,
            peak_mix=peak_mix,
        )
        if peak is not None and peak > 0.0:
            raw = normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = blend_columns(previous, raw, alpha)
        previous = blended
        yield draw_spectrum_frame(
            blended,
            width=draw_w,
            height=draw_h,
            color=preset.waveform.color,
            amplitude=preset.waveform.amplitude,
            center_line=center,
            content_height=height,
            supersample=SCROLL_SUPERSAMPLE,
            glow_sigma=glow,
        )


def _chunk_seconds(performance: PerformanceProfile) -> float:
    return render_scroll._chunk_seconds(_scroll_hooks(), performance)


def _job_workers(performance: PerformanceProfile) -> int:
    raw = performance.processing.get("jobs", 1)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 1
    return max(1, raw)


def _encode_worker_threads(configured: int, workers: int) -> int:
    """Avoid N auto-threaded FFmpeg processes oversubscribing the machine."""
    if workers > 1 and configured == 0:
        return 1
    return configured


def _stderr_note(message: str) -> None:
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def _clip_bounds(
    media: SourceMedia, start: float | None, duration: float | None
) -> tuple[float, float]:
    clip_start = start if start is not None and start > 0 else 0.0
    remain = max(0.0, media.duration_seconds - clip_start)
    if duration is not None and duration > 0:
        return clip_start, min(duration, remain)
    return clip_start, remain


def _envelope_settings(preset: VisualPreset, fps: float, glow: float) -> EnvelopeSettings:
    return render_scroll._envelope_settings(_scroll_hooks(), preset, fps, glow)


def _filter_wav(
    decoded: Path, settings: EnvelopeSettings, sample_rate: int, width: int, window_seconds: float
) -> tuple[list[float], float]:
    return render_scroll._filter_wav(
        _scroll_hooks(), decoded, settings, sample_rate, width, window_seconds
    )


def _validate_mov(
    path: Path,
    *,
    width: int,
    height: int,
    expected_frames: int,
    fps: float,
) -> dict[str, Any]:
    return render_lifecycle._validate_mov(
        _lifecycle_hooks(),
        path,
        width=width,
        height=height,
        expected_frames=expected_frames,
        fps=fps,
    )


def _validate_png(
    directory: Path, *, expected_frames: int, width: int, height: int
) -> dict[str, Any]:
    return render_lifecycle._validate_png(
        _lifecycle_hooks(), directory, expected_frames=expected_frames, width=width, height=height
    )


def _with_glow_level(preset: VisualPreset, level: str | None) -> VisualPreset:
    if level is None:
        return preset
    effects = dict(preset.effects)
    raw_glow = effects.get("glow")
    glow = dict(raw_glow) if isinstance(raw_glow, dict) else {}
    glow["level"] = str(level)
    glow["enabled"] = str(level) != "none"
    effects["glow"] = glow
    return preset.model_copy(update={"effects": effects})


def _with_waveform_color(preset: VisualPreset, color: str | None) -> VisualPreset:
    """Override stroke/glow color without editing the preset file."""
    if color is None or color == preset.waveform.color:
        return preset
    wave = preset.waveform.model_copy(update={"color": color})
    effects = dict(preset.effects)
    glow = effects.get("glow")
    if isinstance(glow, dict):
        effects["glow"] = {**glow, "color": color}
    return preset.model_copy(update={"waveform": wave, "effects": effects})


def _with_classic_alternate_opacity(preset: VisualPreset, opacity: float | None) -> VisualPreset:
    """Apply an in-memory classic opacity override without mutating the preset."""
    if opacity is None:
        return preset
    signal = dict(preset.signal)
    signal["classic_alternate_opacity"] = min(max(float(opacity), 0.0), 1.0)
    return preset.model_copy(update={"signal": signal})


def _render_options_from_legacy(
    *,
    output_dir: Path,
    formats: list[str],
    force: bool,
    start: float | None = None,
    duration: float | None = None,
    keep_temp: bool = False,
    fail_after_chunk: int | None = None,
    progress: Callable[[str], None] | None = None,
    spectrum_contour: bool = False,
    spectrum_spatial_scale: float = 1.0,
    spectrum_spatial_filter: str = "box",
    spectrum_n_bands: int | None = None,
    spectrum_tilt_db_per_octave: float = 0.0,
    spectrum_compress: float = 1.0,
    spectrum_recenter: bool = False,
    spectrum_edge_taper: float = 0.0,
    visual_geometry: str = "spectrum",
    spectrum_layout: str = "linear",
    spectrum_slot_sigma: float = 0.0,
    ribbon_supersample: int | None = None,
    render_path: str | None = None,
    render_aa: str | None = None,
    field_geometry: str = "ribbon",
    bar_width: float | None = None,
    bar_gap: float | None = None,
    bar_count: int | None = None,
    bar_fill: float | None = None,
    bar_align: str | None = None,
    bar_alternate: bool | None = None,
    bar_color_b: str | None = None,
    bar_center_line_width: float | None = None,
    waveform_color: str | None = None,
    glow_level: str | None = None,
    classic_alternate_opacity: float | None = None,
    phases: PhaseTimes | None = None,
) -> RenderOptions:
    """Transport legacy keyword values without resolving, copying or coercing them."""
    return RenderOptions(
        output_dir=output_dir,
        formats=formats,
        force=force,
        start=start,
        duration=duration,
        keep_temp=keep_temp,
        fail_after_chunk=fail_after_chunk,
        progress=progress,
        spectrum_contour=spectrum_contour,
        spectrum_spatial_scale=spectrum_spatial_scale,
        spectrum_spatial_filter=spectrum_spatial_filter,
        spectrum_n_bands=spectrum_n_bands,
        spectrum_tilt_db_per_octave=spectrum_tilt_db_per_octave,
        spectrum_compress=spectrum_compress,
        spectrum_recenter=spectrum_recenter,
        spectrum_edge_taper=spectrum_edge_taper,
        visual_geometry=visual_geometry,
        spectrum_layout=spectrum_layout,
        spectrum_slot_sigma=spectrum_slot_sigma,
        ribbon_supersample=ribbon_supersample,
        render_path=render_path,
        render_aa=render_aa,
        field_geometry=field_geometry,
        bar_width=bar_width,
        bar_gap=bar_gap,
        bar_count=bar_count,
        bar_fill=bar_fill,
        bar_align=bar_align,
        bar_alternate=bar_alternate,
        bar_color_b=bar_color_b,
        bar_center_line_width=bar_center_line_width,
        waveform_color=waveform_color,
        glow_level=glow_level,
        classic_alternate_opacity=classic_alternate_opacity,
        phases=phases,
    )


def render_job(
    job: PlannedJob,
    media: SourceMedia,
    preset: VisualPreset,
    performance: PerformanceProfile,
    *,
    output_dir: Path,
    formats: list[str],
    force: bool,
    start: float | None = None,
    duration: float | None = None,
    keep_temp: bool = False,
    fail_after_chunk: int | None = None,
    progress: Callable[[str], None] | None = None,
    spectrum_contour: bool = False,
    spectrum_spatial_scale: float = 1.0,
    spectrum_spatial_filter: str = "box",
    spectrum_n_bands: int | None = None,
    spectrum_tilt_db_per_octave: float = 0.0,
    spectrum_compress: float = 1.0,
    spectrum_recenter: bool = False,
    spectrum_edge_taper: float = 0.0,
    visual_geometry: str = "spectrum",
    spectrum_layout: str = "linear",
    spectrum_slot_sigma: float = 0.0,
    ribbon_supersample: int | None = None,
    render_path: str | None = None,
    render_aa: str | None = None,
    field_geometry: str = "ribbon",
    bar_width: float | None = None,
    bar_gap: float | None = None,
    bar_count: int | None = None,
    bar_fill: float | None = None,
    bar_align: str | None = None,
    bar_alternate: bool | None = None,
    bar_color_b: str | None = None,
    bar_center_line_width: float | None = None,
    waveform_color: str | None = None,
    glow_level: str | None = None,
    classic_alternate_opacity: float | None = None,
    phases: PhaseTimes | None = None,
) -> dict[str, Any]:
    context = RenderContext(job=job, media=media, preset=preset, performance=performance)
    options = _render_options_from_legacy(
        output_dir=output_dir,
        formats=formats,
        force=force,
        start=start,
        duration=duration,
        keep_temp=keep_temp,
        fail_after_chunk=fail_after_chunk,
        progress=progress,
        spectrum_contour=spectrum_contour,
        spectrum_spatial_scale=spectrum_spatial_scale,
        spectrum_spatial_filter=spectrum_spatial_filter,
        spectrum_n_bands=spectrum_n_bands,
        spectrum_tilt_db_per_octave=spectrum_tilt_db_per_octave,
        spectrum_compress=spectrum_compress,
        spectrum_recenter=spectrum_recenter,
        spectrum_edge_taper=spectrum_edge_taper,
        visual_geometry=visual_geometry,
        spectrum_layout=spectrum_layout,
        spectrum_slot_sigma=spectrum_slot_sigma,
        ribbon_supersample=ribbon_supersample,
        render_path=render_path,
        render_aa=render_aa,
        field_geometry=field_geometry,
        bar_width=bar_width,
        bar_gap=bar_gap,
        bar_count=bar_count,
        bar_fill=bar_fill,
        bar_align=bar_align,
        bar_alternate=bar_alternate,
        bar_color_b=bar_color_b,
        bar_center_line_width=bar_center_line_width,
        waveform_color=waveform_color,
        glow_level=glow_level,
        classic_alternate_opacity=classic_alternate_opacity,
        phases=phases,
    )
    outcome = _render_job(context, options)
    return outcome.payload


def _render_job(context: RenderContext, options: RenderOptions) -> RendererOutcome:
    job = context.job
    media = context.media
    preset = context.preset
    performance = context.performance
    output_dir = options.output_dir
    formats = options.formats
    force = options.force
    start = options.start
    duration = options.duration
    keep_temp = options.keep_temp
    fail_after_chunk = options.fail_after_chunk
    progress = options.progress
    spectrum_contour = options.spectrum_contour
    spectrum_spatial_scale = options.spectrum_spatial_scale
    spectrum_spatial_filter = options.spectrum_spatial_filter
    spectrum_n_bands = options.spectrum_n_bands
    spectrum_tilt_db_per_octave = options.spectrum_tilt_db_per_octave
    spectrum_compress = options.spectrum_compress
    spectrum_recenter = options.spectrum_recenter
    spectrum_edge_taper = options.spectrum_edge_taper
    visual_geometry = options.visual_geometry
    spectrum_layout = options.spectrum_layout
    spectrum_slot_sigma = options.spectrum_slot_sigma
    ribbon_supersample = options.ribbon_supersample
    render_path = options.render_path
    render_aa = options.render_aa
    field_geometry = options.field_geometry
    bar_width = options.bar_width
    bar_gap = options.bar_gap
    bar_count = options.bar_count
    bar_fill = options.bar_fill
    bar_align = options.bar_align
    bar_alternate = options.bar_alternate
    bar_color_b = options.bar_color_b
    bar_center_line_width = options.bar_center_line_width
    waveform_color = options.waveform_color
    glow_level = options.glow_level
    classic_alternate_opacity = options.classic_alternate_opacity
    phases = options.phases

    validate_output_formats(formats)
    started = _utcnow()
    preset = _with_waveform_color(preset, waveform_color)
    if glow_level is None:
        glow_level = default_glow_level(field_geometry)
    preset = _with_glow_level(preset, glow_level)
    preset = _with_classic_alternate_opacity(preset, classic_alternate_opacity)

    appearance: FixedAxisAppearance | None = None
    if job.domain.value == "frequency":
        appearance = resolve_fixed_axis_appearance(
            preset,
            spectrum_contour=spectrum_contour,
            spectrum_spatial_scale=spectrum_spatial_scale,
            spectrum_spatial_filter=spectrum_spatial_filter,
            spectrum_n_bands=spectrum_n_bands,
            spectrum_tilt_db_per_octave=spectrum_tilt_db_per_octave,
            spectrum_compress=spectrum_compress,
            spectrum_recenter=spectrum_recenter,
            spectrum_edge_taper=spectrum_edge_taper,
            visual_geometry=visual_geometry,
            spectrum_layout=spectrum_layout,
            spectrum_slot_sigma=spectrum_slot_sigma,
            ribbon_supersample=ribbon_supersample,
            render_path=render_path,
            render_aa=render_aa,
            field_geometry=field_geometry,
            bar_width=bar_width,
            bar_gap=bar_gap,
            bar_count=bar_count,
            bar_fill=bar_fill,
            bar_align=bar_align,
            bar_alternate=bar_alternate,
            bar_color_b=bar_color_b,
            bar_center_line_width=bar_center_line_width,
        )
    fixed_axis_recipe = appearance.identity() if appearance is not None else None

    def note(message: str) -> None:
        if progress is not None:
            progress(message)

    note(f"hashing {job.path}")
    source_sha = sha256_file(job.path)
    clip_start, clip_duration = _clip_bounds(media, start, duration)
    selection = render_lifecycle.prepare_destinations(
        _lifecycle_hooks(),
        job,
        preset,
        source_sha=source_sha,
        output_dir=output_dir,
        formats=formats,
        force=force,
        clip_start=clip_start,
        clip_duration=clip_duration,
        identity_duration=duration if duration is not None and duration > 0 else None,
        fixed_axis_recipe=fixed_axis_recipe,
    )
    sig = selection.signature
    expected_frames = selection.expected_frames
    lifecycle = render_lifecycle.RenderLifecycle(
        RenderContext(job=job, media=media, preset=preset, performance=performance),
        _lifecycle_hooks(),
        selection,
        source_sha,
        started,
        fixed_axis_recipe,
        clip_start,
        clip_duration,
    )
    if selection.all_reused(force):
        return lifecycle.skipped(note)

    producing_mov = selection.producing_mov
    producing_png = selection.producing_png
    policy = lifecycle.prepare_workdir(keep_temp=keep_temp)
    work = policy.path
    warnings = lifecycle.warnings
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}
    resume_history: list[dict[str, Any]] = []
    clock = phases if phases is not None else PhaseTimes()
    clock.extras.update(
        clip_start_seconds=clip_start,
        effective_audio_seconds=clip_duration,
        expected_frames=expected_frames,
        reused_output_formats=[item["format"] for item in selection.skip_outputs],
        ffmpeg_threads_option_role=(
            "input_rawvideo_decoder" if producing_png and producing_mov else "output_encoder"
        ),
    )
    ribbon_ss = appearance.ribbon_ss if appearance is not None else RIBBON_SUPERSAMPLE
    try:
        lifecycle.verify_source()
        if clip_duration <= 0:
            raise DecodeError("source duration is zero")
        glow = _glow_sigma(preset)
        raw_threads = performance.processing.get("ffmpeg_threads", 0)
        threads = raw_threads if isinstance(raw_threads, int) else 0
        if job.domain.value == "frequency":
            assert appearance is not None
            geometry = appearance.geometry
            scale = str(preset.signal.get("scale") or "sqrt")
            raw_smooth = preset.signal.get("smoothing", 0.0)
            tau = 0.0
            if isinstance(raw_smooth, int | float) and not isinstance(raw_smooth, bool):
                tau = max(0.0, float(raw_smooth))
            norm = preset.signal.get("normalization")
            norm_mode = "auto"
            soft = True
            if isinstance(norm, dict):
                norm_mode = str(norm.get("mode") or "auto")
                soft = bool(norm.get("soft_clip", True))
            note(
                f"{'temporal' if geometry != 'spectrum' else 'spectrum'} decode "
                f"{clip_duration:.1f}s -> {expected_frames} frames @ {job.fps:g} fps"
            )
            reset_workdir(work)
            decoded = work / "source.wav"
            origin_seconds = 0.0
            if geometry != "spectrum":
                half = TEMPORAL_WINDOW_SECONDS / 2.0
                pad_start = max(0.0, clip_start - half)
                pad_end = min(media.duration_seconds, clip_start + clip_duration + half)
                decode_mono_wav(
                    job.path,
                    decoded,
                    start=pad_start if pad_start > 0 else None,
                    duration=max(pad_end - pad_start, clip_duration),
                )
                origin_seconds = clip_start - pad_start
            peak_mix = TEMPORAL_PEAK_MIX if geometry == "temporal_rms_peak" else 0.0
            peak = None
            field_chunk_movs: list[Path] | None = None
            field_encoded = False
            spectrum_encode_workers = 1
            field_plan: RenderPlan | None = None
            bars: BarStyle | None = None
            if geometry != "spectrum":
                samples, rate = load_mono_f32(decoded)
                if norm_mode != "none":
                    note("temporal peak scan")
                    peak = temporal_envelope_peak(
                        samples,
                        rate,
                        n_frames=expected_frames,
                        fps=job.fps,
                        origin_seconds=origin_seconds,
                        width=preset.canvas.width,
                        peak_mix=peak_mix,
                    )
                frames = iter_temporal_frames(
                    samples,
                    rate,
                    n_frames=expected_frames,
                    preset=preset,
                    fps=job.fps,
                    glow=glow,
                    peak=peak,
                    tau_seconds=tau,
                    soft_clip=soft,
                    origin_seconds=origin_seconds,
                    peak_mix=peak_mix,
                )
                analysis = {
                    "chunk_count": 1,
                    "preroll_seconds": TEMPORAL_WINDOW_SECONDS / 2.0,
                    "postroll_seconds": TEMPORAL_WINDOW_SECONDS / 2.0,
                    "encode_workers": 1,
                    "visual_geometry": geometry,
                    "temporal_window_seconds": TEMPORAL_WINDOW_SECONDS,
                    "temporal_bins": TEMPORAL_BINS,
                    "temporal_peak_mix": peak_mix,
                    "spectrum_raster": "contour",
                }
            else:
                spatial_scale = appearance.spatial_scale
                spatial_filter = appearance.spatial_filter
                spatial_sigma = appearance.spatial_sigma
                n_bands = appearance.n_bands
                tilt_db = appearance.tilt_db
                compress = appearance.compress
                recenter = appearance.recenter
                taper = appearance.taper
                layout = appearance.layout
                slot_sigma = appearance.slot_sigma
                bars = appearance.bars
                field_plan = appearance.field_plan
                if layout == "field_center_out":
                    field_bands = n_bands if n_bands is not None else 64
                    mapping = CenterOutMapping(n_slots=CENTER_OUT_SLOTS, n_bands=field_bands)
                    assert bars is not None and field_plan is not None
                    cache_payload = analysis_cache_payload(
                        source_sha256=source_sha,
                        clip_start=clip_start,
                        clip_duration=clip_duration,
                        fps=job.fps,
                        n_frames=expected_frames,
                        n_bands=field_bands,
                        scale=scale,
                        tilt_db_per_octave=tilt_db,
                        compress=compress,
                        signal=preset.signal,
                    )
                    cache_digest = analysis_cache_digest(cache_payload)
                    cached = load_analysis_cache(cache_digest)
                    if cached is not None:
                        sequence, span = cached
                        clock.extras["analysis_cache"] = "hit"
                        note("spectrum analysis cache hit")
                    else:
                        clock.extras["analysis_cache"] = "miss"
                        with clock.span("decode"):
                            decode_mono_wav(
                                job.path,
                                decoded,
                                start=clip_start if clip_start > 0 else None,
                                duration=clip_duration if clip_duration > 0 else None,
                            )
                        with clock.span("pcm_load"):
                            pcm, pcm_rate = load_mono_pcm(decoded)
                        with clock.span("frequency_span"):
                            span = resolve_frequency_span_from_pcm(pcm, pcm_rate, preset.signal)
                        note("spectrum analysis sequence")
                        with clock.span("spectral_analysis"):
                            sequence = build_analysis_sequence(
                                pcm,
                                pcm_rate,
                                n_frames=expected_frames,
                                fps=job.fps,
                                span=span,
                                scale=scale,
                                n_bands=field_bands,
                                tilt_db_per_octave=tilt_db,
                                compress=compress,
                            )
                        store_analysis_cache(cache_digest, sequence, span)
                    if norm_mode != "none":
                        note("spectrum peak scan")
                        with clock.span("peak_scan"):
                            peak = _visual_field_peak(
                                sequence,
                                width=preset.canvas.width,
                                spatial_sigma=spatial_sigma,
                                spatial_filter=spatial_filter,
                                mapping=mapping,
                            )
                    requested_workers = _job_workers(performance)
                    use_pool = requested_workers > 1 and expected_frames >= _FIELD_POOL_MIN_FRAMES
                    if use_pool:
                        pad = glow_overscan(glow)
                        draw_w = preset.canvas.width + 2 * pad
                        with clock.span("visual_field"):
                            column_rows = _precompute_field_columns(
                                sequence,
                                n_frames=expected_frames,
                                draw_w=draw_w,
                                peak=peak,
                                tau_seconds=tau,
                                fps=job.fps,
                                soft_clip=soft,
                                spatial_sigma=spatial_sigma,
                                spatial_filter=spatial_filter,
                                mapping=mapping,
                            )
                        columns_path = work / "field-columns.npy"
                        np.save(columns_path, np.asarray(column_rows, dtype=np.float64))
                        ranges = _field_frame_ranges(len(column_rows), requested_workers)
                        spectrum_encode_workers = len(ranges)
                        worker_threads = _encode_worker_threads(threads, spectrum_encode_workers)
                        clock.extras["ffmpeg_threads_resolved_argument"] = worker_threads
                        png_abs = str((work / "png").resolve()) if producing_png else None
                        if producing_png:
                            (work / "png").mkdir(parents=True, exist_ok=True)
                        tasks = [
                            FieldChunkTask(
                                chunk_index=index,
                                n_chunks=len(ranges),
                                first_frame=start,
                                n_frames=size,
                                columns_path=str(columns_path.resolve()),
                                width=preset.canvas.width,
                                height=preset.canvas.height,
                                fps=job.fps,
                                color=preset.waveform.color,
                                amplitude=preset.waveform.amplitude,
                                center_line=(
                                    bool(preset.waveform.center_line)
                                    and (field_plan.geometry not in BAR_GEOMETRIES)
                                ),
                                content_height=preset.canvas.height,
                                glow=glow,
                                png_dir=png_abs,
                                prores_path=(
                                    str((work / f"field-{index:04d}.mov").resolve())
                                    if producing_mov
                                    else None
                                ),
                                ffmpeg_threads=worker_threads,
                                overscan=pad,
                                supersample=field_plan.supersample if field_plan else ribbon_ss,
                                pix_fmt=field_plan.pix_fmt if field_plan else "rgba",
                                aa_taps=field_plan.aa_taps if field_plan else 1,
                                plan_path=field_plan.path if field_plan else "rgba_2d",
                                geometry=field_plan.geometry if field_plan else "ribbon",
                                bar_width=bars.width,
                                bar_gap=bars.gap,
                                bar_count=0 if bars.count is None else bars.count,
                                bar_fill=bars.fill,
                                bar_align=bars.align,
                                bar_alternate=bars.alternate,
                                bar_color_b=bars.color_b,
                                bar_center_line_width=bars.center_line_width,
                            )
                            for index, (start, size) in enumerate(ranges)
                        ]
                        note(
                            f"spectrum encode {len(column_rows)} frames "
                            f"with {spectrum_encode_workers} process(es)"
                        )
                        with clock.span("field_encode_parallel"):
                            ctx = multiprocessing.get_context("spawn")
                            with ProcessPoolExecutor(
                                max_workers=spectrum_encode_workers, mp_context=ctx
                            ) as pool:
                                parts = list(pool.map(encode_field_chunk, tasks))
                        field_chunk_movs = [path for path in parts if path is not None]
                        field_encoded = True
                        frames = iter(())
                    else:
                        frames = iter_field_frames(
                            sequence,
                            n_frames=expected_frames,
                            preset=preset,
                            fps=job.fps,
                            glow=glow,
                            peak=peak,
                            tau_seconds=tau,
                            soft_clip=soft,
                            spatial_sigma=spatial_sigma,
                            spatial_filter=spatial_filter,
                            mapping=mapping,
                            supersample=ribbon_ss,
                            plan=field_plan,
                            bar_style=bars,
                            phases=clock,
                        )
                else:
                    with clock.span("decode"):
                        decode_mono_wav(
                            job.path,
                            decoded,
                            start=clip_start if clip_start > 0 else None,
                            duration=clip_duration if clip_duration > 0 else None,
                        )
                    with clock.span("pcm_load"):
                        pcm, pcm_rate = load_mono_pcm(decoded)
                    with clock.span("frequency_span"):
                        span = resolve_frequency_span_from_pcm(pcm, pcm_rate, preset.signal)
                    if norm_mode != "none":
                        note("spectrum peak scan")
                        peak = spectrum_peak(
                            decoded,
                            n_frames=expected_frames,
                            fps=job.fps,
                            width=preset.canvas.width,
                            span=span,
                            scale=scale,
                            smoothing_sigma=spatial_sigma,
                            spatial_filter=spatial_filter,
                            n_bands=n_bands,
                            tilt_db_per_octave=tilt_db,
                            compress=compress,
                        )
                    frames = iter_spectrum_frames(
                        decoded,
                        n_frames=expected_frames,
                        preset=preset,
                        fps=job.fps,
                        glow=glow,
                        span=span,
                        peak=peak,
                        scale=scale,
                        tau_seconds=tau,
                        soft_clip=soft,
                        contour=spectrum_contour,
                        spatial_sigma=spatial_sigma,
                        spatial_filter=spatial_filter,
                        n_bands=n_bands,
                        tilt_db_per_octave=tilt_db,
                        compress=compress,
                        recenter=recenter,
                        edge_taper=taper,
                        layout=layout,
                        slot_sigma=slot_sigma,
                        supersample=ribbon_ss,
                    )
            png_work: Path | None = work / "png" if producing_png else None
            mov_work: Path | None = work / "spectrum.mov" if producing_mov else None
            encode_label = "temporal" if geometry != "spectrum" else "spectrum"
            if field_plan is not None:
                overscan = glow_overscan(glow)
                clock.extras["render_path"] = field_plan.path
                clock.extras["bytes_per_frame"] = field_plan.bytes_per_frame(
                    preset.canvas.width, preset.canvas.height, overscan
                )
                clock.extras["fingerprint"] = fingerprint_from_plan(
                    plan_path=field_plan.path,
                    geometry=field_plan.geometry,
                    style=preset.waveform.style,
                    glow=glow > 0.0,
                    particles=False,
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    fps=job.fps,
                    aa_mode=field_plan.aa_mode,
                    supersample=field_plan.supersample,
                    pix_fmt=field_plan.pix_fmt,
                    codec="prores4444" if producing_mov else "png",
                    jobs=spectrum_encode_workers,
                    ffmpeg_threads=threads,
                ).as_dict()
            if field_encoded:
                if mov_work is not None:
                    note(f"{encode_label} concat {len(field_chunk_movs or [])} chunk(s)")
                    with clock.span("concat"):
                        concat_videos(
                            field_chunk_movs or [],
                            mov_work,
                            list_path=work / "field.concat.txt",
                        )
            else:
                note(f"{encode_label} encode")
                encode_ss = (
                    field_plan.supersample
                    if field_plan is not None
                    else (ribbon_ss if geometry == "spectrum" else SCROLL_SUPERSAMPLE)
                )
                encode_rgba_stream(
                    _tick_frames(
                        frames,
                        n_frames=expected_frames,
                        note=note,
                        label=encode_label,
                    ),
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    fps=job.fps,
                    glow=glow,
                    png_dir=png_work,
                    prores_path=mov_work,
                    ffmpeg_threads=threads,
                    overscan=glow_overscan(glow),
                    supersample=encode_ss,
                    phases=clock,
                    pix_fmt=field_plan.pix_fmt if field_plan is not None else "rgba",
                    color=(
                        preset.waveform.color
                        if field_plan is not None and field_plan.colorize
                        else None
                    ),
                    n_frames=expected_frames,
                )
            if mov_work is not None:
                lifecycle.publish_mov(mov_work, failure_message="spectrum output failed validation")
            if png_work is not None:
                lifecycle.publish_png(png_work)
            if geometry == "spectrum":
                analysis = {
                    "chunk_count": spectrum_encode_workers if field_encoded else 1,
                    "preroll_seconds": 0.0,
                    "postroll_seconds": 0.0,
                    "encode_workers": spectrum_encode_workers,
                    "visual_geometry": "spectrum",
                    "fmin_hz": span.fmin_hz,
                    "fmax_hz": span.fmax_hz,
                    "frequency_range": span.source,
                    "spectrum_raster": "contour" if spectrum_contour else "columns",
                    "spectrum_spatial_filter": spatial_filter,
                    "spectrum_spatial_sigma": spatial_sigma,
                    "spectrum_spatial_scale": float(spatial_scale),
                    "spectrum_n_bands": n_bands,
                    "spectrum_tilt_db_per_octave": tilt_db,
                    "spectrum_compress": compress,
                    "spectrum_recenter": recenter,
                    "spectrum_edge_taper": taper,
                    "spectrum_layout": layout,
                    "spectrum_slot_sigma": slot_sigma,
                    "visual_pipeline": (
                        "analysis_field_ribbon" if layout == "field_center_out" else "legacy"
                    ),
                    "field_geometry": (field_plan.geometry if field_plan is not None else "legacy"),
                    "bar_width": bars.width if bars is not None else None,
                    "bar_gap": bars.gap if bars is not None else None,
                    "visual_slots": CENTER_OUT_SLOTS if layout == "field_center_out" else None,
                    "ribbon_supersample": ribbon_ss,
                    "render_path": field_plan.path if field_plan is not None else "rgba_2d",
                    "render_pix_fmt": field_plan.pix_fmt if field_plan is not None else "rgba",
                    "render_aa_mode": (
                        field_plan.aa_mode if field_plan is not None else "physical_ss"
                    ),
                }
            normalization = {"mode": norm_mode, "soft_clip": soft, "peak": peak}
        else:
            mov_work, png_work = render_scroll.run_scroll_pipeline(
                _scroll_hooks(),
                job=job,
                preset=preset,
                performance=performance,
                source_sha=source_sha,
                sig=sig,
                clip_start=clip_start,
                clip_duration=clip_duration,
                expected_frames=expected_frames,
                work=work,
                producing_mov=producing_mov,
                producing_png=producing_png,
                glow=glow,
                threads=threads,
                fail_after_chunk=fail_after_chunk,
                note=note,
                analysis=analysis,
                normalization=normalization,
                warnings=warnings,
                resume_history=resume_history,
                clock=clock,
            )
            if mov_work is not None:
                lifecycle.publish_mov(mov_work, failure_message="scroll output failed validation")
            if png_work is not None:
                lifecycle.publish_png(png_work)
        lifecycle.mark_succeeded()
    except (DecodeError, EncodeError, OSError, RuntimeError, ProbeError) as exc:
        return lifecycle.failed(
            exc,
            policy,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
            clock=clock,
        )
    else:
        return lifecycle.succeeded(
            policy,
            keep_temp=keep_temp,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
            clock=clock,
        )


def encode_scroll_chunk(
    task: ChunkEncodeTask, note: Callable[[str], None] | None = None
) -> ChunkRecord:
    return render_scroll.encode_scroll_chunk(_scroll_hooks(), task, note)


def _chunk_task(
    window: ProcessingWindow,
    prepared: PreparedChunk,
    *,
    n_windows: int,
    preset: VisualPreset,
    clip_duration: float,
    fps: float,
    glow: float,
    png_work: Path | None,
    work: Path,
    producing_mov: bool,
    ffmpeg_threads: int,
    shutter_px: float,
    shutter_mix: float,
) -> ChunkEncodeTask:
    return render_scroll._chunk_task(
        _scroll_hooks(),
        window,
        prepared,
        n_windows=n_windows,
        preset=preset,
        clip_duration=clip_duration,
        fps=fps,
        glow=glow,
        png_work=png_work,
        work=work,
        producing_mov=producing_mov,
        ffmpeg_threads=ffmpeg_threads,
        shutter_px=shutter_px,
        shutter_mix=shutter_mix,
    )


def _run_scroll_encodes(
    *,
    windows: Sequence[ProcessingWindow],
    prepared_by_index: dict[int, PreparedChunk],
    completed_ok: set[int],
    preset: VisualPreset,
    clip_duration: float,
    fps: float,
    glow: float,
    png_work: Path | None,
    work: Path,
    producing_mov: bool,
    ffmpeg_threads: int,
    shutter_px: float,
    shutter_mix: float,
    workers: int,
    fail_after_chunk: int | None,
    checkpoint: Checkpoint,
    cp_file: Path,
    note: Callable[[str], None],
) -> tuple[list[int], int]:
    return render_scroll._run_scroll_encodes(
        _scroll_hooks(),
        windows=windows,
        prepared_by_index=prepared_by_index,
        completed_ok=completed_ok,
        preset=preset,
        clip_duration=clip_duration,
        fps=fps,
        glow=glow,
        png_work=png_work,
        work=work,
        producing_mov=producing_mov,
        ffmpeg_threads=ffmpeg_threads,
        shutter_px=shutter_px,
        shutter_mix=shutter_mix,
        workers=workers,
        fail_after_chunk=fail_after_chunk,
        checkpoint=checkpoint,
        cp_file=cp_file,
        note=note,
    )


def _prepare_chunk_envelopes(
    source: Path,
    windows: Sequence[ProcessingWindow],
    settings: EnvelopeSettings,
    *,
    work: Path,
    clip_start: float,
    width: int,
    window_seconds: float,
) -> list[PreparedChunk]:
    return render_scroll._prepare_chunk_envelopes(
        _scroll_hooks(),
        source,
        windows,
        settings,
        work=work,
        clip_start=clip_start,
        width=width,
        window_seconds=window_seconds,
    )


def _result_payload(
    job: PlannedJob,
    media: SourceMedia,
    preset: VisualPreset,
    performance: PerformanceProfile,
    source_sha: str,
    sig: str,
    started: str,
    *,
    status: str,
    outputs: list[dict[str, Any]],
    warnings: list[Diagnostic],
    workdir: str | None = None,
    validation: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    normalization: dict[str, Any] | None = None,
    resume_history: list[dict[str, Any]] | None = None,
    phase_report: dict[str, Any] | None = None,
    fixed_axis_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return render_lifecycle._result_payload(
        _lifecycle_hooks(),
        job,
        media,
        preset,
        performance,
        source_sha,
        sig,
        started,
        status=status,
        outputs=outputs,
        warnings=warnings,
        workdir=workdir,
        validation=validation,
        analysis=analysis,
        normalization=normalization,
        resume_history=resume_history,
        phase_report=phase_report,
        fixed_axis_recipe=fixed_axis_recipe,
    )
