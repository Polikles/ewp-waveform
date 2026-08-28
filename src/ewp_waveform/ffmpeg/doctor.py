"""Environment checks for FFmpeg/ffprobe/encoders/filters."""

from __future__ import annotations

from ewp_waveform.ffmpeg.process import ToolNotFoundError, require_tool, run_argv


def _has_line(haystack: str, needle: str) -> bool:
    return any(needle in line for line in haystack.splitlines())


def check_environment() -> list[str]:
    """Return human-readable findings. Empty list means doctor passed."""
    problems: list[str] = []
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
        if enc.returncode != 0 or not _has_line(enc.stdout, "prores_ks"):
            problems.append("ffmpeg build lacks prores_ks encoder")
        if enc.returncode != 0 or not _has_line(enc.stdout, "png"):
            problems.append("ffmpeg build lacks png encoder")
        filters = run_argv([str(ffmpeg), "-hide_banner", "-filters"])
        for name in ("showwaves", "showwavespic", "showfreqs", "gblur"):
            if filters.returncode != 0 or not _has_line(filters.stdout, name):
                problems.append(f"ffmpeg build lacks filter {name}")
    if ffprobe is not None:
        probe = run_argv([str(ffprobe), "-version"])
        if probe.returncode != 0:
            problems.append("ffprobe -version failed")
    return problems
