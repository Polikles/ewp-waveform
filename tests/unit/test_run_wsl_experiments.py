"""Focused stdlib startup/authority tests; no target media or host setup execution."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_wsl_experiments.py"
spec = importlib.util.spec_from_file_location("wsl_driver", SCRIPT)
assert spec and spec.loader
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def template() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((SCRIPT.parents[1] / "examples/experiments/wsl-suite.json").read_text()),
    )


def tools(tmp_path: Path, name: str) -> dict[str, Any]:
    directory = tmp_path / name
    directory.mkdir()
    for tool in ("ffmpeg", "ffprobe"):
        path = directory / tool
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    pair = driver.tool_pair(directory)
    assert pair
    return cast(dict[str, Any], pair)


def observed(pair: dict[str, Any], *, gpu: bool = False) -> dict[str, Any]:
    return {
        "tools": pair,
        "observations": {
            "-filters": {"stdout": "hwupload gblur_vulkan" if gpu else ""},
            "-encoders": {"stdout": "prores_ks_vulkan ffv1_vulkan" if gpu else ""},
            "-hwaccels": {"stdout": "vulkan" if gpu else ""},
        },
        "libraries": {},
    }


def test_manifest_keeps_whole_default_scenario_set_and_production32() -> None:
    original = template()
    reference = driver.manifest_for(original, "reference")
    experiments = driver.manifest_for(original, "experiments")
    assert [c["scenario"] for c in reference["cells"]] == ["FULL"]
    assert experiments["cells"] == [c for c in original["cells"] if c["scenario"] != "FULL"]
    assert {c["scenario"] for c in experiments["cells"]} == {
        "PRODUCTION32",
        "A",
        "B",
        "C",
        "D",
        "E0",
        "E1",
        "F0",
        "F1",
    }
    assert original == template()  # no mutation of shared template
    assert {w["id"] for w in experiments["workloads"]} == {"production32", "speech"}


def test_smoke_is_explicit_tiny_cpu_not_reference(tmp_path: Path) -> None:
    audio = tmp_path / "tiny.wav"
    driver.create_smoke_audio(audio)
    manifest = driver.smoke_manifest(template(), audio)
    assert manifest["input_sha256"] == driver.digest(audio)
    assert manifest["source_duration_seconds"] == 0.1
    assert manifest["workloads"][0]["frames"] == 6
    assert [c["scenario"] for c in manifest["cells"]] == ["B", "F0"]
    assert manifest["limits"]["reserve_bytes"] == template()["limits"]["reserve_bytes"]
    from ewp_waveform.application.experiment_suite_models import Manifest

    Manifest.model_validate(manifest)


def test_tool_selection_distinguishes_original_and_selected(tmp_path: Path) -> None:
    cpu, gpu = tools(tmp_path, "original"), tools(tmp_path, "gpu")
    initial = {
        "installed_pairs": [observed(cpu), observed(gpu, gpu=True)],
        "first_path_tools": {k: v["path"] for k, v in cpu.items()},
    }
    baseline, selected = driver.select_tools(initial, None, None)
    assert baseline == cpu
    assert selected["tools"] == gpu
    assert "receipt" not in selected  # no fabricated pinned-build provenance


def test_explicit_pair_does_not_change_original_baseline(tmp_path: Path) -> None:
    cpu, gpu = tools(tmp_path, "original"), tools(tmp_path, "gpu")
    initial = {
        "installed_pairs": [observed(cpu), observed(gpu)],
        "first_path_tools": {k: v["path"] for k, v in cpu.items()},
    }
    baseline, selected = driver.select_tools(
        initial, Path(gpu["ffmpeg"]["path"]), Path(gpu["ffprobe"]["path"])
    )
    assert baseline == cpu and selected["tools"] == gpu
    with pytest.raises(ValueError, match="together"):
        driver.select_tools(initial, Path(gpu["ffmpeg"]["path"]), None)


def test_split_original_path_pair_skips_baseline_not_selected(tmp_path: Path) -> None:
    a, b = tools(tmp_path, "a"), tools(tmp_path, "b")
    initial = {
        "installed_pairs": [observed(a), observed(b)],
        "first_path_tools": {"ffmpeg": a["ffmpeg"]["path"], "ffprobe": b["ffprobe"]["path"]},
    }
    baseline, selected = driver.select_tools(initial, None, None)
    assert baseline is None and selected["tools"] == a
    assert "CPU FULL baseline NOT_RUN" in driver.baseline_skip_reason(None)


def test_roots_outside_git_disjoint_and_not_source_ancestors(tmp_path: Path) -> None:
    driver.outside_git([tmp_path / "evidence", tmp_path / "media"])
    with pytest.raises(ValueError, match="disjoint"):
        driver.outside_git([tmp_path / "a", tmp_path / "a/b"])
    with pytest.raises(ValueError, match="duplicate"):
        driver.outside_git([tmp_path / "a", tmp_path / "a"])
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /elsewhere")  # linked worktree is still Git
    with pytest.raises(ValueError, match="outside Git"):
        driver.outside_git([repo / "child"])
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError, match="outside Git"):
        driver.outside_git([alias / "child"])
    with pytest.raises(ValueError, match="source audio"):
        driver.outside_git([tmp_path / "audio-parent"], tmp_path / "audio-parent/source.wav")


def test_dirty_source_rejected_before_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    def dirty(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 0, stdout=" M scripts/run_wsl_experiments.py\n")

    monkeypatch.setattr(driver.subprocess, "run", dirty)
    with pytest.raises(ValueError, match="commit candidate first"):
        driver.source_identity()


def test_environment_explicit_failure_never_runs_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args: Any) -> Any:
        raise ValueError("wrong Python")

    monkeypatch.setattr(driver, "probe_python", missing)
    monkeypatch.setattr(driver.shutil, "which", lambda _: pytest.fail("must not find uv"))
    with pytest.raises(ValueError, match="wrong Python"):
        driver.select_python(tmp_path / "python", tmp_path)


def test_automatic_environment_uses_frozen_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Any]] = []

    def probe(path: Path) -> dict[str, str]:
        calls.append(("probe", str(path)))
        if len(calls) == 1:
            raise ValueError("no environment")
        return {"version": "3.12"}

    def sync(argv: list[str], **kwargs: Any) -> dict[str, Any]:
        calls.append(("sync", argv))
        return {"returncode": 0}

    monkeypatch.setattr(driver, "probe_python", probe)
    monkeypatch.setattr(driver, "observe", sync)
    monkeypatch.setattr(driver.shutil, "which", lambda _: "/existing/uv")
    selected, metadata = driver.select_python(None, tmp_path)
    assert selected == driver.ROOT / ".venv/bin/python"
    assert metadata["version"] == "3.12"
    assert calls[1][1] == [
        "/existing/uv",
        "sync",
        "--frozen",
        "--python",
        "3.12",
        "--project",
        str(driver.ROOT),
    ]
    assert (tmp_path / "uv-sync.json").is_file()


def add_started(run: Path, name: str) -> Path:
    request = run / (name + "-request.json")
    driver.save(request, {"example": name})
    driver.append_event(
        run, {"event": "STARTED", "name": name, "request": driver.identity(request)}
    )
    return request


def test_resume_started_and_failed_are_never_retried(tmp_path: Path) -> None:
    request = add_started(tmp_path, "preflight")
    with pytest.raises(ValueError, match="uncertain STARTED"):
        driver.completed_steps(tmp_path)
    driver.append_event(
        tmp_path,
        {
            "event": "FAILED",
            "name": "preflight",
            "artifacts": [driver.identity(request)],
            "value": {},
        },
    )
    with pytest.raises(ValueError, match="retained FAILED"):
        driver.completed_steps(tmp_path)


def test_resume_verifies_recorded_artifacts_and_chain(tmp_path: Path) -> None:
    request = add_started(tmp_path, "batch")
    driver.append_event(
        tmp_path,
        {
            "event": "SUCCEEDED",
            "name": "batch",
            "artifacts": [driver.identity(request)],
            "value": {"a": 1},
        },
    )
    assert driver.completed_steps(tmp_path) == {"batch": {"a": 1}}
    request.write_text("tampered")
    with pytest.raises(ValueError, match="frozen artifact changed"):
        driver.completed_steps(tmp_path)


def test_full_reference_common_path_then_selected_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = []
    config: dict[str, Any] = {
        "python": "/python",
        "suites": {"reference": {"run": "/reference"}, "experiments": {"run": "/experiments"}},
    }

    def invoke(python: Path, run: Path, name: str, request: dict[str, Any], **kwargs: Any) -> Any:
        calls.append((name, request))
        return {"status": kwargs["accepted"][0]}

    monkeypatch.setattr(driver, "invoke", invoke)
    monkeypatch.setattr(
        driver, "prepare_request", lambda c, name: {"operation": "prepare", "name": name}
    )
    driver.execute_suites(config, tmp_path, {})
    assert [name for name, _ in calls] == [
        f"{suite}-{op}"
        for suite in ("reference", "experiments")
        for op in ("prepare", "preflight", "batch", "views", "export")
    ]
    assert calls[2][1] == {"operation": "batch", "run": "/reference"}
    calls.clear()
    config["suites"] = dict(reversed(list(config["suites"].items())))
    driver.execute_suites(config, tmp_path, {})
    assert calls[0][0] == "reference-prepare"  # sorted JSON must not change execution order


def test_completed_steps_not_reexecuted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = {"python": "/python", "suites": {"reference": {"run": "/reference"}}}
    done = {
        f"reference-{op}": {"status": "TECHNICAL_COMPLETE"}
        for op in ("prepare", "preflight", "batch", "views", "export")
    }
    monkeypatch.setattr(driver, "prepare_request", lambda *args: {})
    monkeypatch.setattr(driver, "invoke", lambda *args, **kwargs: pytest.fail("no repeated media"))
    assert (
        driver.execute_suites(config, tmp_path, done)["reference"]["status"] == "TECHNICAL_COMPLETE"
    )


def test_preflight_failure_always_has_report_and_suite_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    order = []
    suite_run = tmp_path / "suite"
    suite_run.mkdir()
    (suite_run / "session.json").write_text("{}")
    config = {
        "mode": "reference-only",
        "python": sys.executable,
        "source": {"commit": "a" * 40},
        "environment": {},
        "baseline_tools": {},
        "selected_tools": {},
        "suites": {"reference": {"run": str(suite_run)}},
    }

    def inventory() -> dict[str, Any]:
        order.append("inventory")
        return {"original_path": os.environ.get("PATH")}

    def freeze(args: Any, run: Path, initial: Any, token: str) -> dict[str, Any]:
        order.append("setup")
        saved = driver.load(run / "initial-inventory.json")
        assert saved["storage"]["requested_output_root"]["requested_path"] == str(tmp_path)
        assert run.stat().st_mode & 0o777 == 0o700
        return config

    def fail(*args: Any) -> Any:
        raise ValueError("actual preflight failed")

    monkeypatch.setattr(driver, "initial_inventory", inventory)
    monkeypatch.setattr(driver, "freeze_new", freeze)
    monkeypatch.setattr(driver, "execute_suites", fail)
    monkeypatch.setattr(
        driver,
        "invoke",
        lambda *a, **k: {
            "status": "HOLD",
            "report": "/retained/suite/report.md",
            "json": "/retained/result.json",
        },
    )
    assert driver.main(["--audio", "/source.wav", "--output-root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "planned_absolute_directories" in captured.err
    assert "reference_suite" in captured.err and "reference_media" in captured.err
    result = json.loads(captured.out)
    text = Path(result["report"]).read_text()
    assert "actual preflight failed" in text and "/retained/suite/report.md" in text
    assert order == ["inventory", "setup"]
    assert (Path(result["run"]) / "initial-inventory.json").is_file()


def test_hash_failure_happens_before_environment_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    source = tmp_path / "wrong.wav"
    source.write_bytes(b"not the reference")
    args = driver.parser().parse_args(["--audio", str(source)])
    monkeypatch.setattr(driver, "source_identity", lambda: {})
    monkeypatch.setattr(
        driver, "select_python", lambda *a: pytest.fail("setup before hash verification")
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        driver.freeze_new(args, run, {}, "token")


def test_stdlib_help_works_without_package_or_site(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--reference-only" in proc.stdout and "--cpu-smoke" in proc.stdout
    assert "--resume" in proc.stdout and "--build-ffmpeg" in proc.stdout


def test_report_is_numbered_and_never_claims_visual_acceptance(tmp_path: Path) -> None:
    driver.save(tmp_path / "initial-inventory.json", {})
    first = driver.report(tmp_path, "HOLD", "missing uv", None, {})
    saved = first.read_bytes()
    second = driver.report(tmp_path, "HOLD", "still missing", None, {})
    assert first != second and first.read_bytes() == saved
    assert "PENDING" in saved.decode() and "NOT_APPROVED" in saved.decode()


def frozen_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    run = tmp_path / "metadata/run"
    run.mkdir(parents=True)
    pair = tools(tmp_path, "installed")
    initial = {
        "installed_pairs": [observed(pair)],
        "first_path_tools": {k: v["path"] for k, v in pair.items()},
    }
    driver.save(run / "initial-inventory.json", initial)
    monkeypatch.setattr(driver, "source_identity", lambda: {"commit": "a" * 40})
    monkeypatch.setattr(
        driver, "select_python", lambda *args: (Path(sys.executable), {"test": True})
    )
    monkeypatch.setattr(driver, "probe_python", lambda *args: {"test": True})
    args = driver.parser().parse_args(["--cpu-smoke", "--media-parent", str(tmp_path / "bulky")])
    return run, driver.freeze_new(args, run, initial, "token")


def test_freeze_supports_separate_media_parent_and_explicit_observed_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, config = frozen_smoke(tmp_path, monkeypatch)
    suite = config["suites"]["smoke"]
    assert Path(suite["run"]).parent == run.parent
    assert Path(suite["media"]).parent == tmp_path / "bulky"
    request = driver.prepare_request(config, "smoke")["args"]
    assert request["installed_provenance"] == str(run / "selected-tools.json")
    assert request["build_receipt"] is None
    inventory = json.loads(Path(request["installed_provenance"]).read_text())
    assert inventory["tools"] == config["selected_tools"]
    assert all(t["role"] == "TOOL" for t in inventory["tools"].values())
    driver.verify(driver.load(run / "driver-seal.json"))


def test_resume_verifies_driver_and_tools_before_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, config = frozen_smoke(tmp_path, monkeypatch)
    monkeypatch.setattr(driver, "probe_python", lambda *args: {"test": True})
    assert driver.verify_config(run) == config
    Path(config["selected_tools"]["ffmpeg"]["path"]).write_text("changed")
    with pytest.raises(ValueError, match="frozen artifact changed"):
        driver.verify_config(run)


def test_resume_source_and_driver_drift_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _config = frozen_smoke(tmp_path, monkeypatch)
    monkeypatch.setattr(driver, "source_identity", lambda: {"commit": "b" * 40})
    monkeypatch.setattr(
        driver, "probe_python", lambda *args: pytest.fail("source drift must stop first")
    )
    with pytest.raises(ValueError, match="source/driver identity drift"):
        driver.verify_config(run)


def test_resume_unknown_directory_not_adopted_or_modified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    (unknown / "precious.txt").write_text("preserve")
    before = sorted(unknown.iterdir())
    assert driver.main(["--resume", str(unknown), "--output-root", str(tmp_path / "reports")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert sorted(unknown.iterdir()) == before
    assert Path(result["report"]).is_file()
    assert "no guessing or adoption" in Path(result["report"]).read_text()


def test_identical_original_selected_tools_not_labeled_build_contrast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run, config = frozen_smoke(tmp_path, monkeypatch)
    config["suites"]["experiments"] = config["suites"]["smoke"]
    args = driver.prepare_request(config, "experiments")["args"]
    assert args["old_ffmpeg"] is None and args["old_ffprobe"] is None
    assert args["ffmpeg"] == config["selected_tools"]["ffmpeg"]["path"]


def test_observation_timeout_is_retained_and_process_terminated() -> None:
    result = driver.observe(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
        timeout=0.2,
    )
    assert result["returncode"] is None
    assert result["stdout"] == "started\n"
    assert "process group terminated" in result["error"]


def complete_observations(pair: dict[str, Any], *, gpu: bool = False) -> dict[str, Any]:
    value = observed(pair)
    filters = "format scale split gblur blend crop geq lut alphamerge"
    encoders = "prores_ks ffv1 libx264 rawvideo"
    if gpu:
        filters += " hwupload hwdownload gblur_vulkan"
        encoders += " prores_ks_vulkan ffv1_vulkan"
    value["observations"] = {
        "-filters": {
            "returncode": 0,
            "stdout": "".join(f" T.. {name} V->V description\n" for name in filters.split()),
        },
        "-encoders": {
            "returncode": 0,
            "stdout": "".join(f" V..... {name} description\n" for name in encoders.split()),
        },
        "-hwaccels": {
            "returncode": 0,
            "stdout": "Hardware acceleration methods:\nvulkan\n" if gpu else "",
        },
    }
    return value


def test_inventory_retains_unpaired_tools_python_uv_and_cgroups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "ffmpeg"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        driver,
        "cgroup_inventory",
        lambda: [{"path": "/sys/fs/cgroup", "controls": {"cpu.max": "200000 100000"}}],
    )
    inventory = driver.initial_inventory()
    assert inventory["installed_pairs"] == []
    assert inventory["individual_tools"]["ffmpeg"][0]["path"] == str(binary)
    assert inventory["individual_tools"]["ffprobe"] == []
    assert inventory["bootstrap_python"]["prefix"] == sys.prefix
    assert inventory["bootstrap_python"]["base_prefix"] == sys.base_prefix
    assert inventory["uv_version"]["status"] == "NOT_FOUND"
    assert inventory["host"]["cgroup_ancestors"][0]["controls"]["cpu.max"] == "200000 100000"


def test_cgroup_inventory_reads_every_visible_ancestor(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {
        "/proc/self/cgroup": "0::/tenant/job\n",
        "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n",
    }
    for path, cpu, cpus, memory in (
        ("/sys/fs/cgroup/tenant/job", "10000 100000", "1", "1000"),
        ("/sys/fs/cgroup/tenant", "20000 100000", "1-2", "2000"),
        ("/sys/fs/cgroup", "max 100000", "0-3", "max"),
    ):
        files.update(
            {
                path + "/cpu.max": cpu,
                path + "/cpuset.cpus.effective": cpus,
                path + "/memory.max": memory,
            }
        )
    monkeypatch.setattr(driver, "read_optional", files.get)
    records = driver.cgroup_inventory()
    assert [r["path"] for r in records] == [
        "/sys/fs/cgroup/tenant/job",
        "/sys/fs/cgroup/tenant",
        "/sys/fs/cgroup",
    ]
    assert [r["controls"]["memory.max"] for r in records] == ["1000", "2000", "max"]
    assert records[0]["controls"]["cpuset.cpus.effective"] == "1"


def test_storage_is_actual_requested_roots_before_creation(tmp_path: Path) -> None:
    requested = tmp_path / "future/media"
    inventory = driver.storage_inventory({"requested_media": requested})
    record = inventory["requested_media"]
    assert record["requested_path"] == str(requested)
    assert record["observed_existing_ancestor"] == str(tmp_path)
    assert record["total_bytes"] > 0 and record["available_bytes"] > 0
    assert not requested.exists()


def test_environment_collects_all_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []

    def missing(name: str) -> str:
        called.append(name)
        raise driver.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(driver.importlib.metadata, "version", missing)
    with pytest.raises(ValueError) as exc:
        driver.environment_details()
    import tomllib

    deps = tomllib.loads((driver.ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert all(dep.split("==")[0] in str(exc.value) for dep in deps)
    assert set(called) == {*driver.runtime_lock(), "ewp-waveform"}


def test_startup_aggregates_tool_python_and_build_problems_before_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = driver.parser().parse_args(
        [
            "--cpu-smoke",
            "--build-ffmpeg",
            "--python",
            str(tmp_path / "missing"),
            "--ffmpeg",
            "/unpaired",
        ]
    )
    monkeypatch.setattr(
        driver,
        "probe_python",
        lambda *a: (_ for _ in ()).throw(ValueError("missing numpy; missing pillow")),
    )
    monkeypatch.setattr(
        driver,
        "build_prerequisites",
        lambda *a, **k: {"problems": ["missing glslc", "missing Vulkan headers"]},
    )
    monkeypatch.setattr(
        driver, "select_python", lambda *a: pytest.fail("uv/setup must not execute")
    )
    with pytest.raises(ValueError) as exc:
        driver.startup_prerequisites(
            args,
            tmp_path,
            {"installed_pairs": [], "first_path_tools": {"ffmpeg": None, "ffprobe": None}},
        )
    assert all(
        s in str(exc.value)
        for s in (
            "together",
            "missing numpy",
            "missing pillow",
            "missing glslc",
            "missing Vulkan headers",
        )
    )
    assert driver.load(tmp_path / "startup-prerequisites.json")["build_needed"]


def test_build_permission_not_forced_when_gpu_pair_suitable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pair = tools(tmp_path, "tools")
    observed_pair = complete_observations(pair, gpu=True)
    initial = {
        "installed_pairs": [observed_pair],
        "first_path_tools": {k: v["path"] for k, v in pair.items()},
    }
    monkeypatch.setattr(driver, "probe_python", lambda *a: {})
    monkeypatch.setattr(
        driver,
        "build_prerequisites",
        lambda *a, **k: pytest.fail("must not compile/build suitable selected tools"),
    )
    args = driver.parser().parse_args(["--cpu-smoke", "--build-ffmpeg"])
    baseline, selected, build = driver.startup_prerequisites(args, tmp_path, initial)
    assert baseline == pair and selected == observed_pair and build is False


def test_automatic_selection_prefers_complete_gpu_over_partial_tied_score(tmp_path: Path) -> None:
    partial = tools(tmp_path, "partial")
    full = tools(tmp_path, "full")
    partial_observed = complete_observations(partial, gpu=True)
    partial_observed["observations"]["-filters"]["stdout"] = partial_observed["observations"][
        "-filters"
    ]["stdout"].replace("hwdownload", "not_download")
    full_observed = complete_observations(full, gpu=True)
    initial = {
        "installed_pairs": [partial_observed, full_observed],
        "first_path_tools": {k: v["path"] for k, v in partial.items()},
    }
    baseline, selected = driver.select_tools(initial, None, None)
    assert baseline == partial and selected == full_observed


def test_missing_original_pair_allows_explicit_selected_or_build(tmp_path: Path) -> None:
    pair = tools(tmp_path, "tools")
    initial = {"installed_pairs": [], "first_path_tools": {"ffmpeg": None, "ffprobe": None}}
    baseline, selected = driver.select_tools(
        initial, Path(pair["ffmpeg"]["path"]), Path(pair["ffprobe"]["path"])
    )
    assert baseline is None and selected["tools"] == pair
    assert driver.select_tools(initial, None, None, allow_missing=True) == (None, None)


def test_known_missing_baseline_capability_skips_but_unknown_or_bad_graph_does_not(
    tmp_path: Path,
) -> None:
    pair = tools(tmp_path, "tools")
    value = complete_observations(pair)
    assert driver.baseline_skip_reason(value) is None
    value["observations"]["-encoders"]["stdout"] = " V..... ffv1 FFV1\n"
    assert "prores_ks" in driver.baseline_skip_reason(value)
    value["observations"]["-encoders"]["returncode"] = 1
    assert driver.baseline_skip_reason(value) is None  # unclassified failure is never a skip
    value = complete_observations(pair)
    value["runtime_error"] = "malformed graph"
    assert driver.baseline_skip_reason(value) is None  # runtime failure still reaches suite


def test_build_observations_and_compile_probes_are_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(driver.shutil, "which", lambda name: "/tools/" + name)

    def observe(argv: list[str], **kwargs: Any) -> dict[str, Any]:
        calls.append(argv)
        return {
            "returncode": 1 if "--target-env=vulkan1.4" in argv or "-fsyntax-only" in argv else 0,
            "stdout": "",
        }

    monkeypatch.setattr(driver, "observe", observe)
    inventory = driver.build_prerequisites(tmp_path, compile_probe=False)
    assert not inventory["probes"] and not (tmp_path / "build-prerequisites").exists()
    result = driver.build_prerequisites(tmp_path, compile_probe=True)
    assert len(result["problems"]) == 2
    assert any("--target-env=vulkan1.4" in argv and "--target-spv=spv1.6" in argv for argv in calls)
    assert any("-fsyntax-only" in argv for argv in calls)
    assert (tmp_path / "build-prerequisites").stat().st_mode & 0o777 == 0o700


def test_synthetic_fixture_separate_baseline_driver_still_accounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, config = frozen_smoke(tmp_path, monkeypatch)
    assert str(run) in config["roots"]
    fixture = config["fixture_baseline"]
    assert Path(fixture["root"]).parent == run.parent
    assert not Path(config["audio"]["path"]).is_relative_to(run)
    assert fixture["bytes"] == Path(config["audio"]["path"]).stat().st_size
    assert Path(fixture["root"]).stat().st_mode & 0o777 == 0o700
    assert str(run) in driver.prepare_request(config, "smoke")["args"]["account_root"]


def test_driver_markdown_embeds_suite_pairs_validation_and_media(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    suite_report = suite / "report.md"
    suite_report.write_text(
        "# suite\nComparable pairs: B/C\nValidation PASS\n"
        "Dedup MOV [mov](media/x.mov) [mp4](media/x.mp4)\n"
    )
    driver.save(
        tmp_path / "initial-inventory.json",
        {"bootstrap_python": {"prefix": "/python"}, "storage": {"media": {"free_bytes": 123}}},
    )
    output = driver.report(
        tmp_path,
        "TECHNICAL_COMPLETE",
        None,
        None,
        {"experiments": {"report": str(suite_report), "status": "TECHNICAL_COMPLETE"}},
    )
    text = output.read_text()
    assert all(
        s in text
        for s in (
            "Comparable pairs: B/C",
            "Validation PASS",
            "Dedup MOV",
            str(suite / "media/x.mov"),
            str(suite / "media/x.mp4"),
            "free_bytes",
            "/python",
        )
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux driver ownership contract")
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_direct_parent_signal_reaps_uncooperative_detached_worker(
    tmp_path: Path,
    signum: int,
) -> None:
    """Independent D1 topology, strengthened: both descendants ignore TERM."""
    pidfile = tmp_path / "pids.json"
    fake = tmp_path / "synthetic-python"
    fake.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json, os, signal, subprocess, sys, time
from pathlib import Path
req = json.loads(Path(sys.argv[-1]).read_text())
signal.signal(signal.SIGTERM, signal.SIG_IGN)
worker = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],
    start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(req['pidfile']).write_text(json.dumps([os.getpid(), worker.pid]))
time.sleep(60)
"""
    )
    fake.chmod(0o700)
    run = tmp_path / "run"
    run.mkdir()
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    ready = threading.Event()

    def interrupt() -> None:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if pidfile.exists():
            ready.set()
            os.kill(os.getpid(), signum)

    thread = threading.Thread(target=interrupt, daemon=True)
    thread.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            driver.invoke(
                fake,
                run,
                "batch",
                {"operation": "unit", "pidfile": str(pidfile)},
                accepted=("SUCCEEDED",),
            )
        thread.join(timeout=6)
        assert ready.is_set()
        assert all(not Path(f"/proc/{pid}").exists() for pid in json.loads(pidfile.read_text()))
        assert unrelated.poll() is None
        with pytest.raises(ValueError, match="uncertain STARTED"):
            driver.completed_steps(run)
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux driver ownership contract")
@pytest.mark.parametrize("leader_exits", [False, True])
def test_timeout_or_exited_leader_reaps_closed_pipe_term_resistant_child(
    tmp_path: Path,
    leader_exits: bool,
) -> None:
    """Actual D2 reproducer: pipe completion must never control escalation."""
    pidfile = tmp_path / "child.pid"
    child_source = (
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    )
    leader = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_source!r}],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); "
        f"Path({str(pidfile)!r}).write_text(str(p.pid)); "
        + ("time.sleep(.1)" if leader_exits else "time.sleep(60)")
    )
    result = driver.observe([sys.executable, "-c", leader], timeout=0.5)
    assert result["shutdown_verified"] is True
    assert not Path(f"/proc/{pidfile.read_text()}").exists()


