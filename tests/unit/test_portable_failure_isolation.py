"""Scheduling fixtures: optional failures are local, ownership/resource gates are global."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app


def test_mixed_vulkan_outcomes_keep_qualified_scenarios_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    skips: dict[str, str] = {}
    qualification: dict[str, Any] = {
        "status": "FAILED",
        "attempt_failures": ["blur"],
        "backends": {
            "same_build_control": {"status": "PASS"},
            "transfer": {"status": "PASS"},
            "prores": {"status": "PASS"},
            "ffv1": {"status": "PASS"},
            "blur": {
                "status": "NUMERICAL_MISMATCH",
                "cases": {
                    "64x32": {
                        "status": "NUMERICAL_MISMATCH",
                        "explanation": "small boundary oracle mismatch",
                    },
                    "1400x280": {"status": "PASS"},
                },
            },
        },
    }

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        if name == "audio-plan":
            return {"workloads": [{"id": "speech"}]}
        if name == "backend-qualification":
            return qualification
        if request["operation"] == "qualify-finish":
            return {"status": "SUCCEEDED", "passed": True}
        return {"status": "SUCCEEDED", "output": "fixture-only.mov"}

    def skip(config: Any, name: str, reason: str) -> dict[str, Any]:
        skips[name] = reason
        return {"status": "SKIPPED", "reason": reason}

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "skip", skip)
    app.execute(
        {
            "selected": {"tools": {}},
            "installed": None,
            "smoke": False,
            "preflight_only": False,
            "production32": False,
            "full": False,
            "cuda": True,
            "cuda_environment": {"fixture": True},
            "cuda_python": "fixture-only-python",
        },
        {},
    )
    names = {name for name, _ in calls}
    for backend in ("transfer", "prores", "ffv1", "fir-algorithm", "cuda"):
        assert f"speech-{backend}-r01-B" in names
    assert not any(request.get("variant") == "BLUR" for _, request in calls)
    assert "NUMERICAL_MISMATCH" in skips["speech-blur"]
    assert "64x32" in skips["speech-blur"]
    assert "small boundary oracle mismatch" in skips["speech-blur"]
    assert qualification["backends"]["blur"]["cases"]["1400x280"]["status"] == "PASS"


def test_failed_numpy_does_not_block_independent_qualified_vulkan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(request)
        if name == "audio-plan":
            return {"workloads": [{"id": "speech"}]}
        if name == "backend-qualification":
            return {"backends": {"transfer": {"status": "PASS"}}}
        if request["operation"] == "qualify-finish":
            return {"status": "FAILED", "passed": False, "error": "fixture numerical failure"}
        return {"status": "SUCCEEDED", "output": "fixture-only.mov"}

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "skip", lambda *a: {"status": "SKIPPED"})
    app.execute(
        {
            "selected": {"tools": {}},
            "installed": None,
            "smoke": False,
            "preflight_only": False,
            "production32": False,
            "full": False,
            "cuda": False,
        },
        {},
    )
    assert any(r.get("variant") == "TRANSFER" for r in calls)
    assert not any(r.get("backend") == "numpy" and r.get("pair") for r in calls)


def test_failed_same_build_control_has_explicit_global_tool_reason() -> None:
    qualification = {
        "backends": {
            "same_build_control": {"status": "EXECUTION_ERROR", "explanation": "versions differ"},
            "transfer": {"status": "PASS"},
        }
    }
    assert not app.backend_passed(qualification, "transfer")
    reason = app.backend_failure_reason(qualification, "transfer")
    assert "same_build_control" in reason and "versions differ" in reason


@pytest.mark.parametrize("owned", [False, True])
def test_optional_failure_scope_requires_verified_process_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned: bool,
) -> None:
    from ewp_waveform.application import portable_experiments_state as state

    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    config: dict[str, Any] = {
        "run": str(run),
        "media": str(media),
        "python": "fixture-not-executed",
        "audio": {"path": "fixture.wav"},
        "original_path": "",
        "device": "fixture",
        "expected_device": "fixture",
        "visual_overrides": {},
        "limits": {"stage_timeout": 10},
    }

    def command(argv: Any, folder: Any, **kwargs: Any) -> dict[str, Any]:
        state.save(run / "steps/optional/value.json", {"status": "FAILED", "error": "local"})
        return {
            "returncode": 1,
            "error": None,
            "stderr": "local",
            "argv": argv,
            "wall_seconds": 0.1,
            "shutdown_verified": owned,
        }

    monkeypatch.setattr(app, "run_command", command)
    monkeypatch.setattr(app, "check_budget", lambda *a: None)
    if owned:
        result = app.invoke(config, "optional", {"operation": "fixture"}, optional=True)
        assert result["failure_scope"] == "OPTIONAL_SCENARIO"
        assert result["independent_dispatch_allowed"]
    else:
        with pytest.raises(RuntimeError, match="ownership shutdown UNVERIFIED"):
            app.invoke(config, "optional", {"operation": "fixture"}, optional=True)
        import json

        result = json.loads((run / "events.jsonl").read_text().splitlines()[-1])["value"]
        assert result["failure_scope"] == "GLOBAL_PROCESS_OWNERSHIP"
        assert not result["independent_dispatch_allowed"]
