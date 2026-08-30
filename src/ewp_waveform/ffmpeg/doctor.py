"""Environment checks for FFmpeg/ffprobe/encoders/filters."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ewp_waveform.ffmpeg.process import ToolNotFoundError, require_tool, run_argv

REQUIRED_ENCODERS = ("prores_ks", "png")
REQUIRED_FILTERS = ("gblur", "overlay", "scale")
MIN_TEMP_FREE_BYTES = 256 * 1024 * 1024


def _has_line(haystack: str, needle: str) -> bool:
    return any(needle in line for line in haystack.splitlines())


def check_environment() -> list[str]:
    """Return human-readable findings. Empty list means doctor passed."""
    problems: list[str] = []
    tmp = Path(tempfile.gettempdir())
    if not os.access(tmp, os.W_OK):
        problems.append(f"temp dir not writable: {tmp}")
    else:
        free = shutil.disk_usage(tmp).free
        if free < MIN_TEMP_FREE_BYTES:
            problems.append(
                f"low disk space in {tmp}: {free // (1024 * 1024)} MiB free (need >= 256 MiB)"
            )
    try:
        ffmpeg = require_tool("ffmpeg")
    except ToolNotFoundError as exc:
        problems.append(str(exc))
        ffmpeg = None
    try:
        ffprobe = require_tool("ffprobe")
    except ToolNotFoundError as exc:
        problems.append(str(exc))
        ffprobe = None
    if ffmpeg is not None:
        enc = run_argv([str(ffmpeg), "-hide_banner", "-encoders"])
        for name in REQUIRED_ENCODERS:
            if enc.returncode != 0 or not _has_line(enc.stdout, name):
                problems.append(f"ffmpeg build lacks {name} encoder")
        filters = run_argv([str(ffmpeg), "-hide_banner", "-filters"])
        for name in REQUIRED_FILTERS:
            if filters.returncode != 0 or not _has_line(filters.stdout, name):
                problems.append(f"ffmpeg build lacks filter {name}")
    if ffprobe is not None:
        probe = run_argv([str(ffprobe), "-version"])
        if probe.returncode != 0:
            problems.append("ffprobe -version failed")
    return problems
