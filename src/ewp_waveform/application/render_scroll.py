"""Time-scroll envelope preparation, checkpoint coordination and chunk encoding.

The dispatcher owns lifecycle/publication. Hooks are a typed view of its live
module, not a callback snapshot or a renderer registry. Worker tasks carry only
the selected-base pickleable payload; compatibility worker forwards in render
remain the spawn targets.
"""

from __future__ import annotations

import math
import multiprocessing
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ewp_waveform.application.checkpoint import Checkpoint, ChunkRecord
from ewp_waveform.application.chunks import LogicalChunk, ProcessingWindow
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.encode import EncodeError


@dataclass(frozen=True)
class EnvelopeSettings:
    oversample: int
    aa_kind: str
    aa_support: float
    lpf_kind: str
    lpf_cutoff: float
    smoothing_sigma: float
    scale: str
    norm_mode: str
    soft_clip: bool
    preroll: float
    postroll: float


@dataclass(frozen=True)
class PreparedChunk:
    window: ProcessingWindow
    bins: list[float]
    origin: float


@dataclass(frozen=True)
class ChunkEncodeTask:
    """Pickleable payload for one independent scroll chunk (process-pool target)."""

    chunk_index: int
    n_windows: int
    first_frame: int
    n_frames: int
    start_seconds: float
    end_seconds: float
    bins: list[float]
    origin: float
    clip_duration: float
    preset: VisualPreset
    fps: float
    glow: float
    png_dir: str | None
    prores_path: str | None
    ffmpeg_threads: int
    overscan: int
    supersample: int
    shutter_px: float
    shutter_mix: float


# Constructor attributes in the protocol must not shadow annotation types.
type _Checkpoint = Checkpoint
type _ChunkRecord = ChunkRecord
type _EnvelopeSettings = EnvelopeSettings
type _PreparedChunk = PreparedChunk
type _ChunkEncodeTask = ChunkEncodeTask