def test_no_mp4_encoder_required_for_stock_full(tmp_path: Path) -> None:
    value = complete_observations(tools(tmp_path, "tools"))
    value["observations"]["-encoders"]["stdout"] = value["observations"]["-encoders"][
        "stdout"
    ].replace("libx264", "no_mp4")
    assert driver.baseline_skip_reason(value) is None


@pytest.mark.parametrize("failure", ["missing", "corrupt", "unreadable"])
def test_all_secondary_report_evidence_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    reference = tmp_path / "reference.json"
    current = tmp_path / "current.json"
    suite = tmp_path / "suite.md"
    paths = [
        reference,
        current,
        suite,
        tmp_path / "initial-inventory.json",
        tmp_path / "startup-prerequisites.json",
    ]
    for path in paths:
        if failure != "missing":
            path.write_bytes(b"\xff" if failure == "corrupt" else b"{}")
    original = Path.read_text

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if failure == "unreadable" and path in paths:
            raise PermissionError("synthetic permission failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    config = {
        "mode": "reference-only",
        "source": {"commit": "a" * 40},
        "python": sys.executable,
        "environment": {},
        "baseline_tools": {},
        "selected_tools": {},
        "reference": {"path": str(reference)},
        "current_reference": {"path": str(current)},
    }
    report = driver.report(
        tmp_path,
        "HOLD",
        "original prepare error",
        config,
        {"reference": {"status": "HOLD", "report": str(suite)}},
    )
    text = report.read_text()
    assert "original prepare error" in text
    assert "UNAVAILABLE" in text and "UNVERIFIED" in text
    assert str(current) in text and str(suite) in text


