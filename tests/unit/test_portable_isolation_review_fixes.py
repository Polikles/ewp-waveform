"""Regression coverage for independent review C-R01; real tiny supervised workers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.portable_experiments_process import ResourceAdmissionError


def config_for(tmp_path: Path) -> dict[str, Any]:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    return {
        "run": str(run),
        "media": str(media),
        "python": sys.executable,
        "audio": {"path": "not-used.wav"},
        "original_path": "",
        "device": "fixture",
        "expected_device": "fixture",
        "visual_overrides": {},
        "limits": {"stage_timeout": 5},
    }


@pytest.mark.parametrize("damaged", ["commands", "result"])
def test_owned_partial_evidence_is_terminal_local_failure_not_dispatch_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damaged: str,
) -> None:
    config = config_for(tmp_path)
    driver = tmp_path / "tiny_worker.py"
    driver.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "r=json.loads(Path(sys.argv[2]).read_text())\n"
        "failed=r['operation']=='fail'\n"
        "p=Path(r['result_path'])\n"
        "p.write_text(json.dumps({'status':'FAILED' if failed else 'SUCCEEDED'}))\n"
        "if failed:\n"
        + (
            " (Path(r['evidence'])/'commands.jsonl').write_text('{\\\"argv\\\":')\n"
            if damaged == "commands"
            else " p.write_text('{\\\"status\\\":')\n"
        )
        + "raise SystemExit(7 if failed else 0)\n"
    )
    monkeypatch.setattr(app, "DRIVER", driver)
    monkeypatch.setattr(app, "check_budget", lambda *a: None)
    failed = app.invoke(config, "failed", {"operation": "fail"}, optional=True)
    assert failed["status"] == "FAILED"
    assert failed["diagnostic_parse_errors"]
    assert failed["command"]["shutdown_verified"]
    assert failed["failure_scope"] == "OPTIONAL_SCENARIO"
    assert failed["independent_dispatch_allowed"]
    assert (
        app.invoke(config, "independent", {"operation": "pass"}, optional=True)["status"]
        == "SUCCEEDED"
    )
    rows = [
        json.loads(line) for line in (Path(config["run"]) / "events.jsonl").read_text().splitlines()
    ]
    assert [(r["name"], r["event"]) for r in rows] == [
        ("failed", "STARTED"),
        ("failed", "FAILED"),
        ("independent", "STARTED"),
        ("independent", "SUCCEEDED"),
    ]


@pytest.mark.parametrize("persistent", [False, True])
def test_resource_refusal_is_global_even_if_next_sample_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
) -> None:
    config = config_for(tmp_path)
    count = 0

    def refuse(*a: Any) -> None:
        nonlocal count
        count += 1
        if persistent or count == 1:
            raise ResourceAdmissionError("fixture capacity admission refused")

    monkeypatch.setattr(app, "check_budget", refuse)
    with pytest.raises(ResourceAdmissionError, match="no implicit recovery"):
        app.invoke(config, "resource", {"operation": "not-launched"}, optional=True)
    row = json.loads((Path(config["run"]) / "events.jsonl").read_text().splitlines()[-1])
    assert row["event"] == "FAILED"
    assert row["value"]["failure_scope"] == "GLOBAL_RESOURCE_ADMISSION"
    assert not row["value"]["independent_dispatch_allowed"]
    assert row["value"]["command"]["resource_refused"]
    assert row["value"]["command"]["returncode"] is None


@pytest.mark.parametrize("optional_numpy_passes", [False, True])
def test_optional_interpreter_numpy_is_the_actual_paired_backend_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
    optional_numpy_passes: bool,
) -> None:
    calls: list[tuple[str, Any, Any]] = []
    skips: dict[str, str] = {}

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request, kwargs))
        if name == "audio-plan":
            return {"workloads": [{"id": "speech"}, {"id": "onset"}]}
        if name == "backend-qualification":
            return {"backends": {}}
        if request["operation"] == "qualify-finish":
            if request["backend"] == "numpy":
                passed = kwargs.get("python") == "optional-python" and optional_numpy_passes
                return {
                    "status": "SUCCEEDED" if passed else "FAILED",
                    "passed": passed,
                    "error": None if passed else "fixture NumPy failed",
                }
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
            "cuda_python": "optional-python",
        },
        {},
    )
    names = {name for name, _, _ in calls}
    assert "finish-qualify-optional-numpy" in names
    for backend in ("torch-cpu", "transfer-cuda", "cuda"):
        if optional_numpy_passes:
            assert f"speech-{backend}-r01-B" in names
            assert f"onset-{backend}-screen-r01-B" in names
            paired = [(r, k) for n, r, k in calls if n.startswith(f"speech-{backend}-r")]
            assert paired and all(k["python"] == "optional-python" for _, k in paired)
        else:
            assert f"speech-{backend}-r01-B" not in names
            assert "optional-numpy qualification FAILED" in skips[f"speech-{backend}"]
            assert "fixture NumPy failed" in skips[f"onset-{backend}-screen"]
    assert "speech-fir-algorithm-r01-B" not in names


@pytest.mark.parametrize(
    "kind,status",
    [
        ("resource", "REFUSED_RESOURCE_LIMIT"),
        ("ownership", "REFUSED_PROCESS_OWNERSHIP"),
    ],
)
def test_main_preserves_global_refusal_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    status: str,
) -> None:
    from ewp_waveform.application.portable_experiments_process import ProcessOwnershipError

    monkeypatch.setattr(app, "outside_git", lambda *a: None)
    monkeypatch.setattr(app, "original_inventory", lambda *a: {})

    def freeze(*a: Any) -> Any:
        error = ResourceAdmissionError if kind == "resource" else ProcessOwnershipError
        raise error("fixture global refusal")

    monkeypatch.setattr(app, "freeze", freeze)
    monkeypatch.setattr(app, "execute", lambda *a: pytest.fail("dispatch after global refusal"))
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    reports = [
        p
        for p in tmp_path.glob("run-*/reports/report-*.json")
        if not p.name.endswith(("-commands.json", "-diagnostics.json"))
    ]
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["status"] == status
