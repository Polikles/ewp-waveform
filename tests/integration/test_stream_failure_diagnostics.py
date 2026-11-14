from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from ewp_waveform.ffmpeg.encode import encode_rgba_stream
from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding
from ewp_waveform.ffmpeg.process import run_argv_stdin


def test_real_ffmpeg_diagnostics_survive_original_generator_exception(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("actual FFmpeg required")
    log = tmp_path / "commands.jsonl"

    def frames() -> Iterator[bytes]:
        yield bytes(16 * 16 * 4)
        raise RuntimeError("original generator sentinel")

    with pytest.raises(RuntimeError, match="original generator sentinel"):
        encode_rgba_stream(
            frames(),
            width=16,
            height=16,
            fps=60,
            glow=0,
            png_dir=None,
            prores_path=tmp_path / "partial.mov",
            experiment=SuiteEncoding("CPU-CONTROL", log),
        )
    diagnostic = log.with_suffix(".service.stderr").read_bytes()
    assert len(diagnostic) > 100
    assert b"Input #0" in diagnostic


def test_failed_diagnostic_persistence_does_not_mask_generator_error(tmp_path: Path) -> None:
    def frames() -> Iterator[bytes]:
        raise ValueError("original generator sentinel")
        yield b"unreachable"

    with pytest.raises(ValueError, match="original generator sentinel") as caught:
        run_argv_stdin(
            [sys.executable, "-c", "import sys; sys.stderr.write('actual child diagnostic')"],
            frames(),
            stderr_path=tmp_path / "absent" / "stderr.txt",
        )
    assert any("stderr persistence failed" in note for note in caught.value.__notes__)
