"""Final review capacity/isolation regressions; split-FS observations are simulated."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_dependencies as deps
from ewp_waveform.application import portable_experiments_state as state
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
        "smoke": True,
        "preflight_only": False,
        "source": {"sha256": "fixture"},
    }


def test_setup_growth_root_does_not_exclude_other_filesystem_reserves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, media, store = (tmp_path / n for n in ("run", "media", "store"))
    for p in (run, media, store):
        p.mkdir()
    limits = deps.setup_limits(store, 24, 1)
    observed: list[Path] = []

    class Disk:
        def __init__(self, free: int):
            self.free = free

    def disk(path: Path) -> Any:
        observed.append(Path(path))
        return Disk(100 * 1024**3 if Path(path) == store else 0)

    monkeypatch.setattr(shutil, "disk_usage", disk)
    monkeypatch.setattr(state, "resources", lambda: {"ram_available_bytes": 1024**3})
    monkeypatch.setattr(app, "python_candidates", lambda: [])
    monkeypatch.setattr(deps, "reuse_environment", lambda *a: None)
    monkeypatch.setattr(deps, "discover_environment", lambda *a: None)
    monkeypatch.setattr(app, "run_command", lambda *a, **k: pytest.fail("installer launched"))
    with pytest.raises(ResourceAdmissionError, match="disk budget"):
        app.select_python(
            None, run, media=media, limits=limits, managed_root=store, uv_path="fixture-uv"
        )
    assert set(observed) == {run, media, store}


def test_existing_campaign_overage_refuses_before_any_dependency_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    (run / "existing-metadata").write_bytes(b"x" * 8192)
    args = app.parser().parse_args(
        ["--cpu-smoke", "--cuda", "--install-cuda", "--max-growth-gib", "0.000001"]
    )
    monkeypatch.setattr(app, "choose_tools", lambda *a: (None, {"tools": {}}, None))
    monkeypatch.setattr(
        app, "dependency_policy", lambda *a: pytest.fail("preparation before campaign admission")
    )
    monkeypatch.setattr(app, "select_python", lambda *a, **k: pytest.fail("runtime installation"))
    with pytest.raises(ResourceAdmissionError, match="disk budget"):
        app.freeze(args, run, media, {})


@pytest.mark.parametrize("container", [None, {}, [None]])
def test_parseable_bad_command_container_remains_local_optional_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: Any,
) -> None:
    config = config_for(tmp_path)
    driver = tmp_path / "tiny_worker.py"
    driver.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "r=json.loads(Path(sys.argv[2]).read_text())\n"
        "failed=r['operation']=='fail'\n"
        f"container=json.loads({json.dumps(container)!r})\n"
        "value={'status':'FAILED' if failed else 'SUCCEEDED'}\n"
        "if failed: value['commands']=container\n"
        "Path(r['result_path']).write_text(json.dumps(value))\n"
        "raise SystemExit(7 if failed else 0)\n"
    )
    monkeypatch.setattr(app, "DRIVER", driver)
    monkeypatch.setattr(app, "check_budget", lambda *a: None)
    result = app.invoke(config, "failed", {"operation": "fail"}, optional=True)
    assert result["status"] == "FAILED"
    assert result["diagnostic_parse_errors"]
    assert result["independent_dispatch_allowed"]
    assert result["command"]["shutdown_verified"]
    assert (
        app.invoke(config, "independent", {"operation": "pass"}, optional=True)["status"]
        == "SUCCEEDED"
    )


@pytest.mark.parametrize("worker_fails", [False, True])
def test_post_evidence_refusal_supersedes_scope_and_preserves_metrics_in_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worker_fails: bool,
) -> None:
    config = config_for(tmp_path)
    driver = tmp_path / "tiny_worker.py"
    driver.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "r=json.loads(Path(sys.argv[2]).read_text())\n"
        f"value={{'status':{'FAILED' if worker_fails else 'SUCCEEDED'!r},"
        "'backends':{'blur':{'status':'NUMERICAL_MISMATCH', 'cases':{'64x32':"
        "{'status':'NUMERICAL_MISMATCH','numerical_oracle':{'maximum_8bit_code_error':5}}}}}}\n"
        "Path(r['result_path']).write_text(json.dumps(value))\n"
        f"raise SystemExit({7 if worker_fails else 0})\n"
    )

    def budget(*a: Any) -> None:
        events = Path(config["run"]) / "events.jsonl"
        if events.exists():
            last = json.loads(events.read_text().splitlines()[-1])
            if last["event"] in ("FAILED", "SUCCEEDED"):
                raise state.ResourceLimitError("fixture post-terminal growth crossing")

    def execute(*a: Any) -> Any:
        app.invoke(config, "backend", {"operation": "fixture"}, optional=True)
        pytest.fail("dispatch continued after refusal")

    monkeypatch.setattr(app, "DRIVER", driver)
    monkeypatch.setattr(app, "original_inventory", lambda *a: {})

    def freeze(args: Any, run: Path, media: Path, original: Any) -> dict[str, Any]:
        config.update(run=str(run), media=str(media))
        return config

    monkeypatch.setattr(app, "freeze", freeze)
    monkeypatch.setattr(app, "execute", execute)
    monkeypatch.setattr(app, "check_budget", budget)
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path / "campaigns")]) == 1
    run = Path(config["run"])
    rows = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "DISPATCH_REFUSED"
    assert rows[-1]["value"]["failure_scope"] == "GLOBAL_RESOURCE_ADMISSION"
    assert not rows[-1]["value"]["independent_dispatch_allowed"]
    assert rows[-1]["value"]["worker_status"] == ("FAILED" if worker_fails else "SUCCEEDED")
    (report,) = (run / "reports").glob("report-*.md")
    value = json.loads(report.with_suffix(".json").read_text())["results"]["backend"]
    assert not value["independent_dispatch_allowed"]
    assert (
        value["backends"]["blur"]["cases"]["64x32"]["numerical_oracle"]["maximum_8bit_code_error"]
        == 5
    )
    with pytest.raises(ValueError, match=r"retained FAILED|dispatch refusal"):
        state.completed_steps(run)
