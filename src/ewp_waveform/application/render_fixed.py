"""Fixed-axis settings, frame generation, field staging, cache and encode orchestration.

The typed hook view is the live dispatcher, not a registry or callback snapshot.
Only existing scalar task payloads cross the spawn boundary. Lifecycle retains
validation/publication implementation; calls retain their report/failure ordering.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from ewp_waveform.analysis.frames import AnalysisSequence
from ewp_waveform.analysis.spectrum import Float64, FrequencySpan
from ewp_waveform.application.appearance import FixedAxisAppearance
from ewp_waveform.application.evidence import PerformanceFingerprint
from ewp_waveform.application.render_types import RenderOptions
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE
from ewp_waveform.visual.bars import BarStyle
from ewp_waveform.visual.mapping import CenterOutMapping
from ewp_waveform.visual.models import VisualField
from ewp_waveform.visual.plan import AAMode, RenderPath, RenderPlan


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


# Keep the selected-base pool admission threshold.
_FIELD_POOL_MIN_FRAMES = 1800

type _Path = Path
type _BarStyle = BarStyle
type _CenterOutMapping = CenterOutMapping
type _RenderPlan = RenderPlan
type _FieldChunkTask = FieldChunkTask
type _ProcessPoolExecutor = ProcessPoolExecutor


class FixedHooks(Protocol):
    """Live dispatcher helpers; this view never enters a spawn payload."""

    Path: type[_Path]
    BarStyle: type[_BarStyle]
    CenterOutMapping: type[_CenterOutMapping]
    RenderPlan: type[_RenderPlan]
    FieldChunkTask: type[_FieldChunkTask]
    ProcessPoolExecutor: type[_ProcessPoolExecutor]
    np: ModuleType
    time: ModuleType
    multiprocessing: ModuleType
    BAR_GEOMETRIES: frozenset[str]
    CENTER_OUT_SLOTS: int
    PIVOT_TAU_SECONDS: float
    SCROLL_SUPERSAMPLE: int
    TEMPORAL_BINS: int
    TEMPORAL_PEAK_MIX: float
    TEMPORAL_WINDOW_SECONDS: float
    _FIELD_POOL_MIN_FRAMES: int

    def _encode_worker_threads(self, configured: int, workers: int) -> int: ...

    def _field_frame_ranges(self, n_frames: int, workers: int) -> list[tuple[int, int]]: ...

    def _job_workers(self, performance: PerformanceProfile) -> int: ...

    def _precompute_field_columns(
        self,
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
        mapping: _CenterOutMapping,
        phases: PhaseTimes | None = ...,
    ) -> list[list[float]]: ...

    def _spectrum_spatial_filter(self, kind: str) -> str: ...

    def _tick_frames(
        self, frames: Iterator[bytes], *, n_frames: int, note: Callable[[str], None], label: str
    ) -> Iterator[bytes]: ...

    def _visual_field_peak(
        self,
        sequence: AnalysisSequence,
        *,
        width: int,
        spatial_sigma: float,
        spatial_filter: str,
        mapping: _CenterOutMapping,
    ) -> float: ...

    def analysis_cache_digest(self, payload: dict[str, Any]) -> str: ...

    def analysis_cache_payload(
        self,
        *,
        source_sha256: str,
        clip_start: float,
        clip_duration: float,
        fps: float,
        n_frames: int,
        n_bands: int,
        scale: str,
        tilt_db_per_octave: float,
        compress: float,
        signal: dict[str, object],
    ) -> dict[str, Any]: ...

    def apply_edge_taper(
        self, columns: Sequence[float], *, content_width: int, pad: int = ..., fraction: float = ...
    ) -> list[float]: ...

    def apply_spectrum_spatial(
        self, columns: Sequence[float], *, sigma: float, kind: str = ...
    ) -> list[float]: ...

    def bin_peak(self, bins: Sequence[float], percentile: float = ...) -> float: ...

    def blend_columns(
        self, previous: Sequence[float] | None, current: Sequence[float], alpha: float
    ) -> list[float]: ...

    def build_analysis_sequence(
        self,
        pcm: Float64,
        sample_rate: int,
        *,
        n_frames: int,
        fps: float,
        span: FrequencySpan,
        scale: str,
        n_bands: int,
        tilt_db_per_octave: float,
        compress: float,
    ) -> AnalysisSequence: ...

    def concat_videos(
        self, parts: Sequence[_Path], dest: _Path, *, list_path: _Path | None = ...
    ) -> None: ...

    def decode_mono_wav(
        self,
        source: _Path,
        dest: _Path,
        sample_rate: int = ...,
        start: float | None = ...,
        duration: float | None = ...,
    ) -> None: ...

    def dominant_band_pivot(self, bands: Sequence[float]) -> float: ...

    def draw_envelope_frame(
        self,
        columns: Sequence[float],
        *,
        width: int,
        height: int,
        color: str,
        amplitude: float,
        stroke_width: float,
        style: str,
        center_line: bool,
        scroll_phase: float = ...,
        vertical_margin: int = ...,
        content_height: int | None = ...,
        supersample: int = ...,
        glow_sigma: float = ...,
        envelope_oversample: int = ...,
        classic_alternate_opacity: float = ...,
    ) -> bytes: ...

    def draw_spectrum_frame(
        self,
        columns: Sequence[float],
        *,
        width: int,
        height: int,
        color: str,
        amplitude: float,
        center_line: bool,
        content_height: int | None = ...,
        supersample: int = ...,
        glow_sigma: float = ...,
        vertical_margin: int = ...,
        aa_taps: int = ...,
    ) -> bytes: ...

    def ema_alpha(self, fps: float, tau_seconds: float) -> float: ...

    def encode_field_chunk(self, task: _FieldChunkTask) -> _Path | None: ...

    def encode_rgba_stream(
        self,
        frames: Iterable[bytes],
        *,
        width: int,
        height: int,
        fps: float,
        glow: float,
        png_dir: _Path | None,
        prores_path: _Path | None,
        ffmpeg_threads: int = ...,
        overscan: int = ...,
        supersample: int = ...,
        shutter_px: float = ...,
        shutter_mix: float = ...,
        png_start_number: int = ...,
        phases: Any | None = ...,
        pix_fmt: str = ...,
        color: str | None = ...,
        n_frames: int | None = ...,
    ) -> None: ...

    def field_to_columns(self, field: VisualField, width: int) -> list[float]: ...

    def fingerprint_from_plan(
        self,
        *,
        plan_path: str,
        geometry: str,
        style: str,
        glow: bool,
        particles: bool,
        width: int,
        height: int,
        fps: float,
        aa_mode: str,
        supersample: int,
        pix_fmt: str,
        codec: str,
        jobs: int,
        ffmpeg_threads: int,
        renderer: str = ...,
    ) -> PerformanceFingerprint: ...

    def fold_bands_center_out(self, bands: Sequence[float]) -> list[float]: ...

    def gaussian_smooth(self, values: Sequence[float], *, sigma: float) -> list[float]: ...

    def glow_overscan(self, sigma: float) -> int: ...

    def iter_field_frames(
        self,
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
        mapping: _CenterOutMapping,
        supersample: int = ...,
        plan: _RenderPlan | None = ...,
        bar_style: _BarStyle | None = ...,
        phases: PhaseTimes | None = ...,
    ) -> Iterator[bytes]: ...

    def iter_spectrum_frames(
        self,
        path: _Path,
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
        contour: bool = ...,
        spatial_sigma: float = ...,
        spatial_filter: str = ...,
        n_bands: int | None = ...,
        tilt_db_per_octave: float = ...,
        compress: float = ...,
        recenter: bool = ...,
        edge_taper: float = ...,
        layout: str = ...,
        slot_sigma: float = ...,
        supersample: int = ...,
    ) -> Iterator[bytes]: ...

    def iter_temporal_frames(
        self,
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
    ) -> Iterator[bytes]: ...

    def load_analysis_cache(
        self, digest: str, *, directory: _Path | None = ...
    ) -> tuple[AnalysisSequence, FrequencySpan] | None: ...

    def load_mono_f32(self, path: _Path) -> tuple[list[float], int]: ...

    def load_mono_pcm(self, path: _Path) -> tuple[Float64, int]: ...

    def normalize_bins(
        self,
        bins: Sequence[float],
        *,
        percentile: float = ...,
        soft_clip: bool = ...,
        knee: float = ...,
        peak: float | None = ...,
    ) -> list[float]: ...

    def raster_field_columns(
        self,
        columns: Sequence[float],
        *,
        plan: _RenderPlan,
        width: int,
        height: int,
        color: str,
        amplitude: float,
        center_line: bool,
        content_height: int | None = ...,
        glow_sigma: float = ...,
        bar_style: _BarStyle | None = ...,
    ) -> bytes: ...

    def reset_workdir(self, work: _Path) -> None: ...

    def resolve_fixed_axis_appearance(
        self,
        preset: VisualPreset,
        *,
        spectrum_contour: bool = ...,
        spectrum_spatial_scale: float = ...,
        spectrum_spatial_filter: str = ...,
        spectrum_n_bands: int | None = ...,
        spectrum_tilt_db_per_octave: float = ...,
        spectrum_compress: float = ...,
        spectrum_recenter: bool = ...,
        spectrum_edge_taper: float = ...,
        visual_geometry: str = ...,
        spectrum_layout: str = ...,
        spectrum_slot_sigma: float = ...,
        ribbon_supersample: int | None = ...,
        render_path: str | None = ...,
        render_aa: str | None = ...,
        field_geometry: str = ...,
        bar_width: float | None = ...,
        bar_gap: float | None = ...,
        bar_count: int | None = ...,
        bar_fill: float | None = ...,
        bar_align: str | None = ...,
        bar_alternate: bool | None = ...,
        bar_color_b: str | None = ...,
        bar_center_line_width: float | None = ...,
    ) -> FixedAxisAppearance: ...

    def resolve_frequency_span_from_pcm(
        self, pcm: Float64, rate: int, signal: dict[str, object]
    ) -> FrequencySpan: ...

    def resolve_render_plan(
        self,
        preset: VisualPreset,
        *,
        layout: str = ...,
        field_geometry: str = ...,
        ribbon_supersample: int | None = ...,
        force_path: RenderPath | None = ...,
        aa_mode: AAMode | None = ...,
        alternate_bars: bool = ...,
    ) -> _RenderPlan: ...

    def spectrum_bands(
        self,
        path: _Path,
        *,
        frame_index: int,
        fps: float,
        span: FrequencySpan,
        scale: str,
        n_bands: int,
        tilt_db_per_octave: float,
        compress: float,
    ) -> list[float]: ...

    def spectrum_columns(
        self,
        path: _Path,
        *,
        frame_index: int,
        fps: float,
        width: int,
        span: FrequencySpan,
        scale: str,
        smoothing_sigma: float,
        spatial_filter: str = ...,
        n_bands: int | None = ...,
        tilt_db_per_octave: float = ...,
        compress: float = ...,
        pivot: float | None = ...,
    ) -> list[float]: ...

    def spectrum_peak(
        self,
        path: _Path,
        *,
        n_frames: int,
        fps: float,
        width: int,
        span: FrequencySpan,
        scale: str,
        smoothing_sigma: float,
        spatial_filter: str = ...,
        n_bands: int | None = ...,
        tilt_db_per_octave: float = ...,
        compress: float = ...,
    ) -> float: ...

    def store_analysis_cache(
        self,
        digest: str,
        sequence: AnalysisSequence,
        span: FrequencySpan,
        *,
        directory: _Path | None = ...,
    ) -> _Path: ...

    def temporal_envelope_columns(
        self,
        samples: list[float],
        rate: int,
        *,
        time_seconds: float,
        width: int,
        peak_mix: float = ...,
    ) -> list[float]: ...

    def temporal_envelope_peak(
        self,
        samples: list[float],
        rate: int,
        *,
        n_frames: int,
        fps: float,
        origin_seconds: float,
        width: int,
        peak_mix: float = ...,
    ) -> float: ...

    def upsample_bands(
        self, bands: Sequence[float], width: int, *, pivot: float | None = ...
    ) -> list[float]: ...


class FixedPublication(Protocol):
    """Existing lifecycle publication seam, never a replacement implementation."""

    def publish_mov(self, path: Path, *, failure_message: str) -> None: ...

    def publish_png(self, path: Path) -> None: ...


def iter_spectrum_frames(
    hooks: FixedHooks,
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
    pad = hooks.glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    alpha = hooks.ema_alpha(fps, tau_seconds)
    pivot_alpha = hooks.ema_alpha(fps, hooks.PIVOT_TAU_SECONDS)
    previous: list[float] | None = None
    pivot: float | None = None
    filt = hooks._spectrum_spatial_filter(spatial_filter)
    taper = edge_taper if edge_taper > 0.0 else 0.0
    ss = max(1, int(supersample))
    for i in range(n_frames):
        if n_bands is not None:
            bands = hooks.spectrum_bands(
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
                slots = hooks.fold_bands_center_out(bands)
                if slot_sigma > 0.0:
                    slots = hooks.gaussian_smooth(slots, sigma=slot_sigma)
                raw = hooks.upsample_bands(slots, draw_w, pivot=None)
            else:
                layout_pivot: float | None = None
                if recenter:
                    instant = hooks.dominant_band_pivot(bands)
                    if pivot is None:
                        pivot = instant
                    else:
                        pivot = pivot_alpha * instant + (1.0 - pivot_alpha) * pivot
                    layout_pivot = pivot
                raw = hooks.upsample_bands(bands, draw_w, pivot=layout_pivot)
            raw = hooks.apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        else:
            raw = hooks.spectrum_columns(
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
            raw = hooks.normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = hooks.blend_columns(previous, raw, alpha)
        previous = blended
        if taper > 0.0:
            blended = hooks.apply_edge_taper(
                blended,
                content_width=width,
                pad=pad,
                fraction=taper,
            )
        if contour:
            yield hooks.draw_spectrum_frame(
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
            yield hooks.draw_envelope_frame(
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
    hooks: FixedHooks,
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
    filt = hooks._spectrum_spatial_filter(spatial_filter)
    for i in range(0, n_frames, step):
        field = mapping.apply(sequence[i])
        columns = hooks.field_to_columns(field, width)
        columns = hooks.apply_spectrum_spatial(columns, sigma=spatial_sigma, kind=filt)
        collected.extend(columns)
    return hooks.bin_peak(collected)


def iter_field_frames(
    hooks: FixedHooks,
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
    pad = hooks.glow_overscan(glow)
    draw_w = preset.canvas.width + 2 * pad
    draw_h = height + 2 * pad
    alpha = hooks.ema_alpha(fps, tau_seconds)
    filt = hooks._spectrum_spatial_filter(spatial_filter)
    previous: list[float] | None = None
    resolved = plan or hooks.resolve_render_plan(
        preset,
        layout="field_center_out",
        field_geometry="ribbon",
        ribbon_supersample=supersample,
    )
    # Bars: no decorative center line until that styling pass.
    center = bool(preset.waveform.center_line) and resolved.geometry not in hooks.BAR_GEOMETRIES
    count = min(n_frames, len(sequence))
    for i in range(count):
        t0 = hooks.time.perf_counter()
        field = mapping.apply(sequence[i])
        raw = hooks.field_to_columns(field, draw_w)
        raw = hooks.apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        if peak is not None and peak > 0.0:
            raw = hooks.normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = hooks.blend_columns(previous, raw, alpha)
        previous = blended
        t1 = hooks.time.perf_counter()
        frame = hooks.raster_field_columns(
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
        t2 = hooks.time.perf_counter()
        if phases is not None:
            phases.add("visual_field", t1 - t0)
            phases.add("raster", t2 - t1)
        yield frame


def _field_frame_ranges(hooks: FixedHooks, n_frames: int, workers: int) -> list[tuple[int, int]]:
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


def encode_field_chunk(hooks: FixedHooks, task: FieldChunkTask) -> Path | None:
    """Raster and encode one precomputed column range. Spawn-pool safe."""
    columns = hooks.np.load(task.columns_path, mmap_mode="r")
    slc = columns[task.first_frame : task.first_frame + task.n_frames]
    pad = task.overscan
    draw_w = task.width + 2 * pad
    draw_h = task.height + 2 * pad

    plan = hooks.RenderPlan(
        path="mask_fast" if task.plan_path == "mask_fast" else "rgba_2d",
        pix_fmt="gray" if task.pix_fmt == "gray" else "rgba",
        bytes_per_pixel=1 if task.pix_fmt == "gray" else 4,
        supersample=task.supersample,
        aa_mode="coverage_taps" if task.aa_taps > 1 and task.supersample == 1 else "physical_ss",
        aa_taps=task.aa_taps,
        colorize=task.pix_fmt == "gray",
        geometry=task.geometry,
    )
    bars = hooks.BarStyle(
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
            yield hooks.raster_field_columns(
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

    png_dir = hooks.Path(task.png_dir) if task.png_dir is not None else None
    prores_path = hooks.Path(task.prores_path) if task.prores_path is not None else None
    hooks.encode_rgba_stream(
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
    hooks: FixedHooks,
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
    alpha = hooks.ema_alpha(fps, tau_seconds)
    filt = hooks._spectrum_spatial_filter(spatial_filter)
    previous: list[float] | None = None
    rows: list[list[float]] = []
    count = min(n_frames, len(sequence))
    for i in range(count):
        t0 = hooks.time.perf_counter()
        field = mapping.apply(sequence[i])
        raw = hooks.field_to_columns(field, draw_w)
        raw = hooks.apply_spectrum_spatial(raw, sigma=spatial_sigma, kind=filt)
        if peak is not None and peak > 0.0:
            raw = hooks.normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = hooks.blend_columns(previous, raw, alpha)
        previous = blended
        if phases is not None:
            phases.add("visual_field", hooks.time.perf_counter() - t0)
        rows.append(blended)
    return rows


def iter_temporal_frames(
    hooks: FixedHooks,
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
    pad = hooks.glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    alpha = hooks.ema_alpha(fps, tau_seconds)
    previous: list[float] | None = None
    for i in range(n_frames):
        time_seconds = origin_seconds + (i / fps if fps > 0 else 0.0)
        raw = hooks.temporal_envelope_columns(
            samples,
            rate,
            time_seconds=time_seconds,
            width=draw_w,
            peak_mix=peak_mix,
        )
        if peak is not None and peak > 0.0:
            raw = hooks.normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = hooks.blend_columns(previous, raw, alpha)
        previous = blended
        yield hooks.draw_spectrum_frame(
            blended,
            width=draw_w,
            height=draw_h,
            color=preset.waveform.color,
            amplitude=preset.waveform.amplitude,
            center_line=center,
            content_height=height,
            supersample=hooks.SCROLL_SUPERSAMPLE,
            glow_sigma=glow,
        )


def resolve_fixed_options(
    hooks: FixedHooks, preset: VisualPreset, options: RenderOptions
) -> FixedAxisAppearance:
    """Resolve the unchanged recipe before destination identity and reuse."""
    return hooks.resolve_fixed_axis_appearance(
        preset,
        spectrum_contour=options.spectrum_contour,
        spectrum_spatial_scale=options.spectrum_spatial_scale,
        spectrum_spatial_filter=options.spectrum_spatial_filter,
        spectrum_n_bands=options.spectrum_n_bands,
        spectrum_tilt_db_per_octave=options.spectrum_tilt_db_per_octave,
        spectrum_compress=options.spectrum_compress,
        spectrum_recenter=options.spectrum_recenter,
        spectrum_edge_taper=options.spectrum_edge_taper,
        visual_geometry=options.visual_geometry,
        spectrum_layout=options.spectrum_layout,
        spectrum_slot_sigma=options.spectrum_slot_sigma,
        ribbon_supersample=options.ribbon_supersample,
        render_path=options.render_path,
        render_aa=options.render_aa,
        field_geometry=options.field_geometry,
        bar_width=options.bar_width,
        bar_gap=options.bar_gap,
        bar_count=options.bar_count,
        bar_fill=options.bar_fill,
        bar_align=options.bar_align,
        bar_alternate=options.bar_alternate,
        bar_color_b=options.bar_color_b,
        bar_center_line_width=options.bar_center_line_width,
    )


def run_fixed_pipeline(
    hooks: FixedHooks,
    *,
    job: PlannedJob,
    media: SourceMedia,
    preset: VisualPreset,
    performance: PerformanceProfile,
    appearance: FixedAxisAppearance,
    spectrum_contour: bool,
    ribbon_ss: int,
    source_sha: str,
    clip_start: float,
    clip_duration: float,
    expected_frames: int,
    work: Path,
    producing_mov: bool,
    producing_png: bool,
    glow: float,
    threads: int,
    note: Callable[[str], None],
    lifecycle: FixedPublication,
    analysis: dict[str, Any],
    normalization: dict[str, Any],
    clock: PhaseTimes,
) -> None:
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
    hooks.reset_workdir(work)
    decoded = work / "source.wav"
    origin_seconds = 0.0
    if geometry != "spectrum":
        half = hooks.TEMPORAL_WINDOW_SECONDS / 2.0
        pad_start = max(0.0, clip_start - half)
        pad_end = min(media.duration_seconds, clip_start + clip_duration + half)
        hooks.decode_mono_wav(
            job.path,
            decoded,
            start=pad_start if pad_start > 0 else None,
            duration=max(pad_end - pad_start, clip_duration),
        )
        origin_seconds = clip_start - pad_start
    peak_mix = hooks.TEMPORAL_PEAK_MIX if geometry == "temporal_rms_peak" else 0.0
    peak = None
    field_chunk_movs: list[Path] | None = None
    field_encoded = False
    spectrum_encode_workers = 1
    field_plan: RenderPlan | None = None
    bars: BarStyle | None = None
    if geometry != "spectrum":
        samples, rate = hooks.load_mono_f32(decoded)
        if norm_mode != "none":
            note("temporal peak scan")
            peak = hooks.temporal_envelope_peak(
                samples,
                rate,
                n_frames=expected_frames,
                fps=job.fps,
                origin_seconds=origin_seconds,
                width=preset.canvas.width,
                peak_mix=peak_mix,
            )
        frames = hooks.iter_temporal_frames(
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
        analysis.update(
            {
                "chunk_count": 1,
                "preroll_seconds": hooks.TEMPORAL_WINDOW_SECONDS / 2.0,
                "postroll_seconds": hooks.TEMPORAL_WINDOW_SECONDS / 2.0,
                "encode_workers": 1,
                "visual_geometry": geometry,
                "temporal_window_seconds": hooks.TEMPORAL_WINDOW_SECONDS,
                "temporal_bins": hooks.TEMPORAL_BINS,
                "temporal_peak_mix": peak_mix,
                "spectrum_raster": "contour",
            }
        )
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
            mapping = hooks.CenterOutMapping(n_slots=hooks.CENTER_OUT_SLOTS, n_bands=field_bands)
            assert bars is not None and field_plan is not None
            cache_payload = hooks.analysis_cache_payload(
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
            cache_digest = hooks.analysis_cache_digest(cache_payload)
            cached = hooks.load_analysis_cache(cache_digest)
            if cached is not None:
                sequence, span = cached
                clock.extras["analysis_cache"] = "hit"
                note("spectrum analysis cache hit")
            else:
                clock.extras["analysis_cache"] = "miss"
                with clock.span("decode"):
                    hooks.decode_mono_wav(
                        job.path,
                        decoded,
                        start=clip_start if clip_start > 0 else None,
                        duration=clip_duration if clip_duration > 0 else None,
                    )
                with clock.span("pcm_load"):
                    pcm, pcm_rate = hooks.load_mono_pcm(decoded)
                with clock.span("frequency_span"):
                    span = hooks.resolve_frequency_span_from_pcm(pcm, pcm_rate, preset.signal)
                note("spectrum analysis sequence")
                with clock.span("spectral_analysis"):
                    sequence = hooks.build_analysis_sequence(
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
                hooks.store_analysis_cache(cache_digest, sequence, span)
            if norm_mode != "none":
                note("spectrum peak scan")
                with clock.span("peak_scan"):
                    peak = hooks._visual_field_peak(
                        sequence,
                        width=preset.canvas.width,
                        spatial_sigma=spatial_sigma,
                        spatial_filter=spatial_filter,
                        mapping=mapping,
                    )
            requested_workers = hooks._job_workers(performance)
            use_pool = requested_workers > 1 and expected_frames >= hooks._FIELD_POOL_MIN_FRAMES
            if use_pool:
                pad = hooks.glow_overscan(glow)
                draw_w = preset.canvas.width + 2 * pad
                with clock.span("visual_field"):
                    column_rows = hooks._precompute_field_columns(
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
                hooks.np.save(columns_path, hooks.np.asarray(column_rows, dtype=hooks.np.float64))
                ranges = hooks._field_frame_ranges(len(column_rows), requested_workers)
                spectrum_encode_workers = len(ranges)
                worker_threads = hooks._encode_worker_threads(threads, spectrum_encode_workers)
                clock.extras["ffmpeg_threads_resolved_argument"] = worker_threads
                png_abs = str((work / "png").resolve()) if producing_png else None
                if producing_png:
                    (work / "png").mkdir(parents=True, exist_ok=True)
                tasks = [
                    hooks.FieldChunkTask(
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
                            and (field_plan.geometry not in hooks.BAR_GEOMETRIES)
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
                    ctx = hooks.multiprocessing.get_context("spawn")
                    with hooks.ProcessPoolExecutor(
                        max_workers=spectrum_encode_workers, mp_context=ctx
                    ) as pool:
                        parts = list(pool.map(hooks.encode_field_chunk, tasks))
                field_chunk_movs = [path for path in parts if path is not None]
                field_encoded = True
                frames = iter(())
            else:
                frames = hooks.iter_field_frames(
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
                hooks.decode_mono_wav(
                    job.path,
                    decoded,
                    start=clip_start if clip_start > 0 else None,
                    duration=clip_duration if clip_duration > 0 else None,
                )
            with clock.span("pcm_load"):
                pcm, pcm_rate = hooks.load_mono_pcm(decoded)
            with clock.span("frequency_span"):
                span = hooks.resolve_frequency_span_from_pcm(pcm, pcm_rate, preset.signal)
            if norm_mode != "none":
                note("spectrum peak scan")
                peak = hooks.spectrum_peak(
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
            frames = hooks.iter_spectrum_frames(
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
        overscan = hooks.glow_overscan(glow)
        clock.extras["render_path"] = field_plan.path
        clock.extras["bytes_per_frame"] = field_plan.bytes_per_frame(
            preset.canvas.width, preset.canvas.height, overscan
        )
        clock.extras["fingerprint"] = hooks.fingerprint_from_plan(
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
                hooks.concat_videos(
                    field_chunk_movs or [],
                    mov_work,
                    list_path=work / "field.concat.txt",
                )
    else:
        note(f"{encode_label} encode")
        encode_ss = (
            field_plan.supersample
            if field_plan is not None
            else (ribbon_ss if geometry == "spectrum" else hooks.SCROLL_SUPERSAMPLE)
        )
        hooks.encode_rgba_stream(
            hooks._tick_frames(
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
            overscan=hooks.glow_overscan(glow),
            supersample=encode_ss,
            phases=clock,
            pix_fmt=field_plan.pix_fmt if field_plan is not None else "rgba",
            color=(
                preset.waveform.color if field_plan is not None and field_plan.colorize else None
            ),
            n_frames=expected_frames,
        )
    if mov_work is not None:
        lifecycle.publish_mov(mov_work, failure_message="spectrum output failed validation")
    if png_work is not None:
        lifecycle.publish_png(png_work)
    if geometry == "spectrum":
        analysis.update(
            {
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
                "visual_slots": hooks.CENTER_OUT_SLOTS if layout == "field_center_out" else None,
                "ribbon_supersample": ribbon_ss,
                "render_path": field_plan.path if field_plan is not None else "rgba_2d",
                "render_pix_fmt": field_plan.pix_fmt if field_plan is not None else "rgba",
                "render_aa_mode": (field_plan.aa_mode if field_plan is not None else "physical_ss"),
            }
        )
    normalization.update({"mode": norm_mode, "soft_clip": soft, "peak": peak})
