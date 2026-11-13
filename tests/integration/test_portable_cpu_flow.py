"""Real six-frame production service + unchanged frozen resume, no GPU/full claims."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_portable_real_cpu_service_and_read_only_resume(tmp_path: Path) -> None:
    command = [
        sys.executable,
        str(app.DRIVER),
        "--cpu-smoke",
        "--python",
        sys.executable,
        "--output-root",
        str(tmp_path / "reports"),
        "--media-root",
        str(tmp_path / "media"),
        "--max-growth-gib",
        "0.25",
        "--reserve-gib",
        "0.01",
    ]
    environment = {
        **os.environ,
        "PYTHONPATH": str(app.ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    run = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=180)
    assert run.returncode == 0, run.stdout + run.stderr
    roots = list((tmp_path / "reports").glob("run-*"))
    assert len(roots) == 1
    root = roots[0]
    value = json.loads((root / "steps/smoke-cpu-selected/value.json").read_text())
    assert value["status"] == "SUCCEEDED"
    assert value["route"] == "STOCK_SERVICE"
    assert value["validation"]["frames"] == 6
    assert value["validation"]["passed"]
    assert value["service_result"]["job"]["status"] == "SUCCEEDED"
    # Same smoke graph now exercises CPU oracle, matched custom FFmpeg control,
    # two sequential AB/BA repetitions, native MKV and actual deduplicated views.
    from ewp_waveform.application.portable_experiments_reporting import pair_statistics
    from ewp_waveform.application.portable_experiments_state import completed_steps

    steps = completed_steps(root)
    assert steps["finish-qualify-numpy"]["passed"] is True
    for name in (
        "smoke-fir-algorithm-r01-A",
        "smoke-fir-algorithm-r01-B",
        "smoke-fir-algorithm-r02-B",
        "smoke-fir-algorithm-r02-A",
        "smoke-ffv1-cpu",
    ):
        assert steps[name]["status"] == "SUCCEEDED", steps[name].get("error")
        assert steps[name]["validation"]["passed"]
        assert steps[name]["validation"]["frames"] == 6
    paired = pair_statistics(steps)
    assert len(paired) == 1 and paired[0]["validated_paired_n"] == 2, paired
    assert paired[0]["orders"] == ["AB", "BA"]
    started = [
        json.loads(line)["name"]
        for line in (root / "events.jsonl").read_text().splitlines()
        if json.loads(line)["event"] == "STARTED"
        and "fir-algorithm-r" in json.loads(line)["name"]
        and not json.loads(line)["name"].endswith("-views")
    ]
    assert started == [
        "smoke-fir-algorithm-r01-A",
        "smoke-fir-algorithm-r01-B",
        "smoke-fir-algorithm-r02-B",
        "smoke-fir-algorithm-r02-A",
    ]
    mkv = steps["smoke-ffv1-cpu"]
    assert mkv["comparison_mov"] == value["output"]
    assert mkv["validation"]["decoded_rgba_sha256"] == value["validation"]["decoded_rgba_sha256"]
    view_steps = [v for n, v in steps.items() if n.endswith("-views")]
    assert view_steps and all(v["status"] == "SUCCEEDED" for v in view_steps)
    assert steps["smoke-ffv1-cpu-views"]["alias_of"] == value["output"]
    for view_step in view_steps:
        for artifact in view_step["views"]:
            if artifact["path"].endswith(".mp4"):
                assert artifact["validation"]["passed"]
                assert artifact["validation"]["frames"] == 6
    media = Path(json.loads((root / "config.json").read_text())["media"])
    unique_streams = {
        v["validation"]["decoded_rgba_sha256"]
        for v in steps.values()
        if v.get("output") and v.get("validation", {}).get("passed")
    }
    assert len(list(media.rglob("*.mp4"))) == 3 * len(unique_streams)
    assert not list(media.rglob("comparison-PROXY.mov"))
    # Pixel oracle on real H.264 composites, not merely filter-graph assertions.
    # Native straight RGBA contains fractional alpha; compression/conversion
    # tolerance is intentionally not a lossless or visual-acceptance claim.
    import numpy as np

    def first_rgba(path: str) -> Any:
        observed = subprocess.run(
            [
                shutil.which("ffmpeg"),
                "-v",
                "error",
                "-i",
                path,
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        assert not observed.stderr
        return np.frombuffer(observed.stdout, dtype=np.uint8).reshape(280, 1400, 4)

    rgba = first_rgba(value["output"])
    assert np.any((rgba[:, :, 3] > 0) & (rgba[:, :, 3] < 255))
    yy, xx = np.indices((280, 1400))
    backgrounds = {
        "DARK": np.array([8, 16, 24]),
        "LIGHT": np.array([240, 240, 240]),
        "CHECKER": np.repeat(np.where(((xx // 16 + yy // 16) % 2)[..., None], 224, 48), 3, axis=2),
    }
    alpha = rgba[:, :, 3:4] / 255.0
    for artifact in steps["smoke-cpu-selected-views"]["views"]:
        if artifact["path"].endswith(".mp4"):
            background = backgrounds[artifact["role"].split("_")[-1]]
            expected = rgba[:, :, :3] * alpha + background * (1 - alpha)
            error = np.abs(first_rgba(artifact["path"])[:, :, :3] - expected)
            assert float(error.mean()) < 3.0, artifact["role"]
            assert float(np.quantile(error, 0.99)) < 10.0, artifact["role"]
    report = next((root / "reports").glob("report-*.md"))
    assert report.stat().st_size < 20000
    before = (root / "events.jsonl").read_bytes()
    output = Path(value["output"])
    before_time = output.stat().st_mtime_ns
    resumed = subprocess.run(
        [sys.executable, str(app.DRIVER), "--resume", str(root)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=90,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "VERIFIED_REUSED" in resumed.stdout
    assert (root / "events.jsonl").read_bytes() == before
    assert output.stat().st_mtime_ns == before_time
    # Input mutation is rejected before any replay, without changing retained media.
    config = json.loads((root / "config.json").read_text())
    with Path(config["audio"]["path"]).open("ab") as stream:
        stream.write(b"mutation")
    refused = subprocess.run(
        [sys.executable, str(app.DRIVER), "--resume", str(root)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=90,
    )
    assert refused.returncode != 0
    assert (root / "events.jsonl").read_bytes() == before
    assert output.stat().st_mtime_ns == before_time
