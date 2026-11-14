"""Storage observation is a dispatch fence, not an asserted resource breach."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_process as process
from ewp_waveform.application import portable_experiments_state as state
from ewp_waveform.application.portable_experiments_dependencies import require_process_safe
from tests.unit.test_portable_isolation_review_fixes import config_for


@pytest.mark.parametrize(
    "error,scope,resource,storage",
    [
        (process.ResourceAdmissionError("actual limit"), "GLOBAL_RESOURCE_ADMISSION", True, False),
        (process.StorageObservationError("unreadable"), "GLOBAL_STORAGE_OBSERVATION", False, True),
        (PermissionError("denied"), "GLOBAL_STORAGE_OBSERVATION", False, True),
        (FileNotFoundError("root gone"), "GLOBAL_STORAGE_OBSERVATION", False, True),
        (RuntimeError("monitor defect"), "GLOBAL_MONITOR_FAILURE", False, False),
    ],
)
def test_supervisor_distinguishes_failures_without_launch(
    tmp_path: Path, error: Exception, scope: str, resource: bool, storage: bool
) -> None:
    def monitor() -> None:
        raise error

    result = process.run_command(
        [sys.executable, "-c", "raise AssertionError('launched')"],
        tmp_path / "command",
        monitor=monitor,
    )
    assert result["shutdown_verified"]
    assert result["returncode"] is None
    assert result["failure_scope"] == scope
    assert result["resource_refused"] is resource
    assert result["storage_observation_failed"] is storage
    with pytest.raises((ValueError, RuntimeError)):
        require_process_safe(result)
    assert json.loads((tmp_path / "command/result.json").read_text()) == result


def test_active_incomplete_samples_retained_and_final_reconciled(tmp_path: Path) -> None:
    finals: list[str] = []

    def monitor() -> dict[str, Any]:
        return {"storage": {"complete": False, "incomplete_samples": [{"path": "temp.pyc"}]}}

    def final() -> dict[str, Any]:
        finals.append("reconciled")
        return {"storage": {"complete": True}}

    result = process.run_command(
        [sys.executable, "-c", "pass"], tmp_path / "command", monitor=monitor, final_monitor=final
    )
    assert result["shutdown_verified"] and not result["error"]
    assert result["returncode"] == 0
    assert len(finals) == 3  # Strict admission, shutdown and retained-result reconciliation.
    assert result["incomplete_storage_samples"] > 0
    rows = (tmp_path / "command/storage-observations.jsonl").read_text().splitlines()
    assert len(rows) == result["incomplete_storage_samples"]
    assert all(json.loads(row)["storage"]["complete"] is False for row in rows)


def test_final_observation_failure_never_returns_success(tmp_path: Path) -> None:
    samples = 0

    def final() -> None:
        nonlocal samples
        samples += 1
        if samples > 1:
            raise process.StorageObservationError("unreconciled installation")

    result = process.run_command(
        [sys.executable, "-c", "pass"], tmp_path / "command", final_monitor=final
    )
    assert result["returncode"] == 0
    assert result["storage_observation_failed"] and not result["resource_refused"]
    with pytest.raises(process.StorageObservationError):
        require_process_safe(result)


def test_optional_stage_observation_failure_is_global(tmp_path: Path, monkeypatch: Any) -> None:
    config = config_for(tmp_path)

    def fail(*args: Any) -> None:
        raise process.StorageObservationError("required root lost")

    monkeypatch.setattr(app, "check_budget", fail)
    with pytest.raises(process.StorageObservationError):
        app.invoke(config, "observe", {"operation": "never-launched"}, optional=True)
    row = json.loads((Path(config["run"]) / "events.jsonl").read_text().splitlines()[-1])
    assert row["value"]["failure_scope"] == "GLOBAL_STORAGE_OBSERVATION"
    assert not row["value"]["independent_dispatch_allowed"]
    assert not row["value"]["command"]["resource_refused"]


def test_main_report_classifies_storage_failure(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(app, "outside_git", lambda *a: None)
    monkeypatch.setattr(app, "original_inventory", lambda *a: {})

    def fail(*args: Any) -> None:
        raise process.StorageObservationError("persistent root lost, not a capacity claim")

    monkeypatch.setattr(app, "freeze", fail)
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    reports = [
        p
        for p in tmp_path.glob("run-*/reports/report-*.json")
        if not p.name.endswith(("-commands.json", "-diagnostics.json"))
    ]
    assert len(reports) == 1
    value = state.load(reports[0])
    assert value["status"] == "FAILED_STORAGE_OBSERVATION"
    assert "not a capacity claim" in value["error"]


@pytest.mark.parametrize("resource", [False, True])
def test_failed_reconciliation_retains_incomplete_samples(tmp_path: Path, resource: bool) -> None:
    error_type = process.ResourceAdmissionError if resource else process.StorageObservationError
    observations: list[dict[str, Any]] = [
        {"complete": False, "missing_observations": [{"path": "temporary.pyc"}]}
    ]

    def monitor() -> None:
        raise error_type("failed observation", storage_observations=observations)

    result = process.run_command(
        [sys.executable, "-c", "pass"], tmp_path / "command", monitor=monitor
    )
    assert result["resource_refused"] is resource
    assert result["incomplete_storage_samples"] > 0
    rows = (tmp_path / "command/storage-observations.jsonl").read_text().splitlines()
    assert all(json.loads(row)["incomplete_samples"] == observations for row in rows)
    assert state.load(tmp_path / "command/result.json") == result


def test_observed_resource_refusal_keeps_precedence_over_later_storage_failure(
    tmp_path: Path,
) -> None:
    samples = 0

    def monitor() -> None:
        nonlocal samples
        samples += 1
        if samples == 1:
            raise process.ResourceAdmissionError("real limit exceeded")
        raise process.StorageObservationError("later reconciliation I/O failure")

    result = process.run_command(
        [sys.executable, "-c", "pass"], tmp_path / "command", monitor=monitor
    )
    assert result["resource_refused"] and result["storage_observation_failed"]
    assert result["failure_scope"] == "GLOBAL_RESOURCE_ADMISSION"
    with pytest.raises(process.ResourceAdmissionError, match="later reconciliation I/O failure"):
        require_process_safe(result)
