"""Portable startup/state/process contracts without importing Linux-only legacy suite."""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_state as state
from ewp_waveform.application.portable_experiments_process import run_command
from ewp_waveform.application.portable_experiments_worker import performance_file


def test_parser_defaults_are_short_first_and_cuda_opt_in() -> None:
    args = app.parser().parse_args(["--audio", "source with spaces.wav"])
    assert not args.full and not args.cuda and not args.preflight_only
    assert not args.no_production32
    assert "--cpu-smoke" in app.parser().format_help()
    assert "--reference-only" in app.parser().format_help()
    assert "--prepare-ffmpeg" in app.parser().format_help()
    assert not args.install_cuda and not args.prepare_ffmpeg


@pytest.mark.parametrize("override", ["--python=elsewhere", "--timeout=1", "--install-cuda"])
def test_resume_rejects_equals_or_flag_overrides(override: str) -> None:
    with pytest.raises(SystemExit) as caught:
        app.main(["--resume", "missing-namespace", override])
    assert caught.value.code == 2


def test_cuda_download_is_explicit() -> None:
    with pytest.raises(SystemExit) as caught:
        app.main(["--cpu-smoke", "--install-cuda"])
    assert caught.value.code == 2


def test_cuda_install_low_budget_refuses_before_any_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ewp_waveform.application import portable_experiments_setup as setup

    monkeypatch.setattr("shutil.which", lambda name: "/not/invoked/uv")
    monkeypatch.setattr(setup, "check_budget", lambda *a: {"free_bytes": 10 * 1024**3})
    monkeypatch.setattr(setup, "run_command", lambda *a, **k: pytest.fail("must not download"))
    with pytest.raises(ValueError, match="admission"):
        setup.install_cuda(
            Path(sys.executable),
            {},
            tmp_path,
            tmp_path,
            {"growth_bytes": 1024**2, "reserve_bytes": 1024**3},
            {},
        )


def test_windows_python_layout_is_considered() -> None:
    assert any(
        str(p).replace("\\", "/").endswith(".venv/Scripts/python.exe")
        for p in app.python_candidates()
    )


def test_tool_inventory_records_original_exe_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = tmp_path / "ffmpeg"
    tool.write_text("binary placeholder not invoked")
    tool.chmod(0o700)
    if os.name == "nt":
        tool.rename(tool.with_suffix(".exe"))
    found = app.discover_tools(str(tmp_path))
    assert len(found["ffmpeg"]) == 1
    assert not found["ffprobe"]


def test_performance_path_roundtrips_toml(tmp_path: Path) -> None:
    import tomllib

    performance = performance_file(tmp_path)
    parsed = tomllib.loads(performance.read_text())
    assert parsed["processing"]["jobs"] == 2
    assert parsed["processing"]["ffmpeg_threads"] == 0
    assert parsed["workdirs"]["root"] == (tmp_path / "work").as_posix()


def record_step(root: Path, status: str = "SUCCEEDED") -> None:
    request = root / "request.json"
    result = root / "result.json"
    state.save(request, {"operation": "test"})
    state.save(result, {"status": status})
    state.append_event(
        root, {"event": "STARTED", "name": "test", "request": state.identity(request)}
    )
    state.append_event(
        root,
        {
            "event": status,
            "name": "test",
            "value": {"status": status},
            "artifacts": [state.identity(result)],
        },
    )


def test_successful_resume_is_read_only(tmp_path: Path) -> None:
    record_step(tmp_path)
    before = (tmp_path / "events.jsonl").read_bytes()
    assert state.completed_steps(tmp_path)["test"]["status"] == "SUCCEEDED"
    assert (tmp_path / "events.jsonl").read_bytes() == before


def test_failed_attempt_is_never_replayed(tmp_path: Path) -> None:
    record_step(tmp_path, "FAILED")
    with pytest.raises(ValueError, match="new namespace"):
        state.completed_steps(tmp_path)


