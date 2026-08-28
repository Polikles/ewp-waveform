"""ffprobe inspection (FFmpeg adapter only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ewp_waveform.domain.models import SourceMedia
from ewp_waveform.ffmpeg.process import require_tool, run_argv


class ProbeError(RuntimeError):
    pass


def probe_media(path: Path) -> SourceMedia:
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
    payload = cast(dict[str, Any], json.loads(completed.stdout))
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