def test_main_prints_exact_minimal_markdown_if_detailed_report_breaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        driver,
        "initial_inventory",
        lambda: (_ for _ in ()).throw(ValueError("original inventory failure")),
    )
    monkeypatch.setattr(
        driver,
        "detailed_report",
        lambda *a: (_ for _ in ()).throw(ValueError("secondary reporting failure")),
    )
    assert driver.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 2
    output = json.loads(capsys.readouterr().out)
    path = Path(output["report"])
    assert path.suffix == ".md" and path.is_file()
    assert "original inventory failure" in path.read_text()
    assert "secondary reporting failure" in path.read_text()


def test_transitive_runtime_closure_checked_without_editable_version_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closure = driver.runtime_lock()
    assert {"pydantic-core", "annotated-types", "typing-extensions", "mdurl"} <= closure.keys()
    assert "pytest" not in closure
    assert ("colorama" in closure) == (sys.platform == "win32")
    monkeypatch.setattr(
        driver.importlib.metadata,
        "version",
        lambda name: (
            "editable-label-not-source-version" if name == "ewp-waveform" else closure[name]
        ),
    )
    details = driver.environment_details()
    assert details["project_distribution"] == "editable-label-not-source-version"
    assert details["dependencies"] == details["runtime_lock_closure"] == closure
    monkeypatch.setattr(
        driver.importlib.metadata,
        "version",
        lambda name: (
            "wrong-transitive"
            if name in {"pydantic-core", "mdurl"}
            else "editable"
            if name == "ewp-waveform"
            else closure[name]
        ),
    )
    with pytest.raises(ValueError) as exc:
        driver.environment_details()
    assert "pydantic-core" in str(exc.value) and "mdurl" in str(exc.value)