def test_uncertain_started_is_never_replayed(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    state.save(request, {})
    state.append_event(
        tmp_path, {"event": "STARTED", "name": "test", "request": state.identity(request)}
    )
    with pytest.raises(ValueError, match="uncertain STARTED"):
        state.completed_steps(tmp_path)


def test_artifact_mutation_blocks_resume(tmp_path: Path) -> None:
    record_step(tmp_path)
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact changed"):
        state.completed_steps(tmp_path)


def test_hash_chain_mutation_blocks_resume(tmp_path: Path) -> None:
    record_step(tmp_path)
    path = tmp_path / "events.jsonl"
    path.write_text(path.read_text().replace('"operation":', '"changed":') + " ")
    # Change a retained event byte without updating the next row's hash.
    path.write_text(path.read_text().replace('"event": "STARTED"', '"event":  "STARTED"'))
    with pytest.raises(ValueError, match="hash chain"):
        state.completed_steps(tmp_path)


def test_exclusive_lock_never_adopts_existing_owner(tmp_path: Path) -> None:
    with state.lock(tmp_path), pytest.raises(FileExistsError), state.lock(tmp_path):
        pytest.fail("must not acquire twice")
    assert not (tmp_path / "owner.lock").exists()


def test_bundle_excludes_media_and_enforces_small_text_cap(tmp_path: Path) -> None:
    (tmp_path / "native.mov").write_bytes(b"not media, but excluded by suffix")
    (tmp_path / "result.json").write_text('{"status":"FAILED"}')
    (tmp_path / "stderr.txt").write_text("x" * 100000)
    output = tmp_path / "bundle.zip"
    result = app.diagnostic_bundle(tmp_path, output)
    with zipfile.ZipFile(output) as archive:
        assert "native.mov" not in archive.namelist()
        assert "result.json" in archive.namelist()
        assert b"EXCERPT" in archive.read("stderr.txt")
    assert result["uncompressed_bytes"] <= 2 * 1024**2


def test_optional_backend_statuses_are_independent() -> None:
    qualification = {
        "backends": {"transfer": {"status": "FAILED"}, "blur": {"status": "SUCCEEDED"}}
    }
    assert not app.backend_passed(qualification, "transfer")
    assert app.backend_passed(qualification, "blur")
    assert not app.backend_passed(qualification, "prores")


def test_optional_vulkan_failure_does_not_block_cpu_or_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    workload = {"id": "speech", "kind": "short", "start": 25.0, "duration": 0.1, "frames": 6}

    def fake_invoke(
        config: dict[str, Any], name: str, request: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        calls.append(name)
        if name == "audio-plan":
            return {"status": "SUCCEEDED", "workloads": [workload]}
        if name == "backend-qualification":
            return {"status": "FAILED", "backends": {"transfer": {"status": "FAILED"}}}
        if name.startswith("finish-qualify-"):
            return {"status": "SUCCEEDED", "passed": True}
        return {"status": "SUCCEEDED", "output": "reference.mov"}

    monkeypatch.setattr(app, "invoke", fake_invoke)
    monkeypatch.setattr(app, "skip", lambda *args: {"status": "SKIPPED"})
    config: dict[str, Any] = {
        "selected": {
            "tools": {
                "ffmpeg": {"path": "ffmpeg", "sha256": "1"},
                "ffprobe": {"path": "ffprobe", "sha256": "2"},
            }
        },
        "installed": None,
        "smoke": False,
        "preflight_only": False,
        "production32": False,
        "full": False,
        "cuda": True,
        "cuda_environment": {"version": "pinned"},
        "cuda_python": "python",
    }
    app.execute(config, {})
    assert calls.index("backend-qualification") < calls.index("speech-cpu-selected")
    assert "speech-cuda-r01-B" in calls
    assert calls.index("finish-qualify-cuda") < calls.index("speech-cuda-r01-B")
    assert [name for name in calls if name.startswith("speech-cuda-r")] == [
        "speech-cuda-r01-A",
        "speech-cuda-r01-B",
        "speech-cuda-r02-B",
        "speech-cuda-r02-A",
    ]


def test_no_render_before_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        return {"status": "SUCCEEDED", "workloads": []}

    monkeypatch.setattr(app, "invoke", fake)
    app.execute({"selected": {"tools": {}}, "smoke": False, "preflight_only": True}, {})
    assert calls == ["audio-plan", "backend-qualification", "finish-qualify-numpy"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership oracle")
def test_timeout_reaps_detached_descendants(tmp_path: Path) -> None:
    pid_path = tmp_path / "child.pid"
    child_code = (
        "import os,time; from pathlib import Path; Path("
        + repr(str(pid_path))
        + ").write_text(str(os.getpid())); time.sleep(60)"
    )
    leader = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(child_code)
        + "],start_new_session=True); time.sleep(60)"
    )
    observed = run_command([sys.executable, "-c", leader], tmp_path / "logs", timeout=1)
    assert observed["error"].startswith("TimeoutError")
    assert observed["shutdown_verified"]
    pid = int(pid_path.read_text())
    assert not Path(f"/proc/{pid}").exists()


def test_list_argv_preserves_spaces_quotes_unicode_and_exit(tmp_path: Path) -> None:
    argument = 'spaces "quotes" backslash\\ and λ'
    observed = run_command(
        [
            sys.executable,
            "-c",
            "import json,sys; print(json.dumps(sys.argv[1:])); sys.exit(7)",
            argument,
        ],
        tmp_path / "argv",
        timeout=10,
    )
    assert observed["returncode"] == 7
    assert observed["shutdown_verified"]
    assert json.loads(observed["stdout"]) == [argument]


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows Job Object kernel")
def test_windows_job_timeout_has_verified_shutdown(tmp_path: Path) -> None:
    observed = run_command(
        [sys.executable, "-c", "import time; time.sleep(60)"], tmp_path / "win-job", timeout=0.5
    )
    assert observed["error"].startswith("TimeoutError")
    assert observed["shutdown_verified"]
    assert observed["supervision"] == "WINDOWS_JOB_KILL_ON_CLOSE"


def test_source_change_is_detected(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text("project")
    (tmp_path / "uv.lock").write_text("lock")
    file = tmp_path / "src/module.py"
    file.write_text("value=1")
    first = state.source_identity(tmp_path)
    file.write_text("value=2")
    assert first != state.source_identity(tmp_path)


def test_nested_output_root_is_rejected_inside_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="outside Git"):
        state.outside_git([tmp_path / "generated/nested"])


def test_marker_windows_dependency_is_conditional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert state.marker_applies("sys_platform == 'win32'")
    assert not state.marker_applies("sys_platform != 'win32'")
    with pytest.raises(ValueError, match="unsupported"):
        state.marker_applies("unknown_name == 'x'")
