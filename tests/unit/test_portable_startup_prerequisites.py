"""Prerequisite, admission, accounting and managed reuse regression contracts."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_dependencies as deps
from ewp_waveform.application import portable_experiments_setup as setup
from ewp_waveform.application import portable_experiments_state as state


def fake_environment(python: Path) -> dict[str, Any]:
    return {"binary": state.identity(python), "version": "3.12.3", "locked_runtime": {}}


def test_missing_uv_platform_commands_reason_new_terminal_and_exact_rerun() -> None:
    rerun = [
        "scripts/run_experiments.py",
        "--audio",
        "D:\\media with spaces\\s0.wav",
        "--prepare-ffmpeg",
    ]
    windows = deps.missing_uv(rerun, windows=True)
    assert "winget install --id astral-sh.uv --exact" in windows
    assert "NEW terminal" in windows and "uv --version" in windows
    assert "Python 3.12" in windows and "stdlib driver" in windows
    assert "'D:\\media with spaces\\s0.wav'" in windows
    assert "& 'py' '-3'" in windows
    linux = deps.missing_uv(rerun, windows=False)
    assert "https://astral.sh/uv/install.sh | sh" in linux
    assert "--prepare-ffmpeg" in linux


def test_explicit_missing_python_never_installs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(app, "run_command", lambda *a, **k: pytest.fail("no install"))
    with pytest.raises(ValueError, match="explicit --python does not exist"):
        app.select_python(tmp_path / "absent", tmp_path)


def test_global_inode_dedup_overlaps_hardlinks_and_sparse_allocation(tmp_path: Path) -> None:
    cache, env = tmp_path / "cache", tmp_path / "env"
    cache.mkdir()
    env.mkdir()
    payload = cache / "payload"
    with payload.open("wb") as stream:
        stream.seek(16 * 1024**2)
        stream.write(b"x")
    try:
        os.link(payload, env / "same-payload")
    except OSError:
        pytest.skip("filesystem does not support hardlinks")
    usage = state.tree_usage([tmp_path, cache, env, tmp_path])
    assert usage["files"] == 1
    assert usage["logical_bytes"] == payload.stat().st_size
    if hasattr(payload.stat(), "st_blocks"):
        assert usage["allocated_bytes"] < usage["logical_bytes"]
        assert usage["budget_basis"] == "allocated blocks"
    assert state.tree_usage([tmp_path]) == usage


def test_inspection_bounds_refuse_partial_totals(tmp_path: Path) -> None:
    (tmp_path / "payload").write_bytes(b"x")
    with pytest.raises(ValueError, match="no partial total"):
        state.tree_usage([tmp_path], max_entries=1)


@pytest.mark.parametrize("fault", ["growth", "disk", "ram"])
def test_global_resource_refusals_are_typed(tmp_path: Path, monkeypatch: Any, fault: str) -> None:
    (tmp_path / "payload").write_bytes(b"x" * 8192)
    monkeypatch.setattr(
        state, "resources", lambda: {"ram_available_bytes": 0 if fault == "ram" else 10**12}
    )
    limits = {
        "growth_bytes": 1 if fault == "growth" else 10**12,
        "reserve_bytes": 10**30 if fault == "disk" else 0,
        "memory_floor_bytes": 1,
    }
    with pytest.raises(state.ResourceLimitError):
        state.check_budget(tmp_path, tmp_path, limits)


def test_setup_baseline_excludes_existing_managed_bytes_and_render_scope(
    tmp_path: Path, monkeypatch: Any
) -> None:
    store, run, media = (tmp_path / name for name in ("store", "run", "media"))
    for p in (store, run, media):
        p.mkdir()
    (store / "old-cache").write_bytes(b"x" * 8192)
    limits = deps.setup_limits(store, 1, 0)
    monkeypatch.setattr(state, "resources", lambda: {"ram_available_bytes": 10**12})
    assert state.check_budget(run, media, limits)["growth_bytes"] == 0
    (media / "render").write_bytes(b"x" * 8192)
    assert state.check_budget(run, media, limits)["growth_bytes"] == 0
    (store / "new-cache").write_bytes(b"x" * 8192)
    assert state.check_budget(run, media, limits)["growth_bytes"] > 0
    render_limits = {"growth_bytes": 10**12, "reserve_bytes": 0, "memory_floor_bytes": 1}
    assert state.check_budget(run, media, render_limits)["storage"]["files"] == 1


@pytest.mark.parametrize("fault", ["growth", "free"])
def test_admission_refuses_before_any_download(
    tmp_path: Path, monkeypatch: Any, fault: str
) -> None:
    monkeypatch.setattr(
        deps,
        "check_budget",
        lambda *a: {"growth_bytes": 0, "free_bytes": 1 if fault == "free" else 10**12},
    )
    limits = {"growth_bytes": 1 if fault == "growth" else 10**12, "reserve_bytes": 1}
    monkeypatch.setattr(setup, "run_command", lambda *a, **k: pytest.fail("no download"))
    monkeypatch.setattr(shutil, "which", lambda name: "unused-uv")
    with pytest.raises(state.ResourceLimitError, match="BEFORE download"):
        setup.install_cuda(Path(sys.executable), {}, tmp_path, tmp_path, limits, {})
    assert not (tmp_path / "managed-dependencies/attempts").exists()


def test_verified_runtime_reused_across_campaigns_without_uv_or_install(
    tmp_path: Path, monkeypatch: Any
) -> None:
    python = tmp_path / "python"
    python.write_text("selected interpreter bytes")
    store, run = tmp_path / "store", tmp_path / "run"
    run.mkdir()
    environment = fake_environment(python)
    deps.register_environment(store, app.ROOT, "runtime", python, environment)
    calls: list[Path] = []

    def probe(python: Path, evidence: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append(python)
        return environment

    monkeypatch.setattr(app, "python_candidates", lambda: [])
    monkeypatch.setattr(app, "probe_python", probe)
    monkeypatch.setattr(shutil, "which", lambda *a: None)
    monkeypatch.setattr(app, "run_command", lambda *a, **k: pytest.fail("no install"))
    selected, observed = app.select_python(None, run, managed_root=store)
    assert selected == python and observed == environment and calls == [python]
    assert state.load(run / "runtime-reuse.json")["reused"]


@pytest.mark.parametrize("change", ["lock", "backend", "platform"])
def test_registry_keys_prevent_incompatible_reuse(
    tmp_path: Path, monkeypatch: Any, change: str
) -> None:
    python = tmp_path / "python"
    python.write_text("binary")
    store = tmp_path / "store"
    environment = fake_environment(python)
    deps.register_environment(store, app.ROOT, "runtime", python, environment)
    original = deps.request_key

    def changed(root: Path, backend: str) -> dict[str, Any]:
        value = original(root, backend)
        if change == "lock":
            value["locks"]["uv.lock"] = "changed"
        elif change == "platform":
            value["platform"] = "not-this-platform"
        return value

    monkeypatch.setattr(deps, "request_key", changed)
    result = deps.reuse_environment(
        store,
        app.ROOT,
        "cu128" if change == "backend" else "runtime",
        tmp_path,
        lambda *a, **k: pytest.fail("no incompatible probe"),
    )
    assert result is None


def test_changed_interpreter_payload_refuses_without_repair(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("original")
    store = tmp_path / "store"
    deps.register_environment(store, app.ROOT, "runtime", python, fake_environment(python))
    python.write_text("changed")
    with pytest.raises(ValueError, match="no repair/reinstall"):
        deps.reuse_environment(
            store, app.ROOT, "runtime", tmp_path, lambda *a, **k: fake_environment(python)
        )


def test_legacy_failed_cuda_env_is_discovered_verified_registered_not_reinstalled(
    tmp_path: Path, monkeypatch: Any
) -> None:
    python = (
        tmp_path / "run-old/cuda-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    python.parent.mkdir(parents=True)
    python.write_text("prepared interpreter")
    (python.parents[2] / "FAILED.json").write_text('{"status":"FAILED"}')
    before = (python.parents[2] / "FAILED.json").read_bytes()
    current = tmp_path / "run-new"
    current.mkdir()
    store = tmp_path / "managed-dependencies"
    monkeypatch.setattr(shutil, "which", lambda *a: None)
    monkeypatch.setattr(setup, "run_command", lambda *a, **k: pytest.fail("no sync"))
    selected, receipt = setup.install_cuda(
        Path(sys.executable),
        {},
        current,
        current,
        {},
        {},
        managed_root=store,
        probe=lambda *a, **k: fake_environment(python),
    )
    assert selected == python and receipt["reused"] and receipt["discovered"]
    assert (python.parents[2] / "FAILED.json").read_bytes() == before
    assert list(store.glob("verified/*/*.json"))


def test_policy_is_printed_before_opt_in_uv_install(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    args = app.parser().parse_args(["--setup-only", "--setup-uv", "--output-root", str(tmp_path)])
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()

    def bootstrap(*a: Any) -> str:
        assert "before acquisition" in capsys.readouterr().out
        return "private-uv"

    monkeypatch.setattr(deps, "bootstrap_uv", bootstrap)
    app.dependency_policy(args, run, media)
    assert args._uv_path == "private-uv"
    assert (run / "preparation-policy.json").is_file()


def test_independent_verify_does_not_execute_or_modify_failed_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    failed = tmp_path / "run-failed"
    failed.mkdir()
    (failed / "events.jsonl").write_text("failed immutable history")
    python = failed / "python"
    python.write_text("binary")
    monkeypatch.setattr(app, "probe_python", lambda *a, **k: fake_environment(python))
    monkeypatch.setattr(app, "execute", lambda *a, **k: pytest.fail("no campaign"))
    assert (
        app.main(
            [
                "--verify-environment",
                str(python),
                "--register-environment",
                "--output-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert (failed / "events.jsonl").read_text() == "failed immutable history"
    assert list((tmp_path / "managed-dependencies").glob("verified/*/*.json"))


@pytest.mark.parametrize("fault", ["ownership", "resource"])
@pytest.mark.parametrize("operation", ["probe", "cuda-install", "freeze"])
def test_bootstrap_global_latches_are_not_optional_failures(
    tmp_path: Path, monkeypatch: Any, fault: str, operation: str
) -> None:
    from ewp_waveform.application.portable_experiments_process import (
        ProcessOwnershipError,
        ResourceAdmissionError,
    )

    exception = ProcessOwnershipError if fault == "ownership" else ResourceAdmissionError
    observed = {
        "returncode": 0,
        "error": None,
        "stderr": "",
        "shutdown_verified": fault != "ownership",
        "resource_refused": fault == "resource",
        "resource_errors": ["RAM floor crossed"],
    }
    monkeypatch.setattr(app, "run_command", lambda *a, **k: observed)
    monkeypatch.setattr(setup, "run_command", lambda *a, **k: observed)
    monkeypatch.setattr(setup, "admit_setup", lambda *a: {})
    monkeypatch.setattr(shutil, "which", lambda *a: sys.executable)
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    with pytest.raises(exception):
        if operation == "probe":
            app.probe_python(Path(sys.executable), run / "probe", optional=True)
        elif operation == "cuda-install":
            setup.install_cuda(Path(sys.executable), {}, run, media, {}, {})
        else:
            args = app.parser().parse_args(
                ["--cpu-smoke", "--cuda", "--output-root", str(tmp_path)]
            )
            monkeypatch.setattr(app, "select_python", lambda *a, **k: (Path(sys.executable), {}))
            monkeypatch.setattr(app, "choose_tools", lambda *a: (None, {"tools": {}}, None))
            app.freeze(args, run, media, {})
    assert not (run / "config-seal.json").exists()


def test_optional_full_locked_closure_mismatch_refuses_before_payload_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import importlib.metadata

    (tmp_path / "uv.lock").write_text('[[package]]\nname="ewp-waveform"\nversion="0"\n')
    closure = tmp_path / "cuda.txt"
    closure.write_text("torch==2.9.1+cu128 \\\nfilelock==4.2.10 \\\n")
    monkeypatch.setattr(setup, "cuda_lock", lambda *a: closure)
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: "2.9.1+cu128" if name == "torch" else "wrong"
    )
    monkeypatch.setattr(state, "distribution_payload", lambda *a: pytest.fail("no expensive probe"))
    with pytest.raises(ValueError, match="filelock=wrong"):
        state.environment_details(tmp_path, optional=True)


def test_managed_ffmpeg_request_is_shared_across_campaigns(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from ewp_waveform.ffmpeg import portable_tools

    store = tmp_path / "managed"
    store.mkdir()
    paths: list[str] = []
    args = app.parser().parse_args(["--prepare-ffmpeg"])
    args._managed_root, args._setup_limits = store, {}
    monkeypatch.setattr(deps, "admit_setup", lambda *a: {})
    monkeypatch.setattr(app, "check_budget", lambda *a: {})
    monkeypatch.setattr(app, "inventory_pair", lambda *a: {"tools": {}})

    def worker(argv: Any, logs: Path, **kwargs: Any) -> dict[str, Any]:
        request = state.load(Path(argv[-1]))
        paths.append(request["media"])
        destination = Path(request["media"]) / portable_tools.read_lock()["archive_root"]
        destination.mkdir(parents=True, exist_ok=True)
        state.save(
            Path(request["result_path"]),
            {"acquisition": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}},
        )
        return {"returncode": 0, "error": None, "shutdown_verified": True}

    monkeypatch.setattr(app, "run_command", worker)
    original = {"first_path_tools": {"ffmpeg": None, "ffprobe": None}, "tools": {"ffmpeg": []}}
    for number in (1, 2):
        run = tmp_path / str(number)
        run.mkdir()
        app.choose_tools(args, original, run, tmp_path, Path(sys.executable))
    assert paths[0] == paths[1]
    assert str(store / "ffmpeg") in paths[0]


@pytest.mark.parametrize("flag", ["--setup-uv", "--prepare-ffmpeg"])
def test_read_only_inspection_rejects_install_options(flag: str) -> None:
    with pytest.raises(SystemExit) as caught:
        app.main(["--inspect-storage", ".", flag])
    assert caught.value.code == 2


def test_inspect_storage_cli_is_read_only_and_deduplicates_roots(
    tmp_path: Path, capsys: Any
) -> None:
    (tmp_path / "file").write_bytes(b"1234")
    before = sorted(tmp_path.rglob("*"))
    assert app.main(["--inspect-storage", str(tmp_path), str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["logical_bytes"] == 4
    assert sorted(tmp_path.rglob("*")) == before
