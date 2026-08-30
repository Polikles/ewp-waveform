"""Render orchestration: workdir, envelope scroll, experimental spectrum, publish."""

from __future__ import annotations

import math
import shutil
import tempfile
from collections.abc import Iterator, Sequence
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
from ewp_waveform.application.chunks import (
    ProcessingWindow,
    bin_origin,
    plan_chunks,
    processing_window,
)
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.concat import concat_videos
from ewp_waveform.ffmpeg.decode import DecodeError, decode_mono_wav
from ewp_waveform.ffmpeg.draw import SCROLL_SUPERSAMPLE, draw_envelope_frame, glow_overscan
from ewp_waveform.ffmpeg.encode import (
    EncodeError,
    encode_rgba_stream,
    encode_spectrum_showfreqs,
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
) -> dict[str, Any]:
    started = _utcnow()
    source_sha = sha256_file(job.path)
    after_hash = source_sha
    sig = render_signature(source_sha256=source_sha, preset=preset, fps=job.fps)
    short = short_signature(sig)
    project_dir = output_dir / job.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{job.path.stem}_{preset.name}_{short}"
    want_png = "png" in formats
    want_mov = "prores4444" in formats or not formats
    mov_dest = project_dir / f"{stem}.mov"
    png_dest = project_dir / f"{stem}_png"
    skip_mov = False
    skip_png = False
    if want_mov:
        mov_dest, skip_mov = publish_path(mov_dest, force=force)
    if want_png:
        png_dest, skip_png = publish_path(png_dest, force=force)

    clip_start, clip_duration = _clip_bounds(media, start, duration)
    expected_frames = max(1, round(clip_duration * job.fps))
    skip_outputs: list[dict[str, Any]] = []
    skip_validation: dict[str, Any] = {"passed": True}
    if want_mov and skip_mov:
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
        png_report = _validate_png(png_dest, expected_frames=expected_frames)
        if not png_report.get("passed"):
            skip_png = False
        else:
            skip_outputs.append({"path": str(png_dest), "format": "png"})
            if not (want_mov and skip_mov):
                skip_validation = png_report

    if (not want_mov or skip_mov) and (not want_png or skip_png) and not force:
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

    work = Path(tempfile.mkdtemp(prefix="ewp-waveform-"))
    warnings: list[Diagnostic] = []
    outputs: list[dict[str, Any]] = list(skip_outputs)
    keep = keep_temp or bool(performance.workdirs.get("keep_on_failure", True))
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}
    validation: dict[str, Any] = {"passed": False}
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
            decoded = work / "source.wav"
            decode_mono_wav(
                job.path,
                decoded,
                start=clip_start if clip_start > 0 else None,
                duration=clip_duration if clip_duration > 0 else None,
            )
            tmp_mov = work / "spectrum.mov"
            encode_spectrum_showfreqs(
                decoded if decoded.is_file() else job.path,
                tmp_mov,
                width=preset.canvas.width,
                height=preset.canvas.height,
                fps=job.fps,
                color=preset.waveform.color,
                glow=glow,
                ffmpeg_threads=threads,
            )
            if want_mov and not skip_mov:
                validation = _validate_mov(
                    tmp_mov,
                    width=preset.canvas.width,
                    height=preset.canvas.height,
                    expected_frames=expected_frames,
                )
                if not validation.get("passed"):
                    raise EncodeError("spectrum output failed validation")
                shutil.move(str(tmp_mov), str(mov_dest))
                outputs.append({"path": str(mov_dest), "format": "prores4444"})
            analysis = {"chunk_count": 1, "preroll_seconds": 0.0, "postroll_seconds": 0.0}
        else:
            settings = _envelope_settings(preset, job.fps, glow)
            chunks = plan_chunks(clip_duration, job.fps, _chunk_seconds(performance))
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
            prepared = _prepare_chunk_envelopes(
                job.path,
                windows,
                settings,
                work=work,
                clip_start=clip_start,
                width=preset.canvas.width,
                window_seconds=preset.waveform.window_seconds,
            )
            peak: float | None = None
            if settings.norm_mode != "none":
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
                prepared = [
                    PreparedChunk(
                        window=item.window,
                        bins=normalize_bins(item.bins, soft_clip=settings.soft_clip, peak=peak),
                        origin=item.origin,
                    )
                    for item in prepared
                ]
            normalization = {
                "mode": settings.norm_mode,
                "soft_clip": settings.soft_clip,
                "peak": peak,
            }
            png_work: Path | None = work / "png" if want_png and not skip_png else None
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
            for item in prepared:
                chunk = item.window.chunk
                frames = iter_scroll_frames(
                    item.bins,
                    duration=clip_duration,
                    preset=preset,
                    fps=job.fps,
                    glow=glow,
                    first_frame=chunk.first_frame,
                    n_frames=chunk.n_frames,
                    origin=item.origin,
                )
                chunk_mov: Path | None = None
                if want_mov and not skip_mov:
                    chunk_mov = work / f"chunk-{chunk.index:04d}.mov"
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
                if chunk_mov is not None and chunk_mov.is_file():
                    segments.append(chunk_mov)
            if want_mov and not skip_mov:
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
                shutil.move(str(tmp_mov), str(mov_dest))
                outputs.append({"path": str(mov_dest), "format": "prores4444"})
            if png_work is not None and png_work.is_dir():
                png_report = _validate_png(png_work, expected_frames=expected_frames)
                if not png_report.get("passed"):
                    raise EncodeError("png sequence failed validation")
                if png_dest.exists():
                    shutil.rmtree(png_dest)
                shutil.move(str(png_work), str(png_dest))
                outputs.append({"path": str(png_dest), "format": "png"})
                if not (want_mov and not skip_mov):
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
        "timestamps": {"started_at": started, "completed_at": _utcnow()},
        "execution": {"workdir": workdir, "capability": job.capability.value},
    }
