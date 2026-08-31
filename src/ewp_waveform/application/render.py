"""Render orchestration: workdir, envelope scroll, experimental spectrum, publish."""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ewp_waveform import __version__
from ewp_waveform.analysis.envelope import (
    bin_peak,
    envelope_aa_from_signal,
    envelope_context_bins,
    envelope_oversample_from_signal,
    envelope_preroll_seconds,
    hop_samples,
    motion_cutoff_cyc_px,
    motion_lpf_from_signal,
    normalize_bins,
    process_envelope_bins,
    published_bin_slice,
    rms_bins_from_wav,
    viewport_left_px,
    window_from_origin,
)
from ewp_waveform.analysis.spectrum import (
    FrequencySpan,
    blend_columns,
    ema_alpha,
    resolve_frequency_span,
    spectrum_columns,
    spectrum_peak,
)
from ewp_waveform.application.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    Checkpoint,
    ChunkRecord,
    checkpoint_path,
    identity_matches,
    load_checkpoint,
    png_chunk_complete,
    reset_workdir,
    resolve_workdir,
    reusable_chunk_indices,
    workdir_key,
    write_checkpoint,
)
from ewp_waveform.application.chunks import (
    ProcessingWindow,
    bin_origin,
    plan_chunks,
    processing_window,
)
from ewp_waveform.application.results import elapsed_seconds
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.concat import concat_videos
from ewp_waveform.ffmpeg.decode import DecodeError, decode_mono_wav
from ewp_waveform.ffmpeg.draw import SCROLL_SUPERSAMPLE, draw_envelope_frame, glow_overscan
from ewp_waveform.ffmpeg.encode import (
    EncodeError,
    encode_rgba_stream,
    glow_sigma,
)
from ewp_waveform.ffmpeg.probe import ProbeError, probe_media, probe_video
from ewp_waveform.identity import (
    VISUAL_CONTRACT_VERSION,
    render_signature,
    sha256_file,
    short_signature,
)


def _glow_sigma(preset: VisualPreset) -> float:
    raw = preset.effects.get("glow")
    if not isinstance(raw, dict):
        return 0.0
    return glow_sigma(str(raw.get("level") or "none"), bool(raw.get("enabled", False)))


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def output_root(source: Path, configured: Path | None, directory_name: str) -> Path:
    if configured is not None:
        return configured
    parent = source.parent if source.is_file() else source
    return parent / directory_name


def next_version_path(path: Path) -> Path:
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    n = 2
    while True:
        candidate = parent / f"{stem}_v{n:03d}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def output_is_complete(path: Path) -> bool:
    """True when dest looks like a finished publish, not an empty leftover."""
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.glob("frame_*.png"))
    return False


def publish_path(
    dest: Path,
    *,
    force: bool,
) -> tuple[Path, bool]:
    """Return dest, skip. skip True means equivalent output already present."""
    if not output_is_complete(dest):
        return dest, False
    if force:
        return next_version_path(dest), False
    return dest, True