def test_lock_markers_are_applicable_or_fail_closed() -> None:
    assert driver.lock_marker_applies("python_version >= '3.9' and python_version < '3.13'")
    assert not driver.lock_marker_applies("python_version < '3.9'")
    with pytest.raises(ValueError, match="unsupported"):
        driver.lock_marker_applies("unknown_marker == 'anything'")


def test_build_parent_with_nested_git_is_only_account_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    pair = tools(tmp_path, "installed")
    initial = {
        "installed_pairs": [complete_observations(pair)],
        "first_path_tools": {k: v["path"] for k, v in pair.items()},
    }
    driver.save(run / "initial-inventory.json", initial)
    monkeypatch.setattr(driver, "source_identity", lambda: {"commit": "a" * 40})
    monkeypatch.setattr(driver, "probe_python", lambda *a: {})
    monkeypatch.setattr(driver, "select_python", lambda *a: (Path(sys.executable), {}))
    monkeypatch.setattr(driver, "build_prerequisites", lambda *a, **k: {"problems": []})
    monkeypatch.setattr(driver, "inventory_pair", lambda p: complete_observations(p))
    monkeypatch.setattr(driver, "build_memory", lambda: {"headroom_bytes": 20 * 1024**3})
    monkeypatch.setattr(
        driver,
        "storage_inventory",
        lambda roots: {"toolchain": {"available_bytes": 30 * 1024**3, "free_bytes": 30 * 1024**3}},
    )

    def synthetic_builder(argv: list[str], **kwargs: Any) -> dict[str, Any]:
        source, build, prefix = [
            Path(argv[argv.index("--" + n) + 1]) for n in ("source", "build", "prefix")
        ]
        (source / ".git").mkdir(parents=True)
        (source / ".git/object").write_bytes(b"nested git bytes")
        build.mkdir()
        driver.save(build / "build-receipt.json", {"synthetic": True})
        prefix.mkdir()
        tools(prefix, "bin")
        kwargs["monitor"]()
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(driver, "observe", synthetic_builder)
    args = driver.parser().parse_args(["--cpu-smoke", "--build-ffmpeg"])
    config = driver.freeze_new(args, run, initial, "synthetic")
    parent = run.parent / "ffmpeg-toolchain-synthetic"
    from ewp_waveform.application.experiment_suite_state import tree_bytes, validate_roots

    assert validate_roots([Path(p) for p in config["roots"]])
    assert str(parent) in config["roots"]
    assert not any(str(parent / n) in config["roots"] for n in ("source", "build", "prefix"))
    assert tree_bytes(parent) >= len(b"nested git bytes")
    assert str(parent) in driver.prepare_request(config, "smoke")["args"]["account_root"]
    assert driver.verify_config(run) == config


