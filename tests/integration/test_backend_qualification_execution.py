"""Real bounded software controls and deliberately absent-device execution.

This test does not require, repair, select or claim a physical GPU. Vulkan loader
capabilities are observed on the test host; a nonexistent explicit device name
prevents incidental execution on an operator's hardware during the test suite.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ewp_waveform.ffmpeg.backend_qualification import qualify


def test_real_cpu_controls_and_independent_absent_device(tmp_path: Path) -> None:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg executable pair unavailable")
    result = qualify(
        ffmpeg,
        ffprobe,
        tmp_path,
        device="EWP_NONEXISTENT_DEVICE_7063",
        expected="EWP_NONEXISTENT_DEVICE_7063",
    )
    assert result["cpu_controls_status"] == "PASS"
    assert result["same_build_control"]["status"] == "PASS"
    assert len(result["transfer"]["cases"]) == 8
    assert len(result["blur"]["cases"]) == 2
    assert len(result["prores"]["cases"]) == len(result["ffv1"]["cases"]) == 2
    assert not result["all_backends_passed"]
    for backend in ("transfer", "blur", "prores", "ffv1"):
        assert result[backend]["status"] in ("CAPABILITY_UNAVAILABLE", "EXECUTION_ERROR")
    for name, case in result["cpu_controls"].items():
        if name.startswith("ffv1/"):
            assert case["lossless_rgba_including_hidden_rgb"]
        else:
            assert case["alpha_oracle"]["maximum_10bit_code_error"] <= 1
        assert case["timing"]["frames"] == 2
    assert all("argv" in c and "stderr" in c and "returncode" in c for c in result["commands"])
    assert (
        json.loads((tmp_path / "qualification.json").read_text())["cpu_controls_status"] == "PASS"
    )
    assert not list(tmp_path.glob("codec-media-*"))
