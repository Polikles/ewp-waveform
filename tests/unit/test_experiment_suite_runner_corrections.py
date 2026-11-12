"""Synthetic regressions for independent runner findings; never execute media."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ewp_waveform.application import experiment_suite as app
from ewp_waveform.application import experiment_suite_state as state
from ewp_waveform.application.experiment_suite_models import Manifest
from ewp_waveform.application.experiments import save_new


def example() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            (
                Path(__file__).resolve().parents[2] / "examples/experiments/wsl-suite.json"
            ).read_text()
        ),
    )


def terminal(run: Path, ident: str, digest: str = "1" * 64) -> dict[str, Any]:
    value = {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "validation": {"passed": True, "decoded_rgba_sha256": digest},
        "wall_seconds": 1.0,
        "worker_wall_seconds": 1.0,
    }
    save_new(run / (ident + "-request.json"), {})
    save_new(run / (ident + "-result.json"), value)
    ledger = state.Ledger(run)
    ledger.append("STARTED", ident, request=state.artifact(run / (ident + "-request.json")))
    ledger.append("FINISHED", ident, result=state.artifact(run / (ident + "-result.json")))
    return value


@pytest.mark.parametrize("command", ["one", "batch", "resume"])
@pytest.mark.parametrize("existing_pair", [False, True])
@pytest.mark.parametrize("scenarios", [("B", "C"), ("F0", "F1")])
def test_reversed_pair_hold_stops_all_new_timed_admissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    existing_pair: bool,
    scenarios: tuple[str, str],
) -> None:
    m = example()
    m["cells"] = [
        {
            "id": "candidate",
            "scenario": scenarios[1],
            "workload": "speech",
            "pair": "p",
            "role": "candidate",
        },
        {
            "id": "control",
            "scenario": scenarios[0],
            "workload": "speech",
            "pair": "p",
            "role": "control",
        },
        {"id": "next", "scenario": "B", "workload": "speech", "pair": None, "role": None},
    ]
    s = {"manifest": m, "source": {}, "tools": {}, "build": None, "device": "unit"}
    monkeypatch.setattr(app, "lock", lambda _: nullcontext())
    monkeypatch.setattr(app, "session_at", lambda _: s)
    monkeypatch.setattr(app, "check_envelope", lambda *a, **k: {})
    monkeypatch.setattr(app, "capability_skip", lambda *a: None)
    terminal(tmp_path, "preflight")
    # Give the authenticated preflight the configuration required by dispatch.
    monkeypatch.setattr(app, "Ledger", state.Ledger)
    real_results = state.Ledger.results

    def results(self: state.Ledger) -> dict[str, dict[str, Any]]:
        values = real_results(self)
        values["preflight"]["configurations"] = {"speech": {}}
        return values

    monkeypatch.setattr(state.Ledger, "results", results)
    terminal(tmp_path, "candidate")
    if existing_pair:
        terminal(tmp_path, "control", "2" * 64)
        assert app.export_results(tmp_path)["status"] == "HOLD"
    before = state.Ledger(tmp_path).path.read_bytes()
    launched = []

    def execute(run: Path, session: Any, ident: str, request: Any, kind: str) -> dict[str, Any]:
        launched.append(ident)
        if ident.startswith("fixture-"):
            return {"status": "SUCCEEDED"}
        return terminal(run, ident, "2" * 64)

    monkeypatch.setattr(app, "execute", execute)
    target = "next" if existing_pair else "control"
    assert app.dispatch(tmp_path, command, target if command == "one" else None)["status"] == "HOLD"
    assert launched == (
        []
        if existing_pair
        else (["fixture-speech", "control"] if scenarios[0] == "F0" else ["control"])
    )
    if existing_pair:
        assert state.Ledger(tmp_path).path.read_bytes() == before
    assert "next" not in state.Ledger(tmp_path).results()


def fast_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, growth: int = 1000000, payload: int = 0
) -> tuple[Path, dict[str, Any]]:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    save_new(run / "session.json", {})
    s: dict[str, Any] = {
        "manifest": example(),
        "media_root": str(media),
        "tools": {"new": {}},
        "growth_baseline": {str(run): 0, str(media): 0},
    }
    s["manifest"]["limits"].update(growth_bytes=growth, reserve_bytes=1, memory_floor_bytes=1)
    for e in s["manifest"]["limits"]["estimates"].values():
        e.update(growth_bytes=1, memory_bytes=1)

    def resources(roots: list[Path]) -> dict[str, Any]:
        return {
            "available_memory_bytes": 10**9,
            "cgroups": {"memory.max": "max"},
            "roots": {
                str(p): {"device": 1, "free_bytes": 10**9, "tree_bytes": state.tree_bytes(p)}
                for p in roots
            },
        }

    monkeypatch.setattr(state, "resources", resources)

    class FastProcess:
        pid = 99999999
        returncode = 0

        def __init__(self, *a: Any, **k: Any) -> None:
            (media / "fast" / "unit-payload.txt").write_text("x" * payload)
            save_new(
                run / "attempts/fast/worker-result.json",
                {
                    "status": "SUCCEEDED",
                    "actual_action": "PROCESS",
                    "throughput_fresh": True,
                    "validation": {"passed": True},
                },
            )

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", FastProcess)
    monkeypatch.setattr(state, "stop_group", lambda _: None)
    return run, s


@pytest.mark.parametrize("payload,growth", [(20000, 10000), (0, 6000)])
def test_fast_exit_and_final_receipt_headroom_refuse_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: int,
    growth: int,
) -> None:
    run, s = fast_session(monkeypatch, tmp_path, payload=payload, growth=growth)
    value = state.execute(run, s, "fast", {"operation": "synthetic"}, "short")
    assert value["status"] == "FAILED" and value["throughput_fresh"] is False
    assert "growth" in value["error"]
    assert value["resource_final_status"] == "REFUSED"
    assert value["resource_final"]["observed_growth_bytes"] > 0
    assert state.Ledger(run).results()["fast"] == value
    assert state.execute(run, s, "fast", {}, "short") == value


@pytest.mark.parametrize("limit", ["memory", "reserve", "time"])
def test_fast_exit_checks_resources_after_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit: str,
) -> None:
    run, s = fast_session(monkeypatch, tmp_path)
    real_resources = state.resources

    def shutdown(_: Any) -> None:
        if limit == "time":
            s["manifest"]["limits"]["seconds"] = 0.001
        else:

            def depleted(roots: list[Path]) -> dict[str, Any]:
                snapshot = real_resources(roots)
                if limit == "memory":
                    snapshot["available_memory_bytes"] = 0
                else:
                    for v in snapshot["roots"].values():
                        v["free_bytes"] = 0
                return snapshot

            monkeypatch.setattr(state, "resources", depleted)

    monkeypatch.setattr(state, "stop_group", shutdown)
    value = state.execute(run, s, "fast", {}, "short")
    assert value["status"] == "FAILED" and value["resource_final_status"] == "REFUSED"
    assert value["throughput_fresh"] is False


def test_positive_final_resource_accounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, s = fast_session(monkeypatch, tmp_path)
    value = state.execute(run, s, "fast", {}, "short")
    assert value["status"] == "SUCCEEDED" and value["resource_final_status"] == "ADMITTED"
    growth = state.tree_bytes(run) + state.tree_bytes(Path(s["media_root"]))
    observed = value["resource_final"]["observed_growth_bytes"]
    assert observed < growth <= observed + value["final_write_allowance_bytes"]
    assert value["accounted_wall_seconds"] == value["worker_wall_seconds"] + 0.25
    assert state.Ledger(run).results()["fast"] == value


@pytest.mark.parametrize("cause", ["growth", "elapsed"])
def test_unexpected_final_write_crossing_retains_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cause: str
) -> None:
    run, s = fast_session(monkeypatch, tmp_path)
    original = save_new
    real_clock = time.monotonic
    delay = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: real_clock() + delay[0])

    def save(path: Path, value: Any) -> None:
        original(path, value)
        if path.name == "result.json":
            if cause == "growth":
                (run / "external-growth.txt").write_text("x" * 1000001)
            else:
                delay[0] = 1.0

    monkeypatch.setattr(state, "save_new", save)
    with pytest.raises(RuntimeError, match="final resource refusal"):
        state.execute(run, s, "fast", {}, "short")
    assert (run / "attempts/fast/resource-refusal.json").is_file()
    with pytest.raises(RuntimeError, match="resource refusal"):
        state.Ledger(run)


def test_complete_lifecycle_budget() -> None:
    m = example()
    m["limits"]["attempts"] = len(m["cells"]) + 2
    with pytest.raises(ValueError, match="complete frozen lifecycle"):
        Manifest.model_validate(m)
    m["limits"]["attempts"] = 64
    value = Manifest.model_validate(m)
    assert value.lifecycle_attempts() == 45
    assert value.lifecycle_attempts(old_tools=True) == 46
    m["full_views"] = True
    assert Manifest.model_validate(m).lifecycle_attempts(old_tools=True) == 47
    m["limits"]["attempts"] = 45
    m["full_views"] = False
    value = Manifest.model_validate(m)
    with pytest.raises(ValueError, match="46"):
        value.validate_attempt_budget(old_tools=True)
    m["cells"] = [
        {"id": "b", "scenario": "B", "workload": "speech"},
        {"id": "f", "scenario": "F0", "workload": "speech"},
    ]
    m["limits"]["attempts"] = 12
    assert Manifest.model_validate(m).lifecycle_attempts(old_tools=True) == 6
    w = next(w for w in m["workloads"] if w["id"] == "speech")
    m["workloads"].append({**w, "id": "speech2"})
    m["cells"].append({"id": "f2", "scenario": "F0", "workload": "speech2"})
    assert Manifest.model_validate(m).lifecycle_attempts(old_tools=True) == 9


def test_prepare_budget_rejected_before_namespaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    m = example()
    m["limits"]["attempts"] = 45
    manifest = Manifest.model_validate(m)
    monkeypatch.setattr(app, "read_manifest", lambda _: manifest)
    monkeypatch.setattr(
        app, "artifact", lambda *a: {"sha256": m["input_sha256"], "path": str(tmp_path / "audio")}
    )
    monkeypatch.setattr(app, "validate_roots", lambda roots: roots)
    monkeypatch.setattr(app, "tool", lambda p: {})
    args = argparse.Namespace(
        manifest=tmp_path / "m",
        run=tmp_path / "run",
        media_root=tmp_path / "media",
        audio=tmp_path / "audio",
        account_root=[],
        ffmpeg=Path("ffmpeg"),
        ffprobe=Path("ffprobe"),
        old_ffmpeg=Path("old/ffmpeg"),
        old_ffprobe=Path("old/ffprobe"),
    )
    with pytest.raises(ValueError, match="46"):
        app.prepare(args)
    assert not args.run.exists() and not args.media_root.exists()


def test_source_identity_json_roundtrip_and_strict_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        state,
        "source_fingerprint",
        lambda: {"imported_product_file": "/owned/repo/src/ewp_waveform/__init__.py"},
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Mock(stdout=""))
    distributions = [
        Mock(metadata={"Name": "z"}, version="2"),
        Mock(metadata={"Name": "a"}, version="1"),
    ]
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: distributions)
    current = state.source_identity()
    frozen = json.loads(json.dumps(current))
    assert current == frozen
    assert frozen["distributions"] == [["a", "1"], ["z", "2"]]
    monkeypatch.setattr(state, "verify_artifact", lambda _: None)
    session = {"source": frozen, "audio": {}, "reference_artifact": {}, "tools": {}}
    state.verify_session(session)
    distributions[0].version = "3"
    with pytest.raises(ValueError, match="identity drift"):
        state.verify_session(session)


def test_final_resource_traversal_is_inside_complete_elapsed_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, session = fast_session(monkeypatch, tmp_path)
    real_resources = state.resources
    real_clock = time.monotonic
    delay = [0.0]
    calls: list[int] = []
    monkeypatch.setattr(time, "monotonic", lambda: real_clock() + delay[0])
    session["manifest"]["limits"].update(seconds=0.5, attempt_seconds=0.5)
    session["manifest"]["limits"]["estimates"]["short"]["seconds"] = 0.01

    def delayed_resources(roots: list[Path]) -> dict[str, Any]:
        snapshot = real_resources(roots)
        calls.append(len(calls) + 1)
        if len(calls) == 3:
            delay[0] += 1.0
        return snapshot

    monkeypatch.setattr(state, "resources", delayed_resources)
    with pytest.raises(RuntimeError, match="final resource refusal"):
        state.execute(run, session, "fast", {}, "short")
    assert calls == [1, 2, 3]
    assert (run / "attempts/fast/resource-refusal.json").is_file()
    # The prior immutable result remains untouched, but cannot be read as success.
    assert json.loads((run / "attempts/fast/result.json").read_text())["status"] == "SUCCEEDED"
    with pytest.raises(RuntimeError, match="resource refusal"):
        state.Ledger(run)
