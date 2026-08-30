"""ffprobe inspection (FFmpeg adapter only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ewp_waveform.domain.models import SourceMedia
from ewp_waveform.ffmpeg.process import require_tool, run_argv


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoStreamInfo:
    codec_name: str
    pix_fmt: str
    width: int
    height: int
    nb_frames: int | None
    duration_seconds: float
    avg_frame_rate: str


def _probe_json(path: Path) -> dict[str, Any]:
    ffprobe = require_tool("ffprobe")
    argv = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    completed = run_argv(argv)
    if completed.returncode != 0:
        msg = completed.stderr.strip() or f"ffprobe failed for {path}"
        raise ProbeError(msg)
    return cast(dict[str, Any], json.loads(completed.stdout))


def probe_media(path: Path) -> SourceMedia:
    payload = _probe_json(path)
    streams = payload.get("streams") or []
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if audio is None:
        msg = f"No audio stream in {path}"
        raise ProbeError(msg)
    fmt = payload.get("format") or {}
    duration = float(audio.get("duration") or fmt.get("duration") or 0.0)
    return SourceMedia(
        path=path,
        duration_seconds=duration,
        sample_rate=int(audio["sample_rate"]),
        channels=int(audio.get("channels") or 1),
        codec=str(audio.get("codec_name") or "unknown"),
        format_name=str(fmt.get("format_name") or path.suffix.lstrip(".")),
        size_bytes=int(fmt.get("size") or path.stat().st_size),
    )


def probe_video(path: Path) -> VideoStreamInfo:
    payload = _probe_json(path)
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        msg = f"No video stream in {path}"
        raise ProbeError(msg)
    fmt = payload.get("format") or {}
    raw_frames = video.get("nb_frames")
    nb_frames: int | None
    try:
        nb_frames = int(raw_frames) if raw_frames not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        nb_frames = None
    duration = float(video.get("duration") or fmt.get("duration") or 0.0)
    return VideoStreamInfo(
        codec_name=str(video.get("codec_name") or "unknown"),
        pix_fmt=str(video.get("pix_fmt") or ""),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        nb_frames=nb_frames,
        duration_seconds=duration,
        avg_frame_rate=str(video.get("avg_frame_rate") or ""),
    )
