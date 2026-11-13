"""Real six-frame production service + unchanged frozen resume, no GPU/full claims."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