def planned_destinations(
    job: PlannedJob,
    preset: VisualPreset,
    *,
    source_sha256: str,
    output_dir: Path,
    formats: Sequence[str],
    clip_start: float = 0.0,
    clip_duration: float | None = None,
) -> tuple[str, Path | None, Path | None]:
    """Return render signature and canonical dest paths (mov, png dir)."""
    sig = render_signature(
        source_sha256=source_sha256,
        preset=preset,
        fps=job.fps,
        clip_start=clip_start,
        clip_duration=clip_duration,
    )
    short = short_signature(sig)
    project_dir = output_dir / job.project_id
    stem = f"{job.path.stem}_{preset.name}_{short}"
    want_png = "png" in formats
    want_mov = "prores4444" in formats or not formats
    mov = project_dir / f"{stem}.mov" if want_mov else None
    png = project_dir / f"{stem}_png" if want_png else None
    return sig, mov, png


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
    width = preset.canvas.width
    height = preset.canvas.height
    total = n_frames if n_frames is not None else max(1, round(duration * fps))
    stroke = preset.waveform.stroke_width or 6.0
    center = bool(preset.waveform.center_line)
    window_seconds = preset.waveform.window_seconds
    pad = glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    ss = SCROLL_SUPERSAMPLE
    oversample = envelope_oversample_from_signal(preset.signal)
    env_w = draw_w * oversample
    for i in range(first_frame, first_frame + total):
        vis_start = viewport_left_px(i, fps, window_seconds, width)
        draw_start = vis_start - pad
        draw_start_bins = draw_start * oversample
        raw = window_from_origin(
            bins,
            global_end_exclusive=math.floor(draw_start_bins) + env_w + 1,
            width=env_w + 1,
            origin=origin,
        )
        yield draw_envelope_frame(
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
) -> Iterator[bytes]:
    """Fixed-axis frames: X is log-Hz, motion is vertical only."""
    width = preset.canvas.width
    height = preset.canvas.height
    stroke = preset.waveform.stroke_width or 3.0
    center = bool(preset.waveform.center_line)
    pad = glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    alpha = ema_alpha(fps, tau_seconds)
    previous: list[float] | None = None
    spatial = 0.0
    if tau_seconds > 0.0:
        spatial = max(1.0, width / 200.0)
    for i in range(n_frames):
        raw = spectrum_columns(
            path,
            frame_index=i,
            fps=fps,
            width=draw_w,
            span=span,
            scale=scale,
            smoothing_sigma=spatial,
        )
        if peak is not None and peak > 0.0:
            raw = normalize_bins(raw, peak=peak, soft_clip=soft_clip)
        blended = blend_columns(previous, raw, alpha)
        previous = blended
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
            supersample=SCROLL_SUPERSAMPLE,
            glow_sigma=glow,
            envelope_oversample=1,
        )


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


def _chunk_seconds(performance: PerformanceProfile) -> float:
    raw = performance.processing.get("chunk_seconds", 60)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return 60.0
    return float(raw)


def _clip_bounds(
    media: SourceMedia, start: float | None, duration: float | None
) -> tuple[float, float]:
    clip_start = start if start is not None and start > 0 else 0.0
    remain = max(0.0, media.duration_seconds - clip_start)
    if duration is not None and duration > 0:
        return clip_start, min(duration, remain)
    return clip_start, remain


