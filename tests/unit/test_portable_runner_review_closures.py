"""Regression probes for portable runner review findings; no installs or GPU work."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_reporting as reporting
from ewp_waveform.application import portable_experiments_state as state


def test_tool_selection_reads_complete_captures_not_diagnostic_tails(tmp_path: Path) -> None:
    filters = tmp_path / "filters.txt"
    filters.write_text(" hwupload\n gblur_vulkan\n" + "unrelated tail\n" * 2000)
    encoders = tmp_path / "encoders.txt"
    encoders.write_text(" prores_ks_vulkan\n ffv1_vulkan\n" + "unrelated tail\n" * 2000)
    pair = {
        "observations": {
            "filters": {"stdout": "unrelated tail", "stdout_file": state.identity(filters)},
            "encoders": {"stdout": "unrelated tail", "stdout_file": state.identity(encoders)},
        }
    }
    assert app.tool_score(pair) == 4
    filters.write_text("modified")
    with pytest.raises(ValueError, match="artifact changed"):
        app.tool_score(pair)


def test_automatic_python_setup_admitted_and_monitored(tmp_path: Path, monkeypatch: Any) -> None:
    order: list[str] = []
    monkeypatch.setattr(app, "python_candidates", lambda: [])
    monkeypatch.setattr(shutil, "which", lambda *a: "uv-not-executed")
    monkeypatch.setattr(app, "outside_git", lambda *a: None)
    monkeypatch.setattr(app, "check_budget", lambda *a: order.append("budget"))
    monkeypatch.setattr(app, "probe_python", lambda *a: {"locked": True})

    def run(argv: Any, root: Any, **kwargs: Any) -> dict[str, Any]:
        order.append("launch")
        assert kwargs["monitor"] is not None
        kwargs["monitor"]()
        return {"returncode": 0, "error": None}

    monkeypatch.setattr(app, "run_command", run)
    app.select_python(None, tmp_path, media=tmp_path, limits={})
    assert order == ["budget", "launch", "budget"]

    def refuse(*a: Any) -> None:
        raise ValueError("budget refused")

    monkeypatch.setattr(app, "check_budget", refuse)
    monkeypatch.setattr(app, "run_command", lambda *a, **k: pytest.fail("no setup after refusal"))
    with pytest.raises(ValueError, match="budget refused"):
        app.select_python(None, tmp_path, media=tmp_path, limits={})


def test_optional_matched_prores_failure_does_not_abort_independent_work(monkeypatch: Any) -> None:
    calls: list[tuple[str, Any]] = []
    skips: list[str] = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        if name == "audio-plan":
            return {"workloads": [{"id": "speech"}, {"id": "onset"}]}
        if name == "backend-qualification":
            return {"status": "SUCCEEDED", "backends": {"prores": {"status": "PASS"}}}
        if name == "finish-qualify-numpy":
            return {"status": "SUCCEEDED", "passed": True}
        if request.get("variant") == "PRORES-MATCHED":
            assert kwargs["optional"] is True
            return {"status": "FAILED", "error": "matching CPU encoder failed"}
        return {"status": "SUCCEEDED", "output": "native.mov"}

    def skip(config: Any, name: str, reason: str) -> dict[str, Any]:
        skips.append(name)
        return {"status": "SKIPPED", "reason": reason}

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "skip", skip)
    app.execute(
        {
            "selected": {"tools": {}},
            "installed": None,
            "smoke": False,
            "cuda": False,
            "preflight_only": False,
            "production32": False,
            "full": False,
        },
        {},
    )
    assert not any(r.get("variant") == "PRORES-GPU" for _, r in calls)
    assert "speech-prores-r01-B" in skips and "speech-prores-r02-B" in skips
    assert any(name == "onset-cpu-selected" for name, _ in calls)
    assert any(name == "speech-fir-algorithm-r01-B" for name, _ in calls)


@pytest.mark.parametrize(
    "new_selector", ["CUDA_NEW_TIMING_SELECTOR_TEST", "TORCHINDUCTOR_CACHE_DIR"]
)
def test_timing_environment_changes_and_added_gpu_selectors_refuse_resume(
    tmp_path: Path,
    monkeypatch: Any,
    new_selector: str,
) -> None:
    monkeypatch.delenv(new_selector, raising=False)
    monkeypatch.setattr(shutil, "which", lambda *a: None)
    monkeypatch.setattr(app, "discover_tools", lambda *a: {})
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "3")
    original = app.original_inventory(tmp_path, tmp_path)
    for name in (
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
        "CUDA_LAUNCH_BLOCKING",
    ):
        assert name in original["original_environment"]
    config = {
        "run": str(tmp_path),
        "source": {},
        "original_path": os.environ.get("PATH", ""),
        "original_environment": original["original_environment"],
    }
    state.save(tmp_path / "config.json", config)
    state.save(tmp_path / "config-seal.json", state.identity(tmp_path / "config.json"))
    monkeypatch.setattr(app, "source_identity", lambda *a: {})
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "137")
    with pytest.raises(ValueError, match="OPENBLAS_NUM_THREADS changed"):
        app.verify_config(tmp_path, tmp_path)
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "3")
    monkeypatch.setenv(new_selector, "1")
    with pytest.raises(ValueError, match="new computational environment selectors"):
        app.verify_config(tmp_path, tmp_path)


def test_invoke_checks_budget_after_terminal_evidence(tmp_path: Path, monkeypatch: Any) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    config = {
        "run": str(run),
        "media": str(media),
        "python": "not-executed",
        "limits": {"stage_timeout": 30},
        "original_path": "",
        "audio": {"path": "unused.wav"},
        "device": "RTX 3090",
        "expected_device": "RTX 3090",
        "visual_overrides": {},
    }

    def observed(argv: Any, root: Any, **kwargs: Any) -> dict[str, Any]:
        state.save(run / "steps/test/value.json", {"status": "SUCCEEDED"})
        return {
            "returncode": 0,
            "error": None,
            "stderr": "",
            "argv": argv,
            "wall_seconds": 0.1,
            "shutdown_verified": True,
        }

    def terminal_budget(*a: Any) -> None:
        rows = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        assert rows[-1]["event"] == "SUCCEEDED"
        assert rows[-1]["artifacts"]
        raise ValueError("post-evidence budget crossed")

    monkeypatch.setattr(app, "run_command", observed)
    monkeypatch.setattr(app, "check_budget", terminal_budget)
    with pytest.raises(ValueError, match="post-evidence budget crossed"):
        app.invoke(config, "test", {"operation": "test"})
    assert (run / "steps/test/value.json").is_file()


def mock_main_bootstrap(monkeypatch: Any) -> None:
    monkeypatch.setattr(app, "outside_git", lambda *a: None)
    monkeypatch.setattr(app, "original_inventory", lambda *a: {})

    def freeze(args: Any, run: Path, media: Path, original: Any) -> dict[str, Any]:
        return {
            "run": str(run),
            "media": str(media),
            "python": "not-executed",
            "source": {"sha256": "test-only"},
            "smoke": True,
            "preflight_only": False,
            "limits": {"growth_bytes": 1000000, "reserve_bytes": 1, "memory_floor_bytes": 1},
        }

    monkeypatch.setattr(app, "freeze", freeze)


def test_post_report_budget_refuses_completion_and_retains_reports(
    tmp_path: Path, monkeypatch: Any
) -> None:
    mock_main_bootstrap(monkeypatch)
    monkeypatch.setattr(app, "execute", lambda *a: {})

    def budget(run: Path, media: Path, limits: Any) -> None:
        if (run / "reports").exists():
            raise ValueError("post-report budget crossed")

    monkeypatch.setattr(app, "check_budget", budget)
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    reports = [
        json.loads(p.read_text())
        for p in tmp_path.glob("run-*/reports/report-*.json")
        if not p.name.endswith("-commands.json")
    ]
    assert {r["status"] for r in reports} == {"COMPLETE", "REFUSED_RESOURCE_LIMIT"}
    assert any("post-report budget crossed" in str(r.get("error")) for r in reports)


def test_failure_salvage_preserves_freshness_separate_from_authentication(
    tmp_path: Path, monkeypatch: Any
) -> None:
    mock_main_bootstrap(monkeypatch)
    monkeypatch.setattr(app, "check_budget", lambda *a: None)

    def failure(config: Any, done: Any) -> None:
        state.save(Path(config["run"]) / "retained.json", {"never_deleted": True})
        state.append_event(
            Path(config["run"]),
            {
                "name": "cpu",
                "event": "SUCCEEDED",
                "value": {"status": "SUCCEEDED", "actual_action": "PROCESS"},
            },
        )
        raise RuntimeError("later required stage failed")

    monkeypatch.setattr(app, "execute", failure)
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    report = next(
        p
        for p in tmp_path.glob("run-*/reports/report-*.json")
        if not p.name.endswith("-commands.json")
    )
    value = json.loads(report.read_text())
    assert value["result_use"]["cpu"] == "FRESH"
    assert value["results"]["cpu"]["evidence_status"] == "SALVAGED_UNVERIFIED"
    assert value["fresh_measurements_this_invocation"] is True


def test_main_report_explains_optional_setup_failure_without_private_path_chasing(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    config: dict[str, Any] = {
        "python": "not-executed",
        "source": {"sha256": "test-only"},
        "media": str(tmp_path / "media"),
        "smoke": True,
        "preflight_only": True,
        "cuda_error": (
            "ValueError: explicit CUDA worker requires pinned torch2.9.1+cu128; observed None"
        ),
    }
    path = reporting.report(run, "COMPLETE_WITH_OPTIONAL_FAILURES", None, config, {})
    text = path.read_text()
    assert "Optional CUDA environment/setup failed" in text
    assert config["cuda_error"] in text
    assert "no waveform rendering or throughput measurements" in text
    assert "Fresh rendered measurements" in text
    assert "requires a new campaign" in text


def test_bundle_prioritizes_complete_device_caps_and_records_omissions(tmp_path: Path) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    device = media / "backend-qualification/device"
    device.mkdir(parents=True)
    caps = {
        "before": "b" * 150000,
        "devices": [{"name": "RTX 3090", "api": "1.3"}],
        "after": "a" * 150000,
    }
    (device / "vulkan.json").write_text(json.dumps(caps))
    (device / "oversize.json").write_text(json.dumps({"oversize": "x" * (513 * 1024)}))
    (device.parent / "commands.jsonl").write_text('{"argv":["ffmpeg"]}\n')
    (device.parent / "real.stderr").write_text("actual device execution failure")
    (media / "unrelated-control.json").write_text("must not include or scan")
    (device.parent / "native.mkv").write_bytes(b"excluded binary fixture")
    for ordinal in range(80):
        (run / f"log-{ordinal:03d}.txt").write_text("x" * 40000)
    bundle = reporting.diagnostic_bundle(run, tmp_path / "return.zip", media=media)
    with zipfile.ZipFile(bundle["path"]) as archive:
        assert json.loads(archive.read("backend-qualification/device/vulkan.json")) == caps
        assert "backend-qualification/commands.jsonl" in archive.namelist()
        assert "backend-qualification/real.stderr" in archive.namelist()
        assert not any(
            name.endswith(".mkv") or "unrelated-control" in name for name in archive.namelist()
        )
        scope = json.loads(archive.read("BUNDLE-SCOPE.json"))
        assert any("512KiB" in item["reason"] for item in scope["omissions"])
        assert any("packet cap" in item["reason"] for item in scope["omissions"])
        assert (
            sum(i.file_size for i in archive.infolist())
            == bundle["uncompressed_bytes"]
            <= 2 * 1024**2
        )
