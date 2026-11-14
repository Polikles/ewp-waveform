from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application.portable_experiments_metrics import compact_metrics
from ewp_waveform.application.portable_experiments_reporting import diagnostic_bundle
from ewp_waveform.application.portable_optimization_extras import extras


def test_extra_cuda_pairs_are_one_variable_and_counterbalanced() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    def step(name: str, req: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert kwargs["optional"] is True
        assert kwargs["python"] == "selected-cuda-python"
        seen.append((name, req))
        return {"status": "SUCCEEDED", "passed": True}

    cfg = {
        "repeats": 2,
        "cuda": True,
        "cuda_environment": {"valid": True},
        "cuda_python": "selected-cuda-python",
    }
    extras(cfg, [{"id": "speech", "frames": 240}], step, lambda *_: pytest.fail("unexpected skip"))
    rows = [(n, r) for n, r in seen if r["operation"] == "cuda"]
    assert len(rows) == 20
    for i in range(0, len(rows), 4):
        group = rows[i : i + 4]
        assert [r["pair"]["side"] for _, r in group] == list("ABBA")
        a, b = group[0][1], group[1][1]
        changed = {k for k in a.keys() | b.keys() if k != "pair" and a.get(k) != b.get(k)}
        assert len(changed) == 1
        assert changed <= {"output_mode", "batch_size", "timing_mode"}


def test_failed_cuda_gate_does_not_launch_its_pairs_or_suppress_compact() -> None:
    seen: list[dict[str, Any]] = []
    skipped: list[str] = []

    def step(name: str, req: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        seen.append(req)
        return {"status": "FAILED", "passed": False}

    cfg = {
        "repeats": 2,
        "cuda": True,
        "cuda_environment": {"valid": True},
        "cuda_python": "selected-cuda-python",
        "optimization": {"compact": True},
    }
    extras(cfg, [{"id": "speech", "frames": 240}], step, lambda n, _: skipped.append(n))
    assert len([r for r in seen if r["operation"] == "compact"]) == 8
    assert not [r for r in seen if r["operation"] == "cuda"]
    assert len(skipped) == 5


def test_no_cuda_preparation_is_an_explicit_skip() -> None:
    skipped: list[str] = []
    extras(
        {"repeats": 2, "cuda": True},
        [{"id": "smoke"}],
        lambda *_: pytest.fail("worker not admitted"),
        lambda n, _: skipped.append(n),
    )
    assert skipped == ["opt-fir-output"]


def test_critical_phase_aggregates_precede_packet_omissions(tmp_path: Path) -> None:
    raw = {
        "gpu": {
            "worker": {
                "calls": [
                    {
                        "upload_bytes": 1140000,
                        "download_bytes": 392000,
                        "compute_wall_seconds": i / 1000,
                        "event_seconds": None,
                        "live_frames": 1,
                    }
                    for i in range(240)
                ]
            },
            "wall_seconds": 4.2,
            "commands": ["x" * 3000000],
        }
    }
    metrics = compact_metrics(raw)
    calls = metrics["gpu"]["worker"]["calls"]
    assert calls["sample_count"] == 240
    assert calls["numeric_fields"]["download_bytes"]["sum"] == 240 * 392000
    assert calls["numeric_fields"]["live_frames"]["sum"] == 240
    assert calls["constant_fields"]["event_seconds"] is None
    assert "commands" not in metrics["gpu"]
    run = tmp_path / "run"
    reports = run / "reports"
    reports.mkdir(parents=True)
    (reports / "report-abc-diagnostics.json").write_text(json.dumps(raw))
    (reports / "measurements-abc.json").write_text(json.dumps(metrics))
    packet = tmp_path / "diagnostics.zip"
    diagnostic_bundle(run, packet)
    with zipfile.ZipFile(packet) as z:
        assert json.loads(z.read("reports/measurements-abc.json")) == metrics


def test_oversize_critical_measurements_refuse_explicitly(tmp_path: Path) -> None:
    run = tmp_path / "run"
    reports = run / "reports"
    reports.mkdir(parents=True)
    (reports / "report-abc-diagnostics.json").write_text("{}")
    (reports / "measurements-abc.json").write_text("x" * (2 * 1024**2 + 1))
    with pytest.raises(ValueError, match="critical measurements exceed"):
        diagnostic_bundle(run, tmp_path / "not-created.zip")