class ScrollHooks(Protocol):
    """Existing dispatcher lookups used by scroll; never passed to a worker."""

    CHECKPOINT_SCHEMA_VERSION: int
    CLASSIC_SCROLL_ALTERNATE_OPACITY: float
    SCROLL_SUPERSAMPLE: int
    VISUAL_CONTRACT_VERSION: int
    Checkpoint: type[_Checkpoint]
    ChunkRecord: type[_ChunkRecord]
    EnvelopeSettings: type[_EnvelopeSettings]
    PreparedChunk: type[_PreparedChunk]
    ChunkEncodeTask: type[_ChunkEncodeTask]
    ProcessPoolExecutor: type[ProcessPoolExecutor]

    def as_completed(
        self, fs: Iterable[Future[_ChunkRecord]], timeout: float | None = None
    ) -> Iterator[Future[_ChunkRecord]]: ...

    def _chunk_seconds(self, performance: PerformanceProfile) -> float: ...

    def _chunk_task(
        self,
        window: ProcessingWindow,
        prepared: _PreparedChunk,
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
    ) -> _ChunkEncodeTask: ...

    def _encode_worker_threads(self, configured: int, workers: int) -> int: ...

    def _envelope_settings(
        self, preset: VisualPreset, fps: float, glow: float
    ) -> _EnvelopeSettings: ...

    def _filter_wav(
        self,
        decoded: Path,
        settings: _EnvelopeSettings,
        sample_rate: int,
        width: int,
        window_seconds: float,
    ) -> tuple[list[float], float]: ...

    def _job_workers(self, performance: PerformanceProfile) -> int: ...

    def _prepare_chunk_envelopes(
        self,
        source: Path,
        windows: Sequence[ProcessingWindow],
        settings: _EnvelopeSettings,
        *,
        work: Path,
        clip_start: float,
        width: int,
        window_seconds: float,
    ) -> list[_PreparedChunk]: ...

    def _run_scroll_encodes(
        self,
        *,
        windows: Sequence[ProcessingWindow],
        prepared_by_index: dict[int, _PreparedChunk],
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
        checkpoint: _Checkpoint,
        cp_file: Path,
        note: Callable[[str], None],
    ) -> tuple[list[int], int]: ...

    def _stderr_note(self, message: str) -> None: ...

    def _tick_frames(
        self, frames: Iterator[bytes], *, n_frames: int, note: Callable[[str], None], label: str
    ) -> Iterator[bytes]: ...

    def _validate_mov(
        self, path: Path, *, width: int, height: int, expected_frames: int, fps: float
    ) -> dict[str, Any]: ...

    def bin_origin(self, decode_start: float, sample_rate: int, hop: float) -> float: ...

    def bin_peak(self, bins: Sequence[float], percentile: float = 95.0) -> float: ...

    def checkpoint_path(self, work: Path) -> Path: ...

    def concat_videos(
        self, parts: Sequence[Path], dest: Path, *, list_path: Path | None = None
    ) -> None: ...

    def decode_mono_wav(
        self,
        source: Path,
        dest: Path,
        sample_rate: int = 48000,
        start: float | None = None,
        duration: float | None = None,
    ) -> None: ...

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
        scroll_phase: float = 0.0,
        vertical_margin: int = 1,
        content_height: int | None = None,
        supersample: int = 1,
        glow_sigma: float = 0.0,
        envelope_oversample: int = 1,
        classic_alternate_opacity: float = 0.0,
    ) -> bytes: ...

    def encode_rgba_stream(
        self,
        frames: Iterable[bytes],
        *,
        width: int,
        height: int,
        fps: float,
        glow: float,
        png_dir: Path | None,
        prores_path: Path | None,
        ffmpeg_threads: int = 0,
        overscan: int = 0,
        supersample: int = 1,
        shutter_px: float = 0.0,
        shutter_mix: float = 0.25,
        png_start_number: int = 1,
        phases: Any | None = None,
        pix_fmt: str = "rgba",
        color: str | None = None,
        n_frames: int | None = None,
    ) -> None: ...

    def encode_scroll_chunk(
        self, task: _ChunkEncodeTask, note: Callable[[str], None] | None = None
    ) -> _ChunkRecord: ...

    def envelope_aa_from_signal(self, signal: dict[str, object]) -> tuple[str, float]: ...

    def envelope_context_bins(
        self,
        *,
        oversample: int,
        aa_kind: str,
        aa_support: float,
        lpf_kind: str,
        lpf_cutoff: float,
        smoothing_sigma: float = 0.0,
    ) -> int: ...

    def envelope_oversample_from_signal(self, signal: dict[str, object]) -> int: ...

    def envelope_preroll_seconds(
        self,
        *,
        window_seconds: float,
        width: int,
        oversample: int,
        context_bins: int,
        extra_px: int = 0,
    ) -> tuple[float, float]: ...

    def glow_overscan(self, sigma: float) -> int: ...

    def hop_samples(
        self, sample_rate: int, width: int, window_seconds: float, oversample: int = 1
    ) -> float: ...

    def identity_matches(
        self,
        checkpoint: _Checkpoint,
        *,
        source_sha256: str,
        render_signature: str,
        visual_contract_version: int | str,
        renderer: str,
        fps: float,
        clip_start: float,
        clip_duration: float,
        chunk_seconds: float,
        expected_frames: int,
        want_mov: bool,
        want_png: bool,
    ) -> bool: ...

    def iter_scroll_frames(
        self,
        bins: list[float],
        *,
        duration: float,
        preset: VisualPreset,
        fps: float,
        glow: float = 0.0,
        first_frame: int = 0,
        n_frames: int | None = None,
        origin: float = 0.0,
    ) -> Iterator[bytes]: ...

    def load_checkpoint(self, path: Path) -> _Checkpoint | None: ...

    def motion_cutoff_cyc_px(
        self,
        *,
        width: int,
        window_seconds: float,
        fps: float,
        margin: float = 0.85,
        explicit: float = 0.0,
    ) -> float: ...

    def motion_lpf_from_signal(self, signal: dict[str, object]) -> tuple[str, float, float]: ...

    def normalize_bins(
        self,
        bins: Sequence[float],
        *,
        percentile: float = 95.0,
        soft_clip: bool = False,
        knee: float = 0.88,
        peak: float | None = None,
    ) -> list[float]: ...

    def plan_chunks(
        self, duration: float, fps: float, chunk_seconds: float
    ) -> list[LogicalChunk]: ...

    def png_chunk_complete(self, png_dir: Path, *, first_frame: int, n_frames: int) -> bool: ...

    def probe_media(self, path: Path) -> SourceMedia: ...

    def process_envelope_bins(
        self,
        bins: Sequence[float],
        *,
        scale: str,
        smoothing_sigma: float = 0.0,
        oversample: int = 1,
        aa_kind: str = "none",
        aa_support: float = 1.0,
        lpf_kind: str = "none",
        lpf_cutoff: float = 0.0,
    ) -> list[float]: ...

    def processing_window(
        self, chunk: LogicalChunk, *, source_duration: float, preroll: float, postroll: float
    ) -> ProcessingWindow: ...

    def published_bin_slice(
        self,
        bins: Sequence[float],
        *,
        start_seconds: float,
        end_seconds: float,
        origin_seconds: float,
        bins_per_second: float,
    ) -> list[float]: ...

    def reset_workdir(self, work: Path) -> None: ...

    def reusable_chunk_indices(
        self,
        work: Path,
        checkpoint: _Checkpoint,
        windows: Sequence[ProcessingWindow],
        *,
        want_mov: bool,
        want_png: bool,
    ) -> list[int]: ...

    def rms_bins_from_wav(self, path: Path, hop: float) -> list[float]: ...

    def sha256_file(self, path: Path) -> str: ...

    def viewport_left_px(
        self, frame_index: int, fps: float, window_seconds: float, width: int
    ) -> float: ...

    def window_from_origin(
        self, bins: Sequence[float], *, global_end_exclusive: int, width: int, origin: float
    ) -> list[float]: ...

    def write_checkpoint(self, path: Path, checkpoint: _Checkpoint) -> None: ...


