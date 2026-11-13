"""Focused stdlib startup/authority tests; no target media or host setup execution."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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
    assert len(called) == len(deps) + 1


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
