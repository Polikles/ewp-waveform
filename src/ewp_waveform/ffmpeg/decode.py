"""Decode source audio to a workdir WAV. Never writes the source path."""

from __future__ import annotations

from pathlib import Path

from ewp_waveform.ffmpeg.process import require_tool, run_argv


class DecodeError(RuntimeError):
    pass


def decode_mono_wav(
    source: Path,
    dest: Path,
    sample_rate: int = 48000,
    start: float | None = None,
    duration: float | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() == source.resolve():
        msg = "refusing to decode onto the source file"
        raise DecodeError(msg)
    ffmpeg = require_tool("ffmpeg")
    argv = [str(ffmpeg), "-hide_banner", "-y"]
    if start is not None and start > 0:
        argv.extend(["-ss", str(start)])
    argv.extend(["-i", str(source)])
    if duration is not None and duration > 0:
        argv.extend(["-t", str(duration)])
    argv.extend(
        [
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )
    completed = run_argv(argv)
    if completed.returncode != 0 or not dest.is_file():
        msg = completed.stderr.strip() or f"ffmpeg decode failed for {source}"
        raise DecodeError(msg)