def iter_scroll_frames(
    hooks: ScrollHooks,
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
    width = preset.canvas.width
    height = preset.canvas.height
    total = n_frames if n_frames is not None else max(1, round(duration * fps))
    stroke = preset.waveform.stroke_width or 6.0
    center = bool(preset.waveform.center_line)
    window_seconds = preset.waveform.window_seconds
    pad = hooks.glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    ss = hooks.SCROLL_SUPERSAMPLE
    oversample = hooks.envelope_oversample_from_signal(preset.signal)
    raw_classic_opacity = preset.signal.get(
        "classic_alternate_opacity", hooks.CLASSIC_SCROLL_ALTERNATE_OPACITY
    )
    classic_opacity = (
        min(max(float(raw_classic_opacity), 0.0), 1.0)
        if isinstance(raw_classic_opacity, int | float)
        and not isinstance(raw_classic_opacity, bool)
        else hooks.CLASSIC_SCROLL_ALTERNATE_OPACITY
    )
    env_w = draw_w * oversample
    for i in range(first_frame, first_frame + total):
        vis_start = hooks.viewport_left_px(i, fps, window_seconds, width)
        draw_start = vis_start - pad
        draw_start_bins = draw_start * oversample
        raw = hooks.window_from_origin(
            bins,
            global_end_exclusive=math.floor(draw_start_bins) + env_w + 1,
            width=env_w + 1,
            origin=origin,
        )
        yield hooks.draw_envelope_frame(
            raw,
            width=draw_w,
            height=draw_h,
            color=preset.waveform.color,
            amplitude=preset.waveform.amplitude,
            stroke_width=stroke,
            style=preset.waveform.style,
            center_line=center,
            scroll_phase=draw_start,
            content_height=height,
            supersample=ss,
            glow_sigma=glow,
            envelope_oversample=oversample,
            classic_alternate_opacity=classic_opacity,
        )


def _envelope_settings(
    hooks: ScrollHooks, preset: VisualPreset, fps: float, glow: float
) -> EnvelopeSettings:
    oversample = hooks.envelope_oversample_from_signal(preset.signal)
    aa_kind, aa_support = hooks.envelope_aa_from_signal(preset.signal)
    lpf_kind, lpf_explicit, lpf_margin = hooks.motion_lpf_from_signal(preset.signal)
    lpf_cutoff = hooks.motion_cutoff_cyc_px(
        width=preset.canvas.width,
        window_seconds=preset.waveform.window_seconds,
        fps=fps,
        margin=lpf_margin,
        explicit=lpf_explicit,
    )
    raw_smooth = preset.signal.get("smoothing", 0.0)
    smoothing = 0.0
    if isinstance(raw_smooth, int | float) and not isinstance(raw_smooth, bool):
        smoothing = float(raw_smooth)
    smoothing_sigma = 0.0
    if smoothing > 0.0:
        smoothing_sigma = smoothing * (preset.canvas.width / preset.waveform.window_seconds)
    scale = str(preset.signal.get("scale") or "sqrt")
    norm = preset.signal.get("normalization")
    norm_mode = "auto"
    soft = True
    if isinstance(norm, dict):
        norm_mode = str(norm.get("mode") or "auto")
        soft = bool(norm.get("soft_clip", True))
    context = hooks.envelope_context_bins(
        oversample=oversample,
        aa_kind=aa_kind,
        aa_support=aa_support,
        lpf_kind=lpf_kind,
        lpf_cutoff=lpf_cutoff,
        smoothing_sigma=smoothing_sigma,
    )
    preroll, postroll = hooks.envelope_preroll_seconds(
        window_seconds=preset.waveform.window_seconds,
        width=preset.canvas.width,
        oversample=oversample,
        context_bins=context,
        extra_px=hooks.glow_overscan(glow) + 1,
    )
    return hooks.EnvelopeSettings(
        oversample=oversample,
        aa_kind=aa_kind,
        aa_support=aa_support,
        lpf_kind=lpf_kind,
        lpf_cutoff=lpf_cutoff,
        smoothing_sigma=smoothing_sigma,
        scale=scale,
        norm_mode=norm_mode,
        soft_clip=soft,
        preroll=preroll,
        postroll=postroll,
    )


def _chunk_seconds(hooks: ScrollHooks, performance: PerformanceProfile) -> float:
    raw = performance.processing.get("chunk_seconds", 60)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return 60.0
    return float(raw)


def _filter_wav(
    hooks: ScrollHooks,
    decoded: Path,
    settings: EnvelopeSettings,
    sample_rate: int,
    width: int,
    window_seconds: float,
) -> tuple[list[float], float]:
    hop = hooks.hop_samples(sample_rate, width, window_seconds, oversample=settings.oversample)
    bins = hooks.rms_bins_from_wav(decoded, hop)
    filtered = hooks.process_envelope_bins(
        bins,
        scale=settings.scale,
        smoothing_sigma=settings.smoothing_sigma,
        oversample=settings.oversample,
        aa_kind=settings.aa_kind,
        aa_support=settings.aa_support,
        lpf_kind=settings.lpf_kind,
        lpf_cutoff=settings.lpf_cutoff,
    )
    return filtered, hop


def encode_scroll_chunk(
    hooks: ScrollHooks, task: ChunkEncodeTask, note: Callable[[str], None] | None = None
) -> ChunkRecord:
    """Encode one logical chunk. Safe as a spawn process-pool target."""
    progress = note if note is not None else hooks._stderr_note
    label = f"chunk {task.chunk_index + 1}/{task.n_windows}"
    progress(f"{label} encode {task.n_frames} frames")
    frames = hooks._tick_frames(
        hooks.iter_scroll_frames(
            task.bins,
            duration=task.clip_duration,
            preset=task.preset,
            fps=task.fps,
            glow=task.glow,
            first_frame=task.first_frame,
            n_frames=task.n_frames,
            origin=task.origin,
        ),
        n_frames=task.n_frames,
        note=progress,
        label=label,
    )
    png_dir = Path(task.png_dir) if task.png_dir is not None else None
    prores_path = Path(task.prores_path) if task.prores_path is not None else None
    hooks.encode_rgba_stream(
        frames,
        width=task.preset.canvas.width,
        height=task.preset.canvas.height,
        fps=task.fps,
        glow=task.glow,
        png_dir=png_dir,
        prores_path=prores_path,
        ffmpeg_threads=task.ffmpeg_threads,
        overscan=task.overscan,
        supersample=task.supersample,
        shutter_px=task.shutter_px,
        shutter_mix=task.shutter_mix,
        png_start_number=task.first_frame + 1,
    )
    if prores_path is not None:
        chunk_report = hooks._validate_mov(
            prores_path,
            width=task.preset.canvas.width,
            height=task.preset.canvas.height,
            expected_frames=task.n_frames,
            fps=task.fps,
        )
        if not chunk_report.get("passed"):
            raise EncodeError(f"chunk {task.chunk_index:04d} failed validation")
    if png_dir is not None and not hooks.png_chunk_complete(
        png_dir, first_frame=task.first_frame, n_frames=task.n_frames
    ):
        raise EncodeError(f"chunk {task.chunk_index:04d} png frames missing")
    return hooks.ChunkRecord(
        index=task.chunk_index,
        first_frame=task.first_frame,
        n_frames=task.n_frames,
        start_seconds=task.start_seconds,
        end_seconds=task.end_seconds,
        mov_name=prores_path.name if prores_path is not None else None,
        mov_sha256=hooks.sha256_file(prores_path) if prores_path is not None else None,
        png_count=task.n_frames if png_dir is not None else None,
    )


def _chunk_task(
    hooks: ScrollHooks,
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
    chunk = window.chunk
    chunk_mov = work / f"chunk-{chunk.index:04d}.mov" if producing_mov else None
    return hooks.ChunkEncodeTask(
        chunk_index=chunk.index,
        n_windows=n_windows,
        first_frame=chunk.first_frame,
        n_frames=chunk.n_frames,
        start_seconds=chunk.start_seconds,
        end_seconds=chunk.end_seconds,
        bins=prepared.bins,
        origin=prepared.origin,
        clip_duration=clip_duration,
        preset=preset,
        fps=fps,
        glow=glow,
        png_dir=str(png_work) if png_work is not None else None,
        prores_path=str(chunk_mov) if chunk_mov is not None else None,
        ffmpeg_threads=ffmpeg_threads,
        overscan=hooks.glow_overscan(glow),
        supersample=hooks.SCROLL_SUPERSAMPLE,
        shutter_px=shutter_px,
        shutter_mix=shutter_mix,
    )


def _run_scroll_encodes(
    hooks: ScrollHooks,
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
    """Encode remaining chunks; concat order is applied by the caller.

    ``jobs>1`` fans out independent chunks after the global peak is stored.
    ``fail_after_chunk`` stays sequential so injected resume tests remain exact.
    """
    reused: list[int] = []
    remaining: list[ProcessingWindow] = []
    for window in windows:
        if window.chunk.index in completed_ok:
            note(f"chunk {window.chunk.index + 1}/{len(windows)} reuse")
            reused.append(window.chunk.index)
        else:
            remaining.append(window)
    if not remaining:
        return reused, 0

    work_abs = work.resolve()
    png_abs = png_work.resolve() if png_work is not None else None
    if png_abs is not None:
        png_abs.mkdir(parents=True, exist_ok=True)

    use_pool = workers > 1 and fail_after_chunk is None and len(remaining) > 1
    encode_workers = min(workers, len(remaining)) if use_pool else 1
    worker_threads = hooks._encode_worker_threads(ffmpeg_threads, encode_workers)

    def task_for(window: ProcessingWindow) -> ChunkEncodeTask:
        return hooks._chunk_task(
            window,
            prepared_by_index[window.chunk.index],
            n_windows=len(windows),
            preset=preset,
            clip_duration=clip_duration,
            fps=fps,
            glow=glow,
            png_work=png_abs,
            work=work_abs,
            producing_mov=producing_mov,
            ffmpeg_threads=worker_threads,
            shutter_px=shutter_px,
            shutter_mix=shutter_mix,
        )

    def commit(record: ChunkRecord) -> None:
        checkpoint.completed_chunks.append(record)
        hooks.write_checkpoint(cp_file, checkpoint)

    if not use_pool:
        for window in remaining:
            commit(hooks.encode_scroll_chunk(task_for(window), note=note))
            if fail_after_chunk is not None and window.chunk.index >= fail_after_chunk:
                raise RuntimeError("injected checkpoint stop")
        return reused, encode_workers

    note(f"encode {len(remaining)} remaining chunk(s) with {encode_workers} process(es)")
    ctx = multiprocessing.get_context("spawn")
    first_error: BaseException | None = None
    with hooks.ProcessPoolExecutor(max_workers=encode_workers, mp_context=ctx) as pool:
        pending = [pool.submit(hooks.encode_scroll_chunk, task_for(window)) for window in remaining]
        try:
            for future in hooks.as_completed(pending):
                try:
                    record = future.result()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    continue
                commit(record)
        except KeyboardInterrupt:
            for future in pending:
                future.cancel()
            raise
    if first_error is not None:
        raise first_error
    return reused, encode_workers


def _prepare_chunk_envelopes(
    hooks: ScrollHooks,
    source: Path,
    windows: Sequence[ProcessingWindow],
    settings: EnvelopeSettings,
    *,
    work: Path,
    clip_start: float,
    width: int,
    window_seconds: float,
) -> list[PreparedChunk]:
    prepared: list[PreparedChunk] = []
    for window in windows:
        decoded = work / f"chunk-{window.chunk.index:04d}.wav"
        abs_start = clip_start + window.decode_start
        hooks.decode_mono_wav(
            source,
            decoded,
            start=abs_start if abs_start > 0 else None,
            duration=window.decode_duration if window.decode_duration > 0 else None,
        )
        decoded_media = hooks.probe_media(decoded)
        bins, hop = hooks._filter_wav(
            decoded,
            settings,
            decoded_media.sample_rate,
            width,
            window_seconds,
        )
        origin = hooks.bin_origin(window.decode_start, decoded_media.sample_rate, hop)
        prepared.append(hooks.PreparedChunk(window=window, bins=bins, origin=origin))
    return prepared


def run_scroll_pipeline(
    hooks: ScrollHooks,
    *,
    job: PlannedJob,
    preset: VisualPreset,
    performance: PerformanceProfile,
    source_sha: str,
    sig: str,
    clip_start: float,
    clip_duration: float,
    expected_frames: int,
    work: Path,
    producing_mov: bool,
    producing_png: bool,
    glow: float,
    threads: int,
    fail_after_chunk: int | None,
    note: Callable[[str], None],
    analysis: dict[str, Any],
    normalization: dict[str, Any],
    warnings: list[Diagnostic],
    resume_history: list[dict[str, Any]],
    clock: PhaseTimes,
) -> tuple[Path | None, Path | None]:
    """Build staged outputs; preserve partial reports if any existing step fails.

    Reports are updated at their original assignment boundaries. Publication,
    validation of final assets and job failure/cleanup remain lifecycle work.
    """
    tmp_mov = None
    note(f"scroll decode {clip_duration:.1f}s -> {expected_frames} frames @ {job.fps:g} fps")
    settings = hooks._envelope_settings(preset, job.fps, glow)
    chunk_seconds = hooks._chunk_seconds(performance)
    chunks = hooks.plan_chunks(clip_duration, job.fps, chunk_seconds)
    windows = [
        hooks.processing_window(
            chunk,
            source_duration=clip_duration,
            preroll=settings.preroll,
            postroll=settings.postroll,
        )
        for chunk in chunks
    ]
    analysis.update(
        {
            "chunk_count": len(chunks),
            "preroll_seconds": settings.preroll,
            "postroll_seconds": settings.postroll,
        }
    )
    cp_file = hooks.checkpoint_path(work)
    existing = hooks.load_checkpoint(cp_file)
    completed_ok: set[int] = set()
    peak = None
    if existing is not None and hooks.identity_matches(
        existing,
        source_sha256=source_sha,
        render_signature=sig,
        visual_contract_version=hooks.VISUAL_CONTRACT_VERSION,
        renderer="ffmpeg",
        fps=job.fps,
        clip_start=clip_start,
        clip_duration=clip_duration,
        chunk_seconds=chunk_seconds,
        expected_frames=expected_frames,
        want_mov=producing_mov,
        want_png=producing_png,
    ):
        completed_ok = set(
            hooks.reusable_chunk_indices(
                work, existing, windows, want_mov=producing_mov, want_png=producing_png
            )
        )
        peak = existing.peak
        checkpoint = existing
        checkpoint.completed_chunks = [
            record for record in existing.completed_chunks if record.index in completed_ok
        ]
    else:
        hooks.reset_workdir(work)
        checkpoint = hooks.Checkpoint(
            schema_version=hooks.CHECKPOINT_SCHEMA_VERSION,
            source_sha256=source_sha,
            render_signature=sig,
            visual_contract_version=hooks.VISUAL_CONTRACT_VERSION,
            renderer="ffmpeg",
            fps=job.fps,
            clip_start=clip_start,
            clip_duration=clip_duration,
            chunk_seconds=chunk_seconds,
            expected_frames=expected_frames,
            want_mov=producing_mov,
            want_png=producing_png,
            peak=None,
            preroll_seconds=settings.preroll,
            postroll_seconds=settings.postroll,
            completed_chunks=[],
        )
    work.mkdir(parents=True, exist_ok=True)
    incomplete = [window for window in windows if window.chunk.index not in completed_ok]
    prepared_by_index: dict[int, PreparedChunk] = {}
    if incomplete:
        analyze_windows = windows if peak is None else incomplete
        prepared = hooks._prepare_chunk_envelopes(
            job.path,
            analyze_windows,
            settings,
            work=work,
            clip_start=clip_start,
            width=preset.canvas.width,
            window_seconds=preset.waveform.window_seconds,
        )
        if settings.norm_mode != "none" and peak is None:
            collected: list[float] = []
            bps = float(preset.canvas.width * settings.oversample) / preset.waveform.window_seconds
            for item in prepared:
                collected.extend(
                    hooks.published_bin_slice(
                        item.bins,
                        start_seconds=item.window.chunk.start_seconds,
                        end_seconds=item.window.chunk.end_seconds,
                        origin_seconds=item.window.decode_start,
                        bins_per_second=bps,
                    )
                )
            peak = hooks.bin_peak(collected)
        if settings.norm_mode != "none":
            prepared = [
                hooks.PreparedChunk(
                    window=item.window,
                    bins=hooks.normalize_bins(item.bins, soft_clip=settings.soft_clip, peak=peak),
                    origin=item.origin,
                )
                for item in prepared
            ]
        prepared_by_index = {item.window.chunk.index: item for item in prepared}
        checkpoint.peak = peak
        hooks.write_checkpoint(cp_file, checkpoint)
    normalization.update(
        {"mode": settings.norm_mode, "soft_clip": settings.soft_clip, "peak": peak}
    )
    png_work = work / "png" if producing_png else None
    px_per_frame = preset.canvas.width / (preset.waveform.window_seconds * job.fps)
    raw_shutter = preset.signal.get("shutter_degrees", 0)
    shutter_deg = 0.0
    if isinstance(raw_shutter, int | float) and (not isinstance(raw_shutter, bool)):
        shutter_deg = max(0.0, float(raw_shutter))
    shutter_px = px_per_frame * shutter_deg / 360.0
    raw_mix = preset.signal.get("shutter_mix", 0.25)
    shutter_mix = 0.25
    if isinstance(raw_mix, int | float) and (not isinstance(raw_mix, bool)):
        shutter_mix = min(max(float(raw_mix), 0.0), 1.0)
    reused, encode_workers = hooks._run_scroll_encodes(
        windows=windows,
        prepared_by_index=prepared_by_index,
        completed_ok=completed_ok,
        preset=preset,
        clip_duration=clip_duration,
        fps=job.fps,
        glow=glow,
        png_work=png_work,
        work=work,
        producing_mov=producing_mov,
        ffmpeg_threads=threads,
        shutter_px=shutter_px,
        shutter_mix=shutter_mix,
        workers=hooks._job_workers(performance),
        fail_after_chunk=fail_after_chunk,
        checkpoint=checkpoint,
        cp_file=cp_file,
        note=note,
    )
    analysis["encode_workers"] = encode_workers
    clock.extras["ffmpeg_threads_resolved_argument"] = (
        hooks._encode_worker_threads(threads, encode_workers) if encode_workers else None
    )
    if reused:
        remaining = [
            window.chunk.start_seconds for window in windows if window.chunk.index not in reused
        ]
        boundary = min(remaining) if remaining else clip_duration
        warnings.append(
            Diagnostic(
                code=DiagnosticCode.W_JOB_RESUMED,
                severity=Severity.WARNING,
                message=(
                    f"Resumed at source timestamp {boundary:.3f}s (reused {len(reused)} chunk(s))."
                ),
                path=str(job.path),
            )
        )
        resume_history.append(
            {"resumed": True, "boundary_seconds": boundary, "reused_chunks": reused}
        )
    if producing_mov:
        segments = [work / f"chunk-{window.chunk.index:04d}.mov" for window in windows]
        note(f"concat {len(segments)} segment(s)")
        tmp_mov = work / "out.mov"
        hooks.concat_videos(segments, tmp_mov, list_path=work / "concat.txt")
    return (tmp_mov, png_work)