@pytest.mark.parametrize("fault", ["disk", "growth", "ram", "rss"])
@pytest.mark.parametrize("admission", [True, False])
def test_build_envelope_admission_and_inflight_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    admission: bool,
) -> None:
    limits = dict(driver.BUILD_LIMITS)
    monkeypatch.setattr(
        driver,
        "storage_inventory",
        lambda roots: {
            "toolchain": {
                "available_bytes": 0 if fault == "disk" else 30 * 1024**3,
                "free_bytes": 0 if fault == "disk" else 30 * 1024**3,
            }
        },
    )
    monkeypatch.setattr(
        driver, "build_tree_bytes", lambda p: limits["growth_bytes"] + 1 if fault == "growth" else 0
    )
    monkeypatch.setattr(
        driver, "build_memory", lambda: {"headroom_bytes": 0 if fault == "ram" else 30 * 1024**3}
    )
    monkeypatch.setattr(
        driver, "owned_rss", lambda: limits["memory_bytes"] + 1 if fault == "rss" else 0
    )
    if fault == "rss" and admission:
        driver.check_build_budget(tmp_path, limits, admission=admission)
    else:
        with pytest.raises(ValueError, match="refused/crossed"):
            driver.check_build_budget(tmp_path, limits, admission=admission)


def test_build_refusal_no_launch_retains_failure_no_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "toolchain"
    monkeypatch.setattr(
        driver,
        "check_build_budget",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("synthetic admission refusal")),
    )
    monkeypatch.setattr(driver, "observe", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="admission refusal"):
        driver.run_builder(Path(sys.executable), tmp_path, parent)
    assert driver.load(parent / "FAILED.json")["retry"] == "FORBIDDEN"
    with pytest.raises(FileExistsError):
        driver.run_builder(Path(sys.executable), tmp_path, parent)


