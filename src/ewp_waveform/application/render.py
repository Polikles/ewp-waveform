"""Render orchestration: workdir, envelope scroll, experimental spectrum, publish."""

from __future__ import annotations

import math
import shutil
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ewp_waveform import __version__
from ewp_waveform.analysis.envelope import (
    antialias_envelope,
    envelope_aa_from_signal,
    envelope_oversample_from_signal,
    hop_samples,
    normalize_bins,
    rms_bins_from_wav,
    scale_amplitude,
    smooth_bins,
    viewport_left_px,
    window_at_column,
)
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.decode import DecodeError, decode_mono_wav
from ewp_waveform.ffmpeg.draw import SCROLL_SUPERSAMPLE, draw_envelope_frame, glow_overscan
from ewp_waveform.ffmpeg.encode import (
    EncodeError,
    encode_rgba_stream,
    encode_spectrum_showfreqs,
    glow_sigma,
)
from ewp_waveform.ffmpeg.probe import probe_media
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


def publish_path(
    dest: Path,
    *,
    force: bool,
) -> tuple[Path, bool]:
    """Return dest, skip. skip True means equivalent output already present."""
    if not dest.exists():
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
) -> Iterator[bytes]:
    width = preset.canvas.width
    height = preset.canvas.height
    n_frames = max(1, round(duration * fps))
    stroke = preset.waveform.stroke_width or 6.0
    center = bool(preset.waveform.center_line)
    window_seconds = preset.waveform.window_seconds
    pad = glow_overscan(glow)
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    ss = SCROLL_SUPERSAMPLE
    oversample = envelope_oversample_from_signal(preset.signal)
    env_w = draw_w * oversample
    for i in range(n_frames):
        vis_start = viewport_left_px(i, fps, window_seconds, width)
        draw_start = vis_start - pad
        draw_start_bins = draw_start * oversample
        raw = window_at_column(
            bins,
            end_exclusive=math.floor(draw_start_bins) + env_w + 1,
            width=env_w + 1,
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
            outputs=[],
            warnings=[],
        )

    work = Path(tempfile.mkdtemp(prefix="ewp-waveform-"))
    warnings: list[Diagnostic] = []
    outputs: list[dict[str, Any]] = []
    keep = keep_temp or bool(performance.workdirs.get("keep_on_failure", True))
    try:
        decoded = work / "source.wav"
        decode_mono_wav(job.path, decoded, start=start, duration=duration)
        decoded_media = probe_media(decoded)
        wav_duration = decoded_media.duration_seconds
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
        glow = _glow_sigma(preset)
        raw_threads = performance.processing.get("ffmpeg_threads", 0)
        threads = raw_threads if isinstance(raw_threads, int) else 0
        if job.domain.value == "frequency":
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
                shutil.move(str(tmp_mov), str(mov_dest))
                outputs.append({"path": str(mov_dest), "format": "prores4444"})
        else:
            oversample = envelope_oversample_from_signal(preset.signal)
            hop = hop_samples(
                decoded_media.sample_rate,
                preset.canvas.width,
                preset.waveform.window_seconds,
                oversample=oversample,
            )
            bins = rms_bins_from_wav(decoded, hop)
            scale = str(preset.signal.get("scale") or "sqrt")
            bins = [scale_amplitude(v, scale) for v in bins]
            raw_smooth = preset.signal.get("smoothing", 0.0)
            smoothing = 0.0
            if isinstance(raw_smooth, int | float) and not isinstance(raw_smooth, bool):
                smoothing = float(raw_smooth)
            if smoothing > 0.0:
                bins_per_second = preset.canvas.width / preset.waveform.window_seconds
                bins = smooth_bins(bins, sigma=smoothing * bins_per_second)
            aa_kind, aa_support = envelope_aa_from_signal(preset.signal)
            bins = antialias_envelope(
                bins,
                oversample=oversample,
                kind=aa_kind,
                support_px=aa_support,
            )
            norm = preset.signal.get("normalization")
            norm_mode = "auto"
            soft = True
            if isinstance(norm, dict):
                norm_mode = str(norm.get("mode") or "auto")
                soft = bool(norm.get("soft_clip", True))
            if norm_mode != "none":
                bins = normalize_bins(bins, soft_clip=soft)
            frames = iter_scroll_frames(
                bins,
                duration=wav_duration,
                preset=preset,
                fps=job.fps,
                glow=glow,
            )
            png_work: Path | None = work / "png" if want_png else None
            mov_work: Path | None = work / "out.mov" if want_mov and not skip_mov else None
            px_per_frame = preset.canvas.width / (preset.waveform.window_seconds * job.fps)
            raw_shutter = preset.signal.get("shutter_degrees", 60)
            shutter_deg = 60.0
            if isinstance(raw_shutter, int | float) and not isinstance(raw_shutter, bool):
                shutter_deg = max(0.0, float(raw_shutter))
            shutter_px = px_per_frame * shutter_deg / 360.0
            raw_mix = preset.signal.get("shutter_mix", 0.25)
            shutter_mix = 0.25
            if isinstance(raw_mix, int | float) and not isinstance(raw_mix, bool):
                shutter_mix = min(max(float(raw_mix), 0.0), 1.0)
            encode_rgba_stream(
                frames,
                width=preset.canvas.width,
                height=preset.canvas.height,
                fps=job.fps,
                glow=glow,
                png_dir=png_work,
                prores_path=mov_work,
                ffmpeg_threads=threads,
                overscan=glow_overscan(glow),
                supersample=SCROLL_SUPERSAMPLE,
                shutter_px=shutter_px,
                shutter_mix=shutter_mix,
            )
            if mov_work is not None and mov_work.is_file():
                shutil.move(str(mov_work), str(mov_dest))
                outputs.append({"path": str(mov_dest), "format": "prores4444"})
            if png_work is not None and png_work.is_dir() and not skip_png:
                if png_dest.exists():
                    shutil.rmtree(png_dest)
                shutil.move(str(png_work), str(png_dest))
                outputs.append({"path": str(png_dest), "format": "png"})
        status = "SUCCEEDED"
    except (DecodeError, EncodeError, OSError, RuntimeError) as exc:
        status = "FAILED"
        warnings.append(
            Diagnostic(
                code=DiagnosticCode.E_OUTPUT_VALIDATION
                if "hash" in str(exc)
                else DiagnosticCode.E_RENDERER_CAPABILITY,
                severity=Severity.ERROR,
                message=str(exc),
            )
        )
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
) -> dict[str, Any]:
    glow = preset.effects.get("glow") if isinstance(preset.effects.get("glow"), dict) else {}
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
            "shutter_degrees": preset.signal.get("shutter_degrees", 60),
            "shutter_mix": preset.signal.get("shutter_mix", 0.25),
            "glow": glow,
        },
        "resolved_performance_config": {
            "profile": performance.name,
            **performance.processing,
        },
        "warnings": [w.model_dump(mode="json") for w in warnings],
        "outputs": outputs,
        "validation": {"passed": status == "SUCCEEDED"},
        "timestamps": {"started_at": started, "completed_at": _utcnow()},
        "execution": {"workdir": workdir, "capability": job.capability.value},
    }
