"""Render orchestration: workdir, envelope scroll, experimental spectrum, publish."""

from __future__ import annotations

import multiprocessing as multiprocessing
import shutil as shutil
import sys
import time as time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor as ProcessPoolExecutor
from concurrent.futures import as_completed as as_completed
from datetime import UTC, datetime
from pathlib import Path as Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ewp_waveform.application.experiments_render import ServiceExperiment

import numpy as _np

from ewp_waveform import __version__ as __version__
from ewp_waveform.analysis.cache import analysis_cache_digest as analysis_cache_digest
from ewp_waveform.analysis.cache import analysis_cache_payload as analysis_cache_payload
from ewp_waveform.analysis.cache import load_analysis_cache as load_analysis_cache
from ewp_waveform.analysis.cache import store_analysis_cache as store_analysis_cache
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
from ewp_waveform.analysis.spectrum import PIVOT_TAU_SECONDS as PIVOT_TAU_SECONDS
from ewp_waveform.analysis.spectrum import FrequencySpan
from ewp_waveform.analysis.spectrum import apply_edge_taper as apply_edge_taper
from ewp_waveform.analysis.spectrum import apply_spectrum_spatial as apply_spectrum_spatial
from ewp_waveform.analysis.spectrum import blend_columns as blend_columns
from ewp_waveform.analysis.spectrum import build_analysis_sequence as build_analysis_sequence
from ewp_waveform.analysis.spectrum import dominant_band_pivot as dominant_band_pivot
from ewp_waveform.analysis.spectrum import ema_alpha as ema_alpha
from ewp_waveform.analysis.spectrum import fold_bands_center_out as fold_bands_center_out
from ewp_waveform.analysis.spectrum import gaussian_smooth as gaussian_smooth
from ewp_waveform.analysis.spectrum import load_mono_pcm as load_mono_pcm
from ewp_waveform.analysis.spectrum import (
    resolve_frequency_span_from_pcm as resolve_frequency_span_from_pcm,
)
from ewp_waveform.analysis.spectrum import spectrum_bands as spectrum_bands
from ewp_waveform.analysis.spectrum import spectrum_columns as spectrum_columns
from ewp_waveform.analysis.spectrum import spectrum_peak as spectrum_peak
from ewp_waveform.analysis.spectrum import upsample_bands as upsample_bands
from ewp_waveform.analysis.temporal import TEMPORAL_BINS as TEMPORAL_BINS
from ewp_waveform.analysis.temporal import TEMPORAL_PEAK_MIX as TEMPORAL_PEAK_MIX
from ewp_waveform.analysis.temporal import TEMPORAL_WINDOW_SECONDS as TEMPORAL_WINDOW_SECONDS
from ewp_waveform.analysis.temporal import load_mono_f32 as load_mono_f32
from ewp_waveform.analysis.temporal import temporal_envelope_columns as temporal_envelope_columns
from ewp_waveform.analysis.temporal import temporal_envelope_peak as temporal_envelope_peak
from ewp_waveform.application import render_fixed, render_lifecycle, render_scroll
from ewp_waveform.application.appearance import (
    FixedAxisAppearance as FixedAxisAppearance,
)
from ewp_waveform.application.appearance import (
    normalize_spatial_filter as _normalize_spatial_filter,
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
from ewp_waveform.application.evidence import fingerprint_from_plan as fingerprint_from_plan
from ewp_waveform.application.formats import validate_output_formats as validate_output_formats
from ewp_waveform.application.render_fixed import (
    _FIELD_POOL_MIN_FRAMES as _FIELD_POOL_MIN_FRAMES,
)
from ewp_waveform.application.render_fixed import (
    FieldChunkTask as FieldChunkTask,
)
from ewp_waveform.application.render_pipelines import PipelineHooks, PipelineRun, select_pipeline
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
from ewp_waveform.config.ribbon import CONFIGURABLE_RIBBON_PROFILES, apply_public_appearance
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
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE
from ewp_waveform.ffmpeg.draw import (
    SCROLL_SUPERSAMPLE as SCROLL_SUPERSAMPLE,
)
from ewp_waveform.ffmpeg.draw import (
    draw_envelope_frame as draw_envelope_frame,
)
from ewp_waveform.ffmpeg.draw import draw_spectrum_frame as draw_spectrum_frame
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
from ewp_waveform.visual.bars import BarStyle as BarStyle
from ewp_waveform.visual.mapping import CENTER_OUT_SLOTS as CENTER_OUT_SLOTS
from ewp_waveform.visual.mapping import CenterOutMapping as CenterOutMapping
from ewp_waveform.visual.plan import RenderPlan as RenderPlan
from ewp_waveform.visual.plan import resolve_render_plan as resolve_render_plan
from ewp_waveform.visual.raster import raster_field_columns as raster_field_columns
from ewp_waveform.visual.ribbon import field_to_columns as field_to_columns
from ewp_waveform.visual.style_defaults import BAR_GEOMETRIES as BAR_GEOMETRIES
from ewp_waveform.visual.style_defaults import default_glow_level

# Explicit compatibility exports retain the same imported helper/module objects.
np = _np
_spectrum_spatial_filter = _normalize_spatial_filter


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


def _fixed_hooks() -> render_fixed.FixedHooks:
    """Keep fixed-axis helper/worker lookups live without a reverse import."""
    return cast(render_fixed.FixedHooks, sys.modules[__name__])


def _scroll_hooks() -> render_scroll.ScrollHooks:
    """Keep helper and worker lookups live without a reverse pipeline import."""
    return cast(render_scroll.ScrollHooks, sys.modules[__name__])


def _pipeline_hooks() -> PipelineHooks:
    """Expose live pipeline hook accessors without importing render back."""
    return cast(PipelineHooks, sys.modules[__name__])


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
    return render_fixed.iter_spectrum_frames(
        _fixed_hooks(),
        path,
        n_frames=n_frames,
        preset=preset,
        fps=fps,
        glow=glow,
        span=span,
        peak=peak,
        scale=scale,
        tau_seconds=tau_seconds,
        soft_clip=soft_clip,
        contour=contour,
        spatial_sigma=spatial_sigma,
        spatial_filter=spatial_filter,
        n_bands=n_bands,
        tilt_db_per_octave=tilt_db_per_octave,
        compress=compress,
        recenter=recenter,
        edge_taper=edge_taper,
        layout=layout,
        slot_sigma=slot_sigma,
        supersample=supersample,
    )


def _visual_field_peak(
    sequence: AnalysisSequence,
    *,
    width: int,
    spatial_sigma: float,
    spatial_filter: str,
    mapping: CenterOutMapping,
) -> float:
    return render_fixed._visual_field_peak(
        _fixed_hooks(),
        sequence,
        width=width,
        spatial_sigma=spatial_sigma,
        spatial_filter=spatial_filter,
        mapping=mapping,
    )


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
    return render_fixed.iter_field_frames(
        _fixed_hooks(),
        sequence,
        n_frames=n_frames,
        preset=preset,
        fps=fps,
        glow=glow,
        peak=peak,
        tau_seconds=tau_seconds,
        soft_clip=soft_clip,
        spatial_sigma=spatial_sigma,
        spatial_filter=spatial_filter,
        mapping=mapping,
        supersample=supersample,
        plan=plan,
        bar_style=bar_style,
        phases=phases,
    )


# Spawn+concat loses to the fused generator on short clips (8 s @ 60 fps).


def _field_frame_ranges(n_frames: int, workers: int) -> list[tuple[int, int]]:
    return render_fixed._field_frame_ranges(
        _fixed_hooks(),
        n_frames,
        workers,
    )


def encode_field_chunk(task: FieldChunkTask) -> Path | None:
    return render_fixed.encode_field_chunk(
        _fixed_hooks(),
        task,
    )


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
    return render_fixed._precompute_field_columns(
        _fixed_hooks(),
        sequence,
        n_frames=n_frames,
        draw_w=draw_w,
        peak=peak,
        tau_seconds=tau_seconds,
        fps=fps,
        soft_clip=soft_clip,
        spatial_sigma=spatial_sigma,
        spatial_filter=spatial_filter,
        mapping=mapping,
        phases=phases,
    )


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
    return render_fixed.iter_temporal_frames(
        _fixed_hooks(),
        samples,
        rate,
        n_frames=n_frames,
        preset=preset,
        fps=fps,
        glow=glow,
        peak=peak,
        tau_seconds=tau_seconds,
        soft_clip=soft_clip,
        origin_seconds=origin_seconds,
        peak_mix=peak_mix,
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
    experiment: ServiceExperiment | None = None,
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
    outcome = (
        _render_job(context, options)
        if experiment is None
        else _render_job(context, options, experiment=experiment)
    )
    return outcome.payload


def _render_job(
    context: RenderContext,
    options: RenderOptions,
    *,
    experiment: ServiceExperiment | None = None,
) -> RendererOutcome:
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
    # Preserve the complete legacy raw-binding prefix for compatibility.
    # Fixed-only aliases remain carried unchanged in options for the pipeline.
    del (
        spectrum_spatial_scale,
        spectrum_spatial_filter,
        spectrum_n_bands,
        spectrum_tilt_db_per_octave,
        spectrum_compress,
        spectrum_recenter,
        spectrum_edge_taper,
        visual_geometry,
        spectrum_layout,
        spectrum_slot_sigma,
        ribbon_supersample,
        render_path,
        render_aa,
        bar_width,
        bar_gap,
        bar_count,
        bar_fill,
        bar_align,
        bar_alternate,
        bar_color_b,
        bar_center_line_width,
    )

    if experiment is not None:
        experiment.validate(job, preset, formats, duration)
    validate_output_formats(formats)
    started = _utcnow()
    if preset.signal.get("fixed_axis_profile") in CONFIGURABLE_RIBBON_PROFILES:
        if classic_alternate_opacity is not None:
            raise ValueError("filled-ribbon-v2 does not support classic_alternate_opacity")
        preset = apply_public_appearance(
            preset, waveform_color=waveform_color, glow_level=glow_level
        )
        waveform_color = None
        glow_level = None
    preset = _with_waveform_color(preset, waveform_color)
    if glow_level is None:
        glow_level = default_glow_level(field_geometry)
    preset = _with_glow_level(preset, glow_level)
    preset = _with_classic_alternate_opacity(preset, classic_alternate_opacity)

    appearance = select_pipeline(job.domain.value).prepare(_pipeline_hooks(), preset, options)
    ribbon_finish_lut = performance.processing.get("ribbon_finish_lut", False)
    if type(ribbon_finish_lut) is not bool:
        raise ValueError("processing.ribbon_finish_lut must be an explicit boolean")
    if ribbon_finish_lut and (
        appearance is None
        or appearance.ribbon_finish is None
        or set(options.formats) != {"prores4444"}
        or experiment is not None
    ):
        raise ValueError(
            "ribbon_finish_lut requires ordinary CPU ribbon finishing and one MOV/no PNG"
        )
    fixed_axis_recipe = appearance.identity() if appearance is not None else None
    lifecycle_hooks = _lifecycle_hooks()
    pipeline_hooks = _pipeline_hooks()
    if experiment is not None:
        fixed_axis_recipe = {**(fixed_axis_recipe or {}), "experiment": experiment.identity()}
        lifecycle_hooks = experiment.lifecycle_hooks(lifecycle_hooks)
        pipeline_hooks = experiment.pipeline_hooks(pipeline_hooks)

    def note(message: str) -> None:
        if progress is not None:
            progress(message)

    note(f"hashing {job.path}")
    source_sha = sha256_file(job.path)
    clip_start, clip_duration = _clip_bounds(media, start, duration)
    selection = render_lifecycle.prepare_destinations(
        lifecycle_hooks,
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
        lifecycle_hooks,
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
        select_pipeline(job.domain.value).run(
            pipeline_hooks,
            PipelineRun(
                context=RenderContext(job=job, media=media, preset=preset, performance=performance),
                appearance=appearance,
                spectrum_contour=spectrum_contour,
                ribbon_ss=ribbon_ss,
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
                lifecycle=lifecycle,
                analysis=analysis,
                normalization=normalization,
                warnings=warnings,
                resume_history=resume_history,
                clock=clock,
            ),
        )
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