def test_cgroup_memory_headroom_and_unknown_usage_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver, "read_optional", lambda p: "MemAvailable: 9999999 kB\n")
    controls: dict[str, Any] = {"memory.max": "1024", "memory.current": "1000"}
    monkeypatch.setattr(
        driver, "cgroup_inventory", lambda: [{"path": "/group", "controls": controls}]
    )
    assert driver.build_memory()["headroom_bytes"] == 24
    controls["memory.current"] = None
    with pytest.raises(ValueError, match="unreadable cgroup usage"):
        driver.build_memory()


def test_current_reference_frozen_verified_embedded_and_uses_actual_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, config = frozen_smoke(tmp_path, monkeypatch)
    current = config["current_reference"]
    assert current and Path(current["path"]).name == "vm1-current-reference.json"
    text = driver.report(run, "HOLD", "synthetic", config, {}).read_text()
    measured = driver.load(Path(current["path"]))["source"]["commit"]
    assert measured in text and "NOT a measurement" in text
    actual = driver.verify

    def changed(item: dict[str, Any]) -> None:
        if item == current:
            raise ValueError("current reference drift")
        actual(item)

    monkeypatch.setattr(driver, "verify", changed)
    with pytest.raises(ValueError, match="current reference drift"):
        driver.verify_config(run)


def test_two_tool_smoke_includes_tiny_a_and_but_views_use_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run, config = frozen_smoke(tmp_path, monkeypatch)
    old = tools(tmp_path, "old")
    config["baseline_tools"] = old
    config["baseline_skip_reason"] = None
    old["ffmpeg"]["sha256"] = "different"
    request = driver.prepare_request(config, "smoke")["args"]
    assert request["old_ffmpeg"] == old["ffmpeg"]["path"]
    assert request["ffmpeg"] == config["selected_tools"]["ffmpeg"]["path"]
    manifest = driver.smoke_manifest(template(), Path(config["audio"]["path"]), include_old=True)
    assert [cell["scenario"] for cell in manifest["cells"]] == ["A", "B", "F0"]
    assert manifest["workloads"][0]["frames"] == 6


