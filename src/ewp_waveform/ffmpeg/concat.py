"""Concat demuxer helper. Command construction stays in the FFmpeg adapter."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from ewp_waveform.ffmpeg.encode import EncodeError
from ewp_waveform.ffmpeg.process import require_tool, run_argv


def concat_list_line(path: Path) -> str:
    """One concat-demuxer list line. Single quotes are escaped."""
    text = str(path.resolve()).replace("'", r"'\''")
    return f"file '{text}'"


def concat_videos(parts: Sequence[Path], dest: Path, *, list_path: Path | None = None) -> None:
    """Copy-concat same-codec segments. ``parts`` must be non-empty."""
    if not parts:
        msg = "concat requires at least one segment"
        raise EncodeError(msg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        source = parts[0]
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        return
    ffmpeg = require_tool("ffmpeg")
    listing = list_path if list_path is not None else dest.parent / f"{dest.name}.concat.txt"
    listing.write_text("\n".join(concat_list_line(part) for part in parts) + "\n", encoding="utf-8")
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-c",
        "copy",
        str(dest),
    ]
    completed = run_argv(argv)
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        msg = completed.stderr.strip() or "ffmpeg concat failed"
        raise EncodeError(msg)
