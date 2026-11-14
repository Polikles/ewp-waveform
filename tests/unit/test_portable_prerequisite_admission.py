"""User-facing prerequisite admission precedes isolated runtime downloads."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_dependencies as deps


def test_missing_ffmpeg_explains_platform_install_and_exact_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = app.parser().parse_args(["--cpu-smoke"])
    args._rerun = ["scripts/run_experiments.py", "--cpu-smoke"]
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    monkeypatch.setattr(
        deps, "linux_package_command", lambda name: f"sudo apt-get install -y {name}"
    )
    with pytest.raises(ValueError) as caught:
        app.prerequisite_admission(args)
    text = str(caught.value)
    assert "ffmpeg/ffprobe" in text.lower() and "required" in text
    assert "sudo apt-get install -y ffmpeg" in text
    assert "new terminal" in text.lower()
    assert "scripts/run_experiments.py --cpu-smoke" in text


def test_missing_git_is_rejected_before_runtime_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(shutil, "which", lambda *a: None)
    monkeypatch.setattr(
        app, "original_inventory", lambda *a: pytest.fail("inventory before prerequisites")
    )
    monkeypatch.setattr(
        app, "select_python", lambda *a, **k: pytest.fail("download before prerequisites")
    )
    monkeypatch.setattr(
        deps, "linux_package_command", lambda name: f"sudo apt-get install -y {name}"
    )
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    text = capsys.readouterr().out
    assert "Git" in text and "sudo apt-get install -y git" in text
    assert "Exact command afterward" in text


def test_setup_only_runtime_does_not_require_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    args = app.parser().parse_args(["--setup-only"])
    args._rerun = ["scripts/run_experiments.py", "--setup-only"]
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    app.prerequisite_admission(args)


def test_mismatched_explicit_pair_rejected_before_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "dependency_action", lambda *a: pytest.fail("setup called"))
    with pytest.raises(SystemExit) as caught:
        app.main(["--setup-only", "--ffmpeg", str(tmp_path / "ffmpeg")])
    assert caught.value.code == 2


def test_bad_tool_inventory_precedes_runtime_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    args = app.parser().parse_args(["--cpu-smoke"])
    args._rerun = ["scripts/run_experiments.py", "--cpu-smoke"]
    monkeypatch.setattr(app, "choose_tools", lambda *a: (None, None, None))
    monkeypatch.setattr(app, "select_python", lambda *a, **k: pytest.fail("runtime acquisition"))
    monkeypatch.setattr(
        deps, "linux_package_command", lambda name: f"sudo apt-get install -y {name}"
    )
    with pytest.raises(ValueError, match="sudo apt-get install -y ffmpeg"):
        app.freeze(args, run, media, {})


def test_windows_missing_pair_offers_same_workflow_not_package_investigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = deps.tool_advice(
        ["scripts/run_experiments.py", "--cpu-smoke"],
        windows=True,
    )
    assert "--prepare-ffmpeg" in text
    assert "No new terminal" in text
    assert "py" in text
    assert "isolated" in text


def test_retained_managed_attempt_is_recovered_without_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / "managed"
    request = deps.request_key(app.ROOT, "runtime")
    env = store / "attempts" / deps.digest(request) / "failed-attempt" / "env"
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture interpreter; not executed")
    evidence = tmp_path / "dependency-check"
    evidence.mkdir()
    recorded: list[Path] = []

    def probe(candidate: Path, folder: Path, **kwargs: Any) -> dict[str, Any]:
        recorded.append(candidate)
        return {"binary": {"fixture": True}, "version": "3.12 fixture"}

    monkeypatch.setattr(deps, "outside_git", lambda *a: None)
    result = deps.discover_environment(store, app.ROOT, "runtime", evidence, probe)
    assert result is not None and result[0] == python
    assert recorded == [python]
    assert result[2]["discovered"]
    assert python.read_bytes() == b"fixture interpreter; not executed"


def test_legacy_pinned_ffmpeg_is_verified_in_place_without_download_or_old_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    from ewp_waveform.ffmpeg import portable_tools

    old = tmp_path / "run-old" / "ffmpeg-tools" / "fixture-build"
    bindir = old / "bin"
    bindir.mkdir(parents=True)
    hashes = {}
    for name in ("ffmpeg.exe", "ffprobe.exe", "avcodec.dll"):
        content = ("pinned transport fixture " + name).encode()
        (bindir / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    lock = {
        "archive_root": "fixture-build",
        "bin_sha256": hashes,
        "build_version": "fixture",
        "sha256": "not-an-archive",
        "url": "https://invalid.test",
    }
    monkeypatch.setattr(portable_tools, "read_lock", lambda: lock)
    monkeypatch.setattr(portable_tools, "_download", lambda *a: pytest.fail("network access"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in bindir.iterdir()}
    managed = tmp_path / "managed" / "ffmpeg" / "lock-key"
    selected = deps.prepared_ffmpeg_root(tmp_path, managed, [])
    assert selected == old.parent
    assert portable_tools.acquire_windows(selected, allow_download=False)["reused"]
    assert not managed.exists()
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in bindir.iterdir()}
    (bindir / "avcodec.dll").write_bytes(b"changed")
    problems: list[dict[str, Any]] = []
    assert deps.prepared_ffmpeg_root(tmp_path, managed, problems) == managed
    assert problems and "checksum mismatch" in problems[0]["error"]
