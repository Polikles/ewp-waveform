"""Real six-frame CPU work after an injected owned optional-worker failure.

The request fault is synthetic; supervision, CPU rendering and codecs are real.
This does not execute or qualify a GPU or native Windows on a Linux host.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_real_cpu_continues_after_owned_optional_request_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_invoke = app.invoke

    def injected(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        if name == "finish-qualify-numpy":
            request = {"operation": "intentional-test-only-unknown-operation"}
        return original_invoke(config, name, request, **kwargs)

    monkeypatch.setattr(app, "invoke", injected)
    code = app.main(
        [
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
    )
    assert code == 0
    (root,) = (tmp_path / "reports").glob("run-*")
    rows = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    terminal = {r["name"]: r["value"] for r in rows if "value" in r}
    failed = terminal["finish-qualify-numpy"]
    assert failed["status"] == "FAILED"
    assert failed["failure_scope"] == "OPTIONAL_SCENARIO"
    assert failed["command"]["shutdown_verified"]
    assert failed["independent_dispatch_allowed"]
    for name in ("smoke-cpu-selected", "smoke-ffv1-cpu"):
        assert terminal[name]["status"] == "SUCCEEDED"
        assert terminal[name]["validation"]["passed"]
        assert terminal[name]["validation"]["frames"] == 6
    (report,) = (
        p
        for p in (root / "reports").glob("report-*.json")
        if not p.name.endswith(("-commands.json", "-diagnostics.json"))
    )
    assert json.loads(report.read_text())["status"] == "COMPLETE_WITH_OPTIONAL_FAILURES"
    assert terminal["smoke-fir-algorithm"]["status"] == "SKIPPED"
    assert "numpy qualification FAILED" in terminal["smoke-fir-algorithm"]["reason"]