@pytest.mark.skipif(sys.platform != "linux", reason="Linux driver ownership contract")
@pytest.mark.parametrize("crossing", ["growth", "time", "ram", "disk"])
def test_real_build_supervision_crossing_drains_descendants_and_retains_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crossing: str,
) -> None:
    """Exercise actual observe/monitor/TERM/KILL, never the real compiler/builder."""
    parent = tmp_path / "toolchain"
    pidfile = tmp_path / "worker.pid"
    worker = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    source = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{worker!r}],start_new_session=True,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(pidfile)!r}).write_text(str(p.pid)); "
        "time.sleep(.3); print('x'*100000,flush=True); time.sleep(60)"
    )
    limits = dict(driver.BUILD_LIMITS)
    if crossing == "time":
        limits["seconds"] = 1
    if crossing == "growth":
        limits["growth_bytes"] = 50000
    monkeypatch.setattr(driver, "BUILD_LIMITS", limits)
    monkeypatch.setattr(
        driver,
        "build_memory",
        lambda: {"headroom_bytes": 0 if crossing == "ram" and pidfile.exists() else 20 * 1024**3},
    )
    monkeypatch.setattr(
        driver,
        "storage_inventory",
        lambda roots: {
            "toolchain": {
                "available_bytes": 0 if crossing == "disk" and pidfile.exists() else 30 * 1024**3,
                "free_bytes": 30 * 1024**3,
            }
        },
    )
    actual = driver.observe

    def synthetic(argv: list[str], **kwargs: Any) -> dict[str, Any]:
        assert Path(argv[1]).name == "experiments_build.py"
        return cast(dict[str, Any], actual([sys.executable, "-c", source], **kwargs))

    monkeypatch.setattr(driver, "observe", synthetic)
    with pytest.raises((RuntimeError, ValueError)):
        driver.run_builder(Path(sys.executable), tmp_path, parent)
    assert pidfile.exists()
    assert not Path(f"/proc/{pidfile.read_text()}").exists()
    assert driver.load(parent / "FAILED.json")["retry"] == "FORBIDDEN"
    assert (parent / "stdout.txt").is_file() and (parent / "stderr.txt").is_file()
    assert (parent / "resource-samples.jsonl").is_file()
    result = driver.load(tmp_path / "ffmpeg-builder.json")
    assert result["shutdown_verified"] is True
    assert "process group terminated" in result["error"]
    assert result["returncode"] is None


def test_report_write_failure_explained_on_stderr_without_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        driver, "initial_inventory", lambda: (_ for _ in ()).throw(ValueError("original failure"))
    )
    monkeypatch.setattr(
        driver,
        "report",
        lambda *a: (_ for _ in ()).throw(OSError("disk full for both report formats")),
    )
    assert driver.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    value = json.loads(captured.err)
    assert value["report"] is None and value["status"] == "HOLD"
    assert "original failure" in value["error"] and "disk full" in value["report_error"]


def test_bootstrap_avoids_python311_only_apis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Syntax/API compatibility checks under the test Python, NOT an actual 3.10 qualification.
    ast.parse(SCRIPT.read_text(), feature_version=(3, 10))
    monkeypatch.delattr(driver.hashlib, "file_digest")
    monkeypatch.delattr(driver.dt, "UTC")
    payload = tmp_path / "payload"
    payload.write_bytes(b"x" * (1024**2 + 17))
    assert driver.digest(payload) == driver.hashlib.sha256(payload.read_bytes()).hexdigest()
    problem = ValueError("original")
    driver.note_error(problem, "retained cleanup error")
    assert problem.__notes__ == ["retained cleanup error"]
    monkeypatch.setattr(
        driver,
        "initial_inventory",
        lambda: (_ for _ in ()).throw(ValueError("discovery diagnostic")),
    )
    assert driver.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert "discovery diagnostic" in Path(result["report"]).read_text()


def test_pidfd_api_prefers_stdlib_without_requiring_libc_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(driver.os, "pidfd_open", lambda pid, flags: 123, raising=False)
    monkeypatch.setattr(
        driver.signal,
        "pidfd_send_signal",
        lambda *args: calls.append(args),
        raising=False,
    )
    open_fd, send_fd = driver.pidfd_api(object())
    assert open_fd(42, 0) == 123
    assert send_fd(123, signal.SIGTERM, None, 0) == 0
    assert calls == [(123, signal.SIGTERM, None, 0)]


def test_pidfd_api_supports_standalone_python_via_libc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(driver.os, "pidfd_open", raising=False)
    monkeypatch.delattr(driver.signal, "pidfd_send_signal", raising=False)

    class Libc:
        @staticmethod
        def pidfd_open(pid: int, flags: int) -> int:
            return 456

        @staticmethod
        def pidfd_send_signal(fd: int, sig: int, info: Any, flags: int) -> int:
            return 0

    open_fd, send_fd = driver.pidfd_api(Libc())
    assert open_fd(42, 0) == 456
    assert send_fd(456, signal.SIGKILL, None, 0) == 0


