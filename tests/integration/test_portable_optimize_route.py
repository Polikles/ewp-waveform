"""Real bounded native outputs via the portable worker, never original audio."""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import uuid
import wave
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application.portable_experiments_worker import dispatch


def test_direct_ffv1_and_individual_filter_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = os.environ.get("EWP_EXPERIMENT_TEST_MEDIA")
    if not parent:
        pytest.skip("explicit outside-Git synthetic media destination required")
    monkeypatch.setenv("PATH", os.environ["PATH"])
    monkeypatch.setenv("EWP_ANALYSIS_CACHE", str(tmp_path / "unused-cache"))
    root = Path(parent) / ("direct-opt-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    audio = root / "synthetic.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(
            b"".join(struct.pack("<h", int(12000 * math.sin(i / 20))) for i in range(9600))
        )
    repo = Path(__file__).resolve().parents[2]
    visual = json.loads((repo / "examples/experiments/wsl-suite.json").read_text())[
        "visual_overrides"
    ]
    base: dict[str, Any] = {
        "operation": "direct",
        "audio": str(audio),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "original_path": os.environ["PATH"],
        "visual_overrides": visual,
        "device": "RTX 3090",
        "workload": {
            "id": "synthetic",
            "kind": "short",
            "start": 0.0,
            "duration": 0.2,
            "frames": 12,
        },
    }
    results: dict[str, Any] = {}
    for name, codec, settings in (
        ("mov", "prores", {}),
        ("mkv", "ffv1", {}),
        ("encoder", "ffv1", {"encoder_threads": 2}),
        ("filter", "prores", {"filter_threads": 1}),
    ):
        evidence = tmp_path / name
        evidence.mkdir()
        request = {
            **base,
            **settings,
            "codec": codec,
            "media": str(root / name),
            "evidence": str(evidence),
        }
        control = results.get("mkv" if codec == "ffv1" else "mov")
        if control:
            request.update(
                reference=control["output"],
                reference_lossless=True,
                expected_raster_sha256=control["original_raster_sha256"],
            )
        result = dispatch(request)
        results[name] = result
        assert result["validation"]["passed"]
        assert result["validation"]["frames"] == 12
        assert result["phase_metrics"]["counts"]["ffmpeg_feed"] == 12
        commands = [
            json.loads(line) for line in (evidence / "commands.jsonl").read_text().splitlines()
        ]
        encoded = [row["argv"] for row in commands if row.get("phase") == "suite-service-encode"]
        assert len(encoded) == 1
        assert encoded[0][encoded[0].index("-i") + 1] == "-"
        assert result["output"].endswith(".mkv" if codec == "ffv1" else ".mov")
    assert len({r["original_raster_sha256"] for r in results.values()}) == 1
    assert (
        results["mkv"]["validation"]["decoded_rgba_sha256"]
        == results["encoder"]["validation"]["decoded_rgba_sha256"]
    )
    assert (
        results["mov"]["validation"]["decoded_rgba_sha256"]
        == results["filter"]["validation"]["decoded_rgba_sha256"]
    )
    evidence = tmp_path / "prefix"
    evidence.mkdir()
    prefix = dispatch(
        {
            **base,
            "operation": "codec",
            "reference": results["mov"]["output"],
            "reference_workload": base["workload"],
            "codec_prefix": True,
            "workload": {**base["workload"], "frames": 6, "duration": 0.1},
            "gpu": False,
            "media": str(root / "prefix"),
            "evidence": str(evidence),
        }
    )
    assert prefix["validation"]["reference_prefix_frames"] == 6
    assert prefix["validation"]["frames"] == 6
    assert prefix["validation"]["lossless_against_reference_master"]
    assert prefix["comparison_mov"] is None
