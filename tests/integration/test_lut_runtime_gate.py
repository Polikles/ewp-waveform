from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ewp_waveform.ffmpeg.ribbon_lut import qualify_ribbon_lut


def test_runtime_lut_gate_preserves_all_code_values_and_edges(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("actual FFmpeg byte oracle required")
    result = qualify_ribbon_lut(ffmpeg, tmp_path / "lut-oracle")
    assert result["passed"] is True
    cases = result["cases"]
    assert isinstance(cases, list) and len(cases) == 6
    for i in (0, 2, 4):
        assert cases[i]["frames"] == cases[i + 1]["frames"] == 258
        assert cases[i]["rgba_sha256"] == cases[i + 1]["rgba_sha256"]
