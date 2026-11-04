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
    profile: str = ""


def _probe_json(path: Path, *, first_frame: bool = False) -> dict[str, Any]:
    ffprobe = require_tool("ffprobe")
    argv = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
    ]
    if first_frame:
        argv.extend(["-read_intervals", "%+#1", "-show_frames"])
    argv.append(str(path))
    completed = run_argv(argv)
    if completed.returncode != 0 or (first_frame and completed.stderr.strip()):
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
    # Decode only the first packet, not the complete movie, on this hot path.
    payload = _probe_json(path, first_frame=True)
    frames = payload.get("frames") or []
    if not any(frame.get("media_type") == "video" for frame in frames):
        raise ProbeError(f"No readable video frame in {path}")
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
        profile=str(video.get("profile") or ""),
    )


def probe_png_sequence(directory: Path) -> list[dict[str, Any]]:
    """Decode sequence frames once; return only geometry/pixel-format metadata.

    ffprobe can report decode errors on stderr while exiting zero. Reject both.
    Names/count/file presence are checked by the caller before image2 traversal.
    """
    ffprobe = require_tool("ffprobe")
    completed = run_argv(
        [
            str(ffprobe),
            "-v",
            "error",
            "-f",
            "image2",
            "-start_number",
            "1",
            "-i",
            str(directory / "frame_%06d.png"),
            "-show_frames",
            "-show_entries",
            "stream=codec_name:frame=width,height,pix_fmt",
            "-of",
            "json",
        ]
    )
    if completed.returncode != 0 or completed.stderr.strip():
        raise ProbeError(completed.stderr.strip() or "PNG sequence inspection failed")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if len(streams) != 1 or streams[0].get("codec_name") != "png":
        raise ProbeError("PNG sequence does not contain PNG images")
    return cast(list[dict[str, Any]], payload.get("frames") or [])
