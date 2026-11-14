"""Bounded retained dependency admission; no downloads, installs or GPU work."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_dependencies as deps
from ewp_waveform.application import portable_experiments_process as process
from ewp_waveform.application import portable_experiments_state as state


def candidate(store: Path, request: str = "old-key", attempt: str = "attempt") -> Path:
    python = (
        store
        / "attempts"
        / request
        / attempt
        / "env"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture interpreter; never executed")
    return python


def environment(python: Path) -> dict[str, Any]:
    return {"binary": state.identity(python), "version": "3.12 fixture", "locked_runtime": {}}


def events(run: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (run / "runtime-reuse-selection.jsonl").read_text().splitlines()
    ]


@pytest.mark.parametrize("change", ["pyproject.toml", "uv.lock"])
def test_recipe_change_recovers_prior_registry_pointer_without_trusting_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root, store, run = tmp_path / "source", tmp_path / "managed", tmp_path / "run-new"
    root.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (root / name).write_text("old recipe")
    python = tmp_path / "retained-python"
    python.write_bytes(b"retained bytes")
    registered = deps.register_environment(store, root, "runtime", python, environment(python))
    old_receipt = Path(registered["receipt"]["path"])
    # An old receipt is only a pointer. Its assertions cannot admit an environment.
    old = state.load(old_receipt)
    old["environment"] = {"untrusted": True}
    old["key_sha256"] = "untrusted old key"
    old_receipt.write_text(json.dumps(old))
    before = old_receipt.read_bytes()
    (root / change).write_text("new recipe; same runtime dependencies")
    calls: list[tuple[str, Path]] = []

    def native(p: Path, folder: Path) -> dict[str, Any]:
        calls.append(("native", p))
        folder.mkdir(parents=True)
        return {}

    monkeypatch.setattr(deps, "interpreter_probe", native)

    def probe(python: Path, folder: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append(("runtime", python))
        # Real run_command refuses an already-used evidence directory. Native
        # and payload probes must be siblings, never nested in the same folder.
        assert not folder.exists()
        folder.mkdir(parents=True)
        assert kwargs == {"optional": False}
        return environment(python)

    selected = deps.prepared_environment(store, root, "runtime", run, probe)
    assert selected is not None and selected[0] == python
    assert calls == [("native", python), ("runtime", python)]
    new = state.load(Path(selected[2]["receipt"]["path"]))
    assert new["key"]["request"] == deps.request_key(root, "runtime")
    assert new["environment"] == environment(python)
    assert old_receipt.read_bytes() == before
    assert [e["status"] for e in events(run)] == ["EXACT_KEY_MISS", "SEARCH", "SELECTED"]
    assert "locks" in events(run)[-1]["request_differences"]


def test_old_attempt_without_receipt_is_recovered_and_backend_is_reprobed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run = tmp_path / "managed", tmp_path / "run-new"
    python = candidate(store)
    before = python.read_bytes()
    checked: list[Path] = []
    monkeypatch.setattr(deps, "interpreter_probe", lambda p, e: checked.append(p))

    def probe(p: Path, e: Path, *, optional: bool) -> dict[str, Any]:
        assert optional
        return environment(p)

    result = deps.discover_environment(store, app.ROOT, "cu128", run, probe)
    assert result is not None and result[0] == python and checked == [python]
    assert result[2]["key"]["request"]["backend"] == "cu128"
    assert python.read_bytes() == before


@pytest.mark.parametrize(
    "failure",
    ["native platform mismatch", "locked runtime dependency mismatch", "RECORD hash changed"],
)
def test_incompatible_cross_recipe_candidate_is_not_registered_or_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store, run = tmp_path / "managed", tmp_path / "run-new"
    python = candidate(store)
    before = python.read_bytes()
    monkeypatch.setattr(deps, "interpreter_probe", lambda *a: {})

    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError(failure)

    if failure == "native platform mismatch":
        monkeypatch.setattr(deps, "interpreter_probe", refuse)
    assert deps.discover_environment(store, app.ROOT, "runtime", run, refuse) is None
    assert not (store / "verified").exists()
    assert python.read_bytes() == before
    assert events(run)[1]["status"] == "INVALIDATED"
    assert events(run)[1]["error"] == failure


@pytest.mark.parametrize(
    "error",
    [
        process.ResourceAdmissionError,
        process.StorageObservationError,
        process.ProcessOwnershipError,
        process.MonitorFailureError,
    ],
)
def test_discovery_does_not_convert_global_failures_to_optional_candidate_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    store = tmp_path / "managed"
    candidate(store, deps.digest(deps.request_key(app.ROOT, "runtime")))

    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise error("global failure")

    with pytest.raises(error, match="global failure"):
        deps.discover_environment(store, app.ROOT, "runtime", tmp_path / "run-new", refuse)
    assert not (store / "verified").exists()


@pytest.mark.parametrize(
    ("flag", "error"),
    [
        ("resource_refused", process.ResourceAdmissionError),
        ("storage_observation_failed", process.StorageObservationError),
        ("monitor_failed", process.MonitorFailureError),
    ],
)
def test_process_global_flags_propagate(flag: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        deps.require_process_safe({"shutdown_verified": True, flag: True, "error": "diagnostic"})


def test_discovery_verification_is_bounded_and_leaves_unprobed_payloads_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run = tmp_path / "managed", tmp_path / "run-new"
    paths = [candidate(store, attempt=str(i)) for i in range(10)]
    checks: list[Path] = []
    monkeypatch.setattr(deps, "interpreter_probe", lambda *a: {})

    def refuse(p: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
        checks.append(p)
        raise ValueError("incompatible closure")

    assert deps.discover_environment(store, app.ROOT, "runtime", run, refuse) is None
    assert len(checks) == 8 and len(set(checks)) == 8
    assert events(run)[-1]["unprobed"] == 2
    assert all(p.read_bytes() == b"fixture interpreter; never executed" for p in paths)
    with pytest.raises(ValueError, match="search bound exceeded"):
        deps.bounded_paths(iter(paths), bound=3)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("implementation", "pypy"),
        ("version", [3, 14]),
        ("platform", "other-os"),
        ("machine", "other-machine"),
        ("bits", 32),
    ],
)
def test_native_interpreter_probe_refuses_wrong_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    def run(argv: list[str], folder: Path, **kwargs: Any) -> dict[str, Any]:
        assert argv[1:4] == ["-I", "-B", "-c"] and kwargs["timeout"] == 20
        folder.mkdir()
        payload = {
            "implementation": "cpython",
            "version": [3, 12],
            "platform": sys.platform,
            "machine": platform.machine().lower(),
            "bits": 64,
            field: value,
        }
        (folder / "stdout.txt").write_text(json.dumps(payload))
        return {"returncode": 0, "error": None, "shutdown_verified": True}

    monkeypatch.setattr(process, "run_command", run)
    with pytest.raises(ValueError, match="identity mismatch"):
        deps.interpreter_probe(Path("fixture-python"), tmp_path / "probe")


def test_retained_managed_python_lookup_is_offline_and_never_a_project_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run = tmp_path / "managed", tmp_path / "run-new"
    python = store / "python" / "retained" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture interpreter")
    checked: list[Path] = []
    monkeypatch.setattr(deps, "interpreter_probe", lambda p, e: checked.append(p))

    def execute(argv: list[str], folder: Path, **kwargs: Any) -> dict[str, Any]:
        assert argv[1:4] == ["python", "find", "3.12"]
        assert {
            "--offline",
            "--no-project",
            "--no-config",
            "--managed-python",
            "--no-python-downloads",
        } <= set(argv)
        assert kwargs["env"]["UV_PYTHON_DOWNLOADS"] == "never"
        folder.mkdir(parents=True)
        (folder / "stdout.txt").write_text(str(python) + "\n")
        return {"returncode": 0, "error": None, "shutdown_verified": True}

    monkeypatch.setattr(process, "run_command", execute)
    assert deps.retained_managed_python("fixture-uv", store, run, {}) == python
    assert checked == [python]
    assert events(run)[-1]["status"] == "RETAINED_INTERPRETER_SELECTED"


def test_live_install_samples_are_retained_and_final_policy_is_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = {"growth_bytes": 100, "allow_transient_disappearance": True}
    policies: list[bool] = []

    def check(run: Path, media: Path, policy: dict[str, Any]) -> dict[str, Any]:
        policies.append(policy["allow_transient_disappearance"])
        return {
            "storage": {
                "complete": not policy["allow_transient_disappearance"],
                "transient_disappearances": [{"path": "python/.temp"}],
            }
        }

    monkeypatch.setattr(deps, "check_budget", check)
    live, final = deps.installation_monitors(tmp_path, tmp_path, limits, tmp_path / "samples")
    assert live()["storage"]["complete"] is False
    assert final()["storage"]["complete"] is True
    assert policies == [True, False] and limits["allow_transient_disappearance"] is True
    samples = [
        json.loads(line)
        for line in (tmp_path / "samples/storage-samples.jsonl").read_text().splitlines()
    ]
    assert [item["phase"] for item in samples] == ["LIVE_INSTALL", "FINAL_STRICT"]
    assert samples[0]["observation"]["storage"]["transient_disappearances"]


def test_monitor_errors_are_retained_and_reraised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any) -> dict[str, Any]:
        raise process.StorageObservationError("unresolved final accounting")

    monkeypatch.setattr(deps, "check_budget", refuse)
    _, final = deps.installation_monitors(tmp_path, tmp_path, {}, tmp_path / "samples")
    with pytest.raises(process.StorageObservationError):
        final()
    sample = json.loads((tmp_path / "samples/storage-samples.jsonl").read_text())
    assert sample["phase"] == "FINAL_STRICT" and sample["error_type"] == "StorageObservationError"


@pytest.mark.parametrize("final_refusal", [False, True])
def test_runtime_install_uses_retained_python_and_strict_reconciliation_before_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_refusal: bool
) -> None:
    retained = tmp_path / "managed/python/retained/python"
    registered: list[str] = []
    calls: list[bool] = []
    monkeypatch.setattr(app, "python_candidates", lambda: [])
    monkeypatch.setattr(deps, "reuse_environment", lambda *a: None)
    monkeypatch.setattr(deps, "discover_environment", lambda *a: None)
    monkeypatch.setattr(deps, "retained_managed_python", lambda *a: retained)
    monkeypatch.setattr(deps, "admit_setup", lambda *a: {})
    monkeypatch.setattr(app, "probe_python", lambda *a: {"locked": True})
    monkeypatch.setattr(app, "check_budget", lambda *a: {})

    def register(*args: Any) -> dict[str, Any]:
        registered.append("registered")
        return {}

    monkeypatch.setattr(deps, "register_environment", register)

    def check(run: Path, media: Path, policy: dict[str, Any]) -> dict[str, Any]:
        calls.append(policy["allow_transient_disappearance"])
        if final_refusal and not policy["allow_transient_disappearance"]:
            raise process.StorageObservationError("final incomplete")
        return {"storage": {"complete": True}}

    monkeypatch.setattr(deps, "check_budget", check)

    def execute(argv: list[str], folder: Path, **kwargs: Any) -> dict[str, Any]:
        assert argv[argv.index("--python") + 1] == str(retained)
        assert kwargs["env"]["UV_PYTHON_DOWNLOADS"] == "never"
        kwargs["monitor"]()
        kwargs["final_monitor"]()
        return {"returncode": 0, "error": None, "shutdown_verified": True}

    monkeypatch.setattr(app, "run_command", execute)
    kwargs: dict[str, Any] = dict(
        media=tmp_path / "media", limits={}, managed_root=tmp_path / "managed", uv_path="fixture-uv"
    )
    if final_refusal:
        with pytest.raises(process.StorageObservationError, match="final incomplete"):
            app.select_python(None, tmp_path / "run-new", **kwargs)
        assert not registered
    else:
        app.select_python(None, tmp_path / "run-new", **kwargs)
        assert calls == [True, False, False] and registered == ["registered"]