@pytest.mark.parametrize("operation", ["observe", "invoke"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize(
    "boundary", ["constructor", "registration", "transfer", "return", "wrapper"]
)
@pytest.mark.parametrize("fail", [False, True])
def test_launch_boundary_defers_signals_and_reconciles_bookkeeping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    signum: int,
    boundary: str,
    fail: bool,
) -> None:
    """Portable state-machine oracle; no /proc, chmod, sleeps or real subprocess.

    Exercise the actual owned_popen return event, including an exception before
    its caller can receive a handle. Constructor/registry/list failures retain
    the original error even if an operator interrupt was delivered concurrently.
    The independent real-process tests exercise this same protocol with workers.
    """
    original = RuntimeError(f"original {boundary} failure")
    processes: list[Any] = []
    closed: list[int] = []
    shutdown_signals: list[tuple[int, int]] = []
    reads = iter([b"READY\n", b"REAPED"])
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    def interrupt() -> None:
        signal.raise_signal(signum)
        if fail:
            raise original

    class SyntheticPopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.pid = 48123
            self.returncode: int | None = None
            processes.append(self)
            if boundary == "constructor":
                interrupt()

        def send_signal(self, sig: int) -> None:
            shutdown_signals.append((self.pid, sig))

        def wait(self) -> int:
            self.returncode = 143
            return self.returncode

    class Receipts(dict[int, int]):
        def __setitem__(self, pid: int, reader: int) -> None:
            if boundary == "registration":
                interrupt()
            super().__setitem__(pid, reader)

    class Transfer(list[Any]):
        def __init__(self, target: list[Any]) -> None:
            super().__init__()
            self.target = target

        def append(self, proc: Any) -> None:
            interrupt()
            self.target.append(proc)

    monkeypatch.setattr(driver.subprocess, "Popen", SyntheticPopen)
    monkeypatch.setattr(driver.os, "pipe", lambda: (81001, 81002))
    monkeypatch.setattr(driver.os, "close", closed.append)
    monkeypatch.setattr(driver.os, "read", lambda fd, count: next(reads))
    receipts = Receipts()
    monkeypatch.setattr(driver, "OWNERSHIP_RECEIPTS", receipts)
    actual = driver.owned_popen

    def wrapped(argv: list[str], **kwargs: Any) -> Any:
        if boundary == "transfer":
            kwargs["_owned"] = Transfer(kwargs["_owned"])
        proc = actual(argv, **kwargs)
        if boundary == "wrapper":
            interrupt()
        return proc

    if boundary in ("transfer", "wrapper"):
        monkeypatch.setattr(driver, "owned_popen", wrapped)

    def trace(frame: Any, event: str, arg: Any) -> Any:
        if frame.f_code is actual.__code__ and event == "return" and arg is not None:
            interrupt()
        return trace

    if boundary == "return":
        sys.settrace(trace)
    try:
        with pytest.raises(RuntimeError if fail else KeyboardInterrupt) as caught:
            if operation == "observe":
                driver.observe([sys.executable, "-c", "pass"])
            else:
                driver.invoke(Path(sys.executable), tmp_path, "synthetic", {}, accepted=("OK",))
    finally:
        if boundary == "return":
            sys.settrace(None)
    if fail:
        assert caught.value is original
    assert processes[0].returncode == 143
    assert shutdown_signals == [(48123, signal.SIGTERM)]
    assert sorted(closed) == [81001, 81002]
    assert receipts == {}
    assert {s: signal.getsignal(s) for s in previous} == previous
    if operation == "invoke":
        with pytest.raises(ValueError, match="uncertain STARTED"):
            driver.completed_steps(tmp_path)


@pytest.mark.parametrize("operation", ["observe", "invoke"])
def test_constructor_failure_without_child_closes_receipt_and_preserves_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    original = RuntimeError("constructor refused before spawn")
    closed: list[int] = []

    class NoChild:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise original

    monkeypatch.setattr(driver.subprocess, "Popen", NoChild)
    monkeypatch.setattr(driver.os, "pipe", lambda: (81001, 81002))
    monkeypatch.setattr(driver.os, "close", closed.append)
    monkeypatch.setattr(driver, "OWNERSHIP_RECEIPTS", {})
    with pytest.raises(RuntimeError) as caught:
        if operation == "observe":
            driver.observe(["unused"])
        else:
            driver.invoke(Path(sys.executable), tmp_path, "synthetic", {}, accepted=("OK",))
    assert caught.value is original
    assert sorted(closed) == [81001, 81002]
    assert not driver.OWNERSHIP_RECEIPTS


@pytest.mark.skipif(sys.platform != "linux", reason="Linux driver ownership contract")
def test_launch_deferral_does_not_block_child_interrupt_signals() -> None:
    source = (
        "import signal,json; "
        "mask=signal.pthread_sigmask(signal.SIG_BLOCK, []); "
        "print(json.dumps([int(s) for s in mask]))"
    )
    value = driver.observe([sys.executable, "-c", source])
    assert value["returncode"] == 0 and value["shutdown_verified"]
    assert not {signal.SIGINT, signal.SIGTERM}.intersection(json.loads(value["stdout"]))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux driver ownership contract")
@pytest.mark.parametrize("operation", ["observe", "invoke"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("boundary", ["constructor", "registration", "return"])
def test_real_launch_boundary_reaps_ready_detached_worker_before_propagating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    signum: int,
    boundary: str,
) -> None:
    """Actual launcher/supervisor, ready TERM-resistant descendants, no media."""
    ready = tmp_path / "leaf-ready"
    pidfile = tmp_path / "pids.json"
    leaf = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    stage = (
        "import os,sys,signal,subprocess,time,json; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"p=subprocess.Popen([sys.executable,'-c',{leaf!r}],start_new_session=True,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)"
    )
    original = RuntimeError(f"original ready-child {boundary} failure")
    launched: list[subprocess.Popen[Any]] = []
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    actual_init = subprocess.Popen.__init__
    actual_launch = driver.owned_popen
    previous_trace = sys.gettrace()

    def interrupt_ready() -> None:
        deadline = time.monotonic() + 6
        while not (ready.exists() and pidfile.exists()) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists() and pidfile.exists(), "synthetic child readiness"
        os.kill(os.getpid(), signum)
        if boundary != "return":
            raise original

    def init(proc: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        actual_init(proc, *args, **kwargs)
        launched.append(proc)
        if boundary == "constructor":
            interrupt_ready()

    class Receipts(dict[int, int]):
        def __setitem__(self, pid: int, reader: int) -> None:
            if boundary == "registration":
                interrupt_ready()
            super().__setitem__(pid, reader)

    def launch(argv: list[str], **kwargs: Any) -> Any:
        return actual_launch([sys.executable, "-c", stage], **kwargs)

    def trace(frame: Any, event: str, arg: Any) -> Any:
        if frame.f_code is actual_launch.__code__ and event == "return" and arg is not None:
            interrupt_ready()
        return trace

    monkeypatch.setattr(subprocess.Popen, "__init__", init)
    monkeypatch.setattr(driver, "OWNERSHIP_RECEIPTS", Receipts())
    monkeypatch.setattr(driver, "owned_popen", launch)
    if boundary == "return":
        sys.settrace(trace)
    try:
        with pytest.raises(KeyboardInterrupt if boundary == "return" else RuntimeError) as caught:
            if operation == "observe":
                driver.observe([sys.executable, "-c", "pass"])
            else:
                driver.invoke(Path(sys.executable), tmp_path, "synthetic", {}, accepted=("OK",))
        if boundary != "return":
            assert caught.value is original
        pids = [p.pid for p in launched] + json.loads(pidfile.read_text())
        observation = {str(pid): Path(f"/proc/{pid}").exists() for pid in pids}
        (tmp_path / "after-propagation.json").write_text(json.dumps(observation))
        assert not any(observation.values()), observation
        assert not driver.OWNERSHIP_RECEIPTS
        assert unrelated.poll() is None
        if operation == "invoke":
            with pytest.raises(ValueError, match="uncertain STARTED"):
                driver.completed_steps(tmp_path)
    finally:
        sys.settrace(previous_trace)
        for proc in launched:
            if proc.pid in driver.OWNERSHIP_RECEIPTS:
                driver.stop_owned(proc)
            elif proc.poll() is None:
                proc.terminate()  # Only the test's exact retained supervisor.
                proc.wait(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=5)