def _envelope_settings(preset: VisualPreset, fps: float, glow: float) -> EnvelopeSettings:
    oversample = envelope_oversample_from_signal(preset.signal)
    aa_kind, aa_support = envelope_aa_from_signal(preset.signal)
    lpf_kind, lpf_explicit, lpf_margin = motion_lpf_from_signal(preset.signal)
    lpf_cutoff = motion_cutoff_cyc_px(
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
    context = envelope_context_bins(
        oversample=oversample,
        aa_kind=aa_kind,
        aa_support=aa_support,
        lpf_kind=lpf_kind,
        lpf_cutoff=lpf_cutoff,
        smoothing_sigma=smoothing_sigma,
    )
    preroll, postroll = envelope_preroll_seconds(
        window_seconds=preset.waveform.window_seconds,
        width=preset.canvas.width,
        oversample=oversample,
        context_bins=context,
        extra_px=glow_overscan(glow) + 1,
    )
    return EnvelopeSettings(
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


def _filter_wav(
    decoded: Path,
    settings: EnvelopeSettings,
    sample_rate: int,
    width: int,
    window_seconds: float,
) -> tuple[list[float], float]:
    hop = hop_samples(sample_rate, width, window_seconds, oversample=settings.oversample)
    bins = rms_bins_from_wav(decoded, hop)
    filtered = process_envelope_bins(
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


def _png_frame_count(directory: Path) -> int:
    return len(list(directory.glob("frame_*.png")))


def _validate_mov(
    path: Path,
    *,
    width: int,
    height: int,
    expected_frames: int,
) -> dict[str, Any]:
    info = probe_video(path)
    frames_ok = True
    if info.nb_frames is not None:
        frames_ok = abs(info.nb_frames - expected_frames) <= 1
    passed = (
        path.is_file()
        and path.stat().st_size > 0
        and "prores" in info.codec_name
        and "yuva" in info.pix_fmt
        and info.width == width
        and info.height == height
        and frames_ok
    )
    return {
        "passed": passed,
        "codec": info.codec_name,
        "pix_fmt": info.pix_fmt,
        "width": info.width,
        "height": info.height,
        "frames": info.nb_frames,
        "duration_seconds": info.duration_seconds,
    }


def _validate_png(directory: Path, *, expected_frames: int) -> dict[str, Any]:
    count = _png_frame_count(directory)
    passed = directory.is_dir() and count == expected_frames
    return {"passed": passed, "frames": count, "format": "png"}


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
) -> dict[str, Any]:
    started = _utcnow()

    def note(message: str) -> None:
        if progress is not None:
            progress(message)

    note(f"hashing {job.path}")
    source_sha = sha256_file(job.path)
    after_hash = source_sha
    clip_start, clip_duration = _clip_bounds(media, start, duration)
    sig, mov_dest, png_dest = planned_destinations(
        job,
        preset,
        source_sha256=source_sha,
        output_dir=output_dir,
        formats=formats,
        clip_start=clip_start,
        clip_duration=duration if duration is not None and duration > 0 else None,
    )
    project_dir = output_dir / job.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    want_png = png_dest is not None
    want_mov = mov_dest is not None
    skip_mov = False
    skip_png = False
    if mov_dest is not None:
        mov_dest, skip_mov = publish_path(mov_dest, force=force)
    if png_dest is not None:
        png_dest, skip_png = publish_path(png_dest, force=force)

    expected_frames = max(1, round(clip_duration * job.fps))
    skip_outputs: list[dict[str, Any]] = []
    skip_validation: dict[str, Any] = {"passed": True}
    if want_mov and skip_mov:
        assert mov_dest is not None
        try:
            skip_validation = _validate_mov(
                mov_dest,
                width=preset.canvas.width,
                height=preset.canvas.height,
                expected_frames=expected_frames,
            )
        except (ProbeError, OSError):
            skip_validation = {"passed": False}
        if not skip_validation.get("passed"):
            skip_mov = False
        else:
            skip_outputs.append({"path": str(mov_dest), "format": "prores4444"})
    if want_png and skip_png:
        assert png_dest is not None
        png_report = _validate_png(png_dest, expected_frames=expected_frames)
        if not png_report.get("passed"):
            skip_png = False
        else:
            skip_outputs.append({"path": str(png_dest), "format": "png"})
            if not (want_mov and skip_mov):
                skip_validation = png_report

    if (not want_mov or skip_mov) and (not want_png or skip_png) and not force:
        note("skip: equivalent output already present")
        return _result_payload(
            job,
            media,
            preset,
            performance,
            source_sha,
            sig,
            started,
            status="SKIPPED",
            outputs=skip_outputs,
            warnings=[],
            validation=skip_validation,
        )

    producing_mov = want_mov and not skip_mov
    producing_png = want_png and not skip_png
    key = workdir_key(
        render_signature=sig,
        clip_start=clip_start,
        clip_duration=clip_duration,
        want_mov=producing_mov,
        want_png=producing_png,
    )
    work = resolve_workdir(performance, key)
    warnings: list[Diagnostic] = []
    outputs: list[dict[str, Any]] = list(skip_outputs)
    keep = keep_temp or bool(performance.workdirs.get("keep_on_failure", True))
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}
    validation: dict[str, Any] = {"passed": False}
    resume_history: list[dict[str, Any]] = []
    try:
        after_hash = sha256_file(job.path)
        if after_hash != source_sha:
            warnings.append(
                Diagnostic(
                    code=DiagnosticCode.E_OUTPUT_VALIDATION,
                    severity=Severity.ERROR,
                    message="Source hash changed during render; sources must be immutable.",
                    path=str(job.path),
                )
            )
            raise RuntimeError("source mutated")
        if clip_duration <= 0:
            raise DecodeError("source duration is zero")
        glow = _glow_sigma(preset)
        raw_threads = performance.processing.get("ffmpeg_threads", 0)
        threads = raw_threads if isinstance(raw_threads, int) else 0
        if job.domain.value == "frequency":
            note(
                f"spectrum decode {clip_duration:.1f}s -> {expected_frames} frames "
                f"@ {job.fps:g} fps"
            )
            reset_workdir(work)
            decoded = work / "source.wav"
            decode_mono_wav(
                job.path,
                decoded,
                start=clip_start if clip_start > 0 else None,
                duration=clip_duration if clip_duration > 0 else None,
            )
            span = resolve_frequency_span(decoded, preset.signal)
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
            peak = None
            if norm_mode != "none":
                note("spectrum peak scan")
                peak = spectrum_peak(
                    decoded,
                    n_frames=expected_frames,
                    fps=job.fps,
                    width=preset.canvas.width,
                    span=span,
                    scale=scale,
                    smoothing_sigma=max(1.0, preset.canvas.width / 200.0) if tau > 0 else 0.0,
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
            )
            png_work: Path | None = work / "png" if producing_png else None
            mov_work: Path | None = work / "spectrum.mov" if producing_mov else None
            note("spectrum encode")
            encode_rgba_stream(
                _tick_frames(
                    frames,
                    n_frames=expected_frames,
                    note=note,
                    label="spectrum",
                ),
                width=preset.canvas.width,
                height=preset.canvas.height,
                fps=job.fps,
                glow=glow,
                png_dir=png_work,
                prores_path=mov_work,
                ffmpeg_threads=threads,
                overscan=glow_overscan(glow),
                supersample=SCROLL_SUPERSAMPLE,
            )
            if mov_work is not None:
                validation = _validate_mov(
                    mov_work,
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    expected_frames=expected_frames,
                )
                if not validation.get("passed"):
                    raise EncodeError("spectrum output failed validation")
                if mov_dest is not None:
                    shutil.move(str(mov_work), str(mov_dest))
                    outputs.append({"path": str(mov_dest), "format": "prores4444"})
            if png_work is not None and png_work.is_dir():
                png_report = _validate_png(png_work, expected_frames=expected_frames)
                if not png_report.get("passed"):
                    raise EncodeError("png sequence failed validation")
                if png_dest is not None and png_dest.exists():
                    shutil.rmtree(png_dest)
                if png_dest is not None:
                    shutil.move(str(png_work), str(png_dest))
                    outputs.append({"path": str(png_dest), "format": "png"})
                if not producing_mov:
                    validation = png_report
            analysis = {
                "chunk_count": 1,
                "preroll_seconds": 0.0,
                "postroll_seconds": 0.0,
                "fmin_hz": span.fmin_hz,
                "fmax_hz": span.fmax_hz,
                "frequency_range": span.source,
            }
            normalization = {"mode": norm_mode, "soft_clip": soft, "peak": peak}
        else:
            note(
                f"scroll decode {clip_duration:.1f}s -> {expected_frames} frames @ {job.fps:g} fps"
            )
            settings = _envelope_settings(preset, job.fps, glow)
            chunk_seconds = _chunk_seconds(performance)
            chunks = plan_chunks(clip_duration, job.fps, chunk_seconds)
            windows = [
                processing_window(
                    chunk,
                    source_duration=clip_duration,
                    preroll=settings.preroll,
                    postroll=settings.postroll,
                )
                for chunk in chunks
            ]
            analysis = {
                "chunk_count": len(chunks),
                "preroll_seconds": settings.preroll,
                "postroll_seconds": settings.postroll,
            }
            cp_file = checkpoint_path(work)
            existing = load_checkpoint(cp_file)
            completed_ok: set[int] = set()
            peak = None
            if existing is not None and identity_matches(
                existing,
                source_sha256=source_sha,
                render_signature=sig,
                visual_contract_version=VISUAL_CONTRACT_VERSION,
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
                    reusable_chunk_indices(
                        work,
                        existing,
                        windows,
                        want_mov=producing_mov,
                        want_png=producing_png,
                    )
                )
                peak = existing.peak
                checkpoint = existing
                checkpoint.completed_chunks = [
                    record for record in existing.completed_chunks if record.index in completed_ok
                ]
            else:
                reset_workdir(work)
                checkpoint = Checkpoint(
                    schema_version=CHECKPOINT_SCHEMA_VERSION,
                    source_sha256=source_sha,
                    render_signature=sig,
                    visual_contract_version=VISUAL_CONTRACT_VERSION,
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
                prepared = _prepare_chunk_envelopes(
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
                    bps = (
                        float(preset.canvas.width * settings.oversample)
                        / preset.waveform.window_seconds
                    )
                    for item in prepared:
                        collected.extend(
                            published_bin_slice(
                                item.bins,
                                start_seconds=item.window.chunk.start_seconds,
                                end_seconds=item.window.chunk.end_seconds,
                                origin_seconds=item.window.decode_start,
                                bins_per_second=bps,
                            )
                        )
                    peak = bin_peak(collected)
                if settings.norm_mode != "none":
                    prepared = [
                        PreparedChunk(
                            window=item.window,
                            bins=normalize_bins(item.bins, soft_clip=settings.soft_clip, peak=peak),
                            origin=item.origin,
                        )
                        for item in prepared
                    ]
                prepared_by_index = {item.window.chunk.index: item for item in prepared}
                checkpoint.peak = peak
                write_checkpoint(cp_file, checkpoint)
            normalization = {
                "mode": settings.norm_mode,
                "soft_clip": settings.soft_clip,
                "peak": peak,
            }
            png_work = work / "png" if producing_png else None
            px_per_frame = preset.canvas.width / (preset.waveform.window_seconds * job.fps)
            raw_shutter = preset.signal.get("shutter_degrees", 0)
            shutter_deg = 0.0
            if isinstance(raw_shutter, int | float) and not isinstance(raw_shutter, bool):
                shutter_deg = max(0.0, float(raw_shutter))
            shutter_px = px_per_frame * shutter_deg / 360.0
            raw_mix = preset.signal.get("shutter_mix", 0.25)
            shutter_mix = 0.25
            if isinstance(raw_mix, int | float) and not isinstance(raw_mix, bool):
                shutter_mix = min(max(float(raw_mix), 0.0), 1.0)
            segments: list[Path] = []
            reused: list[int] = []
            for window in windows:
                chunk = window.chunk
                chunk_mov: Path | None = None
                if producing_mov:
                    chunk_mov = work / f"chunk-{chunk.index:04d}.mov"
                if chunk.index in completed_ok:
                    note(f"chunk {chunk.index + 1}/{len(windows)} reuse")
                    if chunk_mov is not None:
                        segments.append(chunk_mov)
                    reused.append(chunk.index)
                    continue
                note(f"chunk {chunk.index + 1}/{len(windows)} encode {chunk.n_frames} frames")
                item = prepared_by_index[chunk.index]
                frames = _tick_frames(
                    iter_scroll_frames(
                        item.bins,
                        duration=clip_duration,
                        preset=preset,
                        fps=job.fps,
                        glow=glow,
                        first_frame=chunk.first_frame,
                        n_frames=chunk.n_frames,
                        origin=item.origin,
                    ),
                    n_frames=chunk.n_frames,
                    note=note,
                    label=f"chunk {chunk.index + 1}/{len(windows)}",
                )
                if png_work is not None:
                    png_work.mkdir(parents=True, exist_ok=True)
                encode_rgba_stream(
                    frames,
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    fps=job.fps,
                    glow=glow,
                    png_dir=png_work,
                    prores_path=chunk_mov,
                    ffmpeg_threads=threads,
                    overscan=glow_overscan(glow),
                    supersample=SCROLL_SUPERSAMPLE,
                    shutter_px=shutter_px,
                    shutter_mix=shutter_mix,
                    png_start_number=chunk.first_frame + 1,
                )
                if chunk_mov is not None:
                    chunk_report = _validate_mov(
                        chunk_mov,
                        width=preset.canvas.width,
                        height=preset.canvas.height,
                        expected_frames=chunk.n_frames,
                    )
                    if not chunk_report.get("passed"):
                        raise EncodeError(f"chunk {chunk.index:04d} failed validation")
                    segments.append(chunk_mov)
                if png_work is not None and not png_chunk_complete(
                    png_work, first_frame=chunk.first_frame, n_frames=chunk.n_frames
                ):
                    raise EncodeError(f"chunk {chunk.index:04d} png frames missing")
                checkpoint.completed_chunks.append(
                    ChunkRecord(
                        index=chunk.index,
                        first_frame=chunk.first_frame,
                        n_frames=chunk.n_frames,
                        start_seconds=chunk.start_seconds,
                        end_seconds=chunk.end_seconds,
                        mov_name=chunk_mov.name if chunk_mov is not None else None,
                        mov_sha256=sha256_file(chunk_mov) if chunk_mov is not None else None,
                        png_count=chunk.n_frames if png_work is not None else None,
                    )
                )
                write_checkpoint(cp_file, checkpoint)
                if fail_after_chunk is not None and chunk.index >= fail_after_chunk:
                    raise RuntimeError("injected checkpoint stop")
            if reused:
                remaining = [
                    window.chunk.start_seconds
                    for window in windows
                    if window.chunk.index not in reused
                ]
                boundary = min(remaining) if remaining else clip_duration
                warnings.append(
                    Diagnostic(
                        code=DiagnosticCode.W_JOB_RESUMED,
                        severity=Severity.WARNING,
                        message=(
                            f"Resumed at source timestamp {boundary:.3f}s "
                            f"(reused {len(reused)} chunk(s))."
                        ),
                        path=str(job.path),
                    )
                )
                resume_history.append(
                    {
                        "resumed": True,
                        "boundary_seconds": boundary,
                        "reused_chunks": reused,
                    }
                )
            if producing_mov:
                note(f"concat {len(segments)} segment(s)")
                tmp_mov = work / "out.mov"
                concat_videos(segments, tmp_mov, list_path=work / "concat.txt")
                validation = _validate_mov(
                    tmp_mov,
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    expected_frames=expected_frames,
                )
                if not validation.get("passed"):
                    raise EncodeError("scroll output failed validation")
                if mov_dest is not None:
                    shutil.move(str(tmp_mov), str(mov_dest))
                    outputs.append({"path": str(mov_dest), "format": "prores4444"})
            if png_work is not None and png_work.is_dir():
                png_report = _validate_png(png_work, expected_frames=expected_frames)
                if not png_report.get("passed"):
                    raise EncodeError("png sequence failed validation")
                if png_dest is not None and png_dest.exists():
                    shutil.rmtree(png_dest)
                if png_dest is not None:
                    shutil.move(str(png_work), str(png_dest))
                    outputs.append({"path": str(png_dest), "format": "png"})
                if not producing_mov:
                    validation = png_report
                else:
                    validation = {**validation, "png_frames": png_report.get("frames")}
        status = "SUCCEEDED"
        validation["passed"] = True
    except (DecodeError, EncodeError, OSError, RuntimeError, ProbeError) as exc:
        status = "FAILED"
        warnings.append(
            Diagnostic(
                code=DiagnosticCode.E_OUTPUT_VALIDATION
                if "hash" in str(exc) or "validation" in str(exc)
                else DiagnosticCode.E_RENDERER_CAPABILITY,
                severity=Severity.ERROR,
                message=str(exc),
            )
        )
        validation = {**validation, "passed": False}
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
        payload = _result_payload(
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
            workdir=str(work) if Path(work).exists() else None,
            validation=validation,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
        )
        return payload
    else:
        if not keep_temp and not bool(performance.workdirs.get("keep_on_success", False)):
            shutil.rmtree(work, ignore_errors=True)
            work_out = None
        else:
            work_out = str(work)
        return _result_payload(
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
            workdir=work_out,
            validation=validation,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
        )


@dataclass(frozen=True)
class PreparedChunk:
    window: ProcessingWindow
    bins: list[float]
    origin: float


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
    prepared: list[PreparedChunk] = []
    for window in windows:
        decoded = work / f"chunk-{window.chunk.index:04d}.wav"
        abs_start = clip_start + window.decode_start
        decode_mono_wav(
            source,
            decoded,
            start=abs_start if abs_start > 0 else None,
            duration=window.decode_duration if window.decode_duration > 0 else None,
        )
        decoded_media = probe_media(decoded)
        bins, hop = _filter_wav(
            decoded,
            settings,
            decoded_media.sample_rate,
            width,
            window_seconds,
        )
        origin = bin_origin(window.decode_start, decoded_media.sample_rate, hop)
        prepared.append(PreparedChunk(window=window, bins=bins, origin=origin))
    return prepared


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
) -> dict[str, Any]:
    glow = preset.effects.get("glow") if isinstance(preset.effects.get("glow"), dict) else {}
    report = validation if validation is not None else {"passed": status == "SUCCEEDED"}
    return {
        "schema_version": 1,
        "tool": {"name": "ewp-waveform", "version": __version__},
        "job": {
            "job_id": f"{job.project_id}-{job.track_id}-{short_signature(sig)}",
            "status": status,
            "render_signature": sig,
            "seed": 0,
        },
        "renderer": {
            "name": "ffmpeg",
            "version": "system",
            "visual_contract_version": VISUAL_CONTRACT_VERSION,
        },
        "project": {"project_id": job.project_id, "track_id": job.track_id},
        "inputs": [
            {
                "path": str(media.path),
                "sha256": source_sha,
                "size_bytes": media.size_bytes,
                "duration_seconds": media.duration_seconds,
                "codec": media.codec,
                "sample_rate": media.sample_rate,
                "channels": media.channels,
            }
        ],
        "preset": {"name": preset.name, "source": "builtin"},
        "resolved_visual_config": {
            "fps": job.fps,
            "style": preset.waveform.style,
            "domain": preset.waveform.domain,
            "time_mode": preset.waveform.time_mode,
            "color": preset.waveform.color,
            "window_seconds": preset.waveform.window_seconds,
            "envelope_oversample": envelope_oversample_from_signal(preset.signal),
            "envelope_aa": envelope_aa_from_signal(preset.signal)[0],
            "envelope_aa_support": envelope_aa_from_signal(preset.signal)[1],
            "shutter_degrees": preset.signal.get("shutter_degrees", 0),
            "shutter_mix": preset.signal.get("shutter_mix", 0.25),
            "envelope_motion_lpf": motion_lpf_from_signal(preset.signal)[0],
            "envelope_motion_cutoff": motion_cutoff_cyc_px(
                width=preset.canvas.width,
                window_seconds=preset.waveform.window_seconds,
                fps=job.fps,
                margin=motion_lpf_from_signal(preset.signal)[2],
                explicit=motion_lpf_from_signal(preset.signal)[1],
            ),
            "glow": glow,
        },
        "resolved_performance_config": {
            "profile": performance.name,
            **performance.processing,
        },
        "analysis": analysis or {},
        "normalization": normalization or {},
        "warnings": [w.model_dump(mode="json") for w in warnings],
        "outputs": outputs,
        "validation": report,
        "performance": {},
        "resume_history": resume_history or [],
        "timestamps": {
            "started_at": started,
            "completed_at": (completed := _utcnow()),
            "duration_seconds": elapsed_seconds(started, completed),
        },
        "execution": {
            "workdir": workdir,
            "capability": job.capability.value,
            "resumed": bool(resume_history),
        },
    }
