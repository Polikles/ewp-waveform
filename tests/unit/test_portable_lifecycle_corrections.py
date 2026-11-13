"""Focused lifecycle regressions; private fixtures, no rendering or shared installs."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments_process as process
from ewp_waveform.application import portable_experiments_state as state


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux supervisor startup")
def test_ready_handshake_is_inside_launch_deadline(tmp_path: Path) -> None:
    startup = tmp_path / "startup"
    startup.mkdir()
    pid_path = tmp_path / "supervisor.pid"
    marker = tmp_path / "work-launched"
    (startup / "sitecustomize.py").write_text(
        "import os,time\n"
        "from pathlib import Path\n"
        f"Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(1.5)\n"
    )
    started = time.monotonic()
    observed = process.run_command(
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        tmp_path / "logs",
        timeout=0.2,
        env={**os.environ, "PYTHONPATH": str(startup)},
    )
    assert time.monotonic() - started < 1.0
    assert observed["error"].startswith("TimeoutError")
    assert "UNVERIFIED; no replay" in observed["error"]
    assert not observed["shutdown_verified"]  # No authenticated subreaper receipt.
    assert not marker.exists()
    assert not Path(f"/proc/{int(pid_path.read_text())}").exists()
    assert json.loads((tmp_path / "logs/result.json").read_text()) == observed


def test_budget_admission_precedes_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise ValueError("budget already exceeded")

    monkeypatch.setattr(process.subprocess, "Popen", lambda *a, **k: pytest.fail("launched"))
    observed = process.run_command(
        [sys.executable, "-c", "pass"], tmp_path / "logs", monitor=refuse
    )
    assert "budget already exceeded" in observed["error"]
    assert observed["returncode"] is None
    assert observed["shutdown_verified"]


def test_fast_terminal_growth_is_checked_after_shutdown(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    samples: list[int] = []

    def monitor() -> None:
        size = payload.stat().st_size if payload.exists() else 0
        samples.append(size)
        if size > 1024:
            raise ValueError("terminal growth crossed")

    observed = process.run_command(
        [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(payload)!r}).write_bytes(b'x'*8192)",
        ],
        tmp_path / "logs",
        monitor=monitor,
    )
    assert "terminal growth crossed" in observed["error"]
    assert observed["shutdown_verified"]
    assert samples[0] == 0 and samples[-1] == 8192


def test_result_log_growth_is_checked_before_success(tmp_path: Path) -> None:
    root = tmp_path / "logs"

    def monitor() -> None:
        if (root / "result.json").exists():
            raise ValueError("retained log budget crossed")

    observed = process.run_command([sys.executable, "-c", "pass"], root, monitor=monitor)
    assert observed["shutdown_verified"]
    assert "retained log budget crossed" in observed["error"]
    assert json.loads((root / "result.json").read_text()) == observed


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux pipe descriptors")
def test_failed_process_creation_closes_all_private_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptors = []
    real_pipe = os.pipe

    def pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("private launch refused")

    monkeypatch.setattr(process.os, "pipe", pipe)
    monkeypatch.setattr(process.subprocess, "Popen", refuse)
    observed = process.run_command([sys.executable, "-c", "pass"], tmp_path / "logs")
    assert observed["shutdown_verified"] and observed["returncode"] is None
    assert "private launch refused" in observed["error"]
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_terminal_poll_cannot_skip_elapsed_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Advance a private clock exactly when poll first observes exit; the command
    # never needs to remain alive for a watchdog sample to establish the crossing.
    clock = [time.monotonic()]
    real_popen = process.subprocess.Popen

    def popen(*args: Any, **kwargs: Any) -> Any:
        proc = real_popen(*args, **kwargs)
        real_poll = proc.poll

        def poll() -> int | None:
            status = real_poll()
            if status is not None:
                clock[0] += 20
            return status

        proc.poll = poll
        return proc

    monkeypatch.setattr(process.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(process.subprocess, "Popen", popen)
    observed = process.run_command([sys.executable, "-c", "pass"], tmp_path / "logs", timeout=10)
    assert observed["error"].startswith("TimeoutError")
    assert observed["shutdown_verified"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux receipt pipe")
def test_partial_ready_reads_preserve_shutdown_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = os.read

    def read(descriptor: int, maximum: int) -> bytes:
        return real_read(descriptor, min(2, maximum) if maximum <= 6 else maximum)

    monkeypatch.setattr(process.os, "read", read)
    observed = process.run_command([sys.executable, "-c", "pass"], tmp_path / "logs")
    assert observed["error"] is None
    assert observed["shutdown_verified"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux launch gate")
def test_budget_refusal_after_ready_never_releases_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = os.read
    ready = False
    marker = tmp_path / "must-not-launch"

    def read(descriptor: int, maximum: int) -> bytes:
        nonlocal ready
        result = real_read(descriptor, maximum)
        if result == b"READY\n":
            ready = True
        return result

    def monitor() -> None:
        if ready:
            raise ValueError("budget crossed during startup")

    monkeypatch.setattr(process.os, "read", read)
    observed = process.run_command(
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        tmp_path / "logs",
        monitor=monitor,
    )
    assert "budget crossed during startup" in observed["error"]
    assert observed["shutdown_verified"]
    assert not marker.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux receipt pipe")
@pytest.mark.parametrize("ready", [False, True])
def test_exited_supervisor_with_still_open_receipt_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    # Retain a duplicate writer in the parent: EOF is unavailable after the child
    # exits, reproducing an inherited writer without leaving a sleeping process.
    real_pipe = os.pipe
    held: list[int] = []

    def pipe() -> tuple[int, int]:
        reader, writer = real_pipe()
        if not held:
            held.append(os.dup(writer))
        return reader, writer

    real_popen = process.subprocess.Popen

    def popen(argv: list[str], **kwargs: Any) -> Any:
        if "--supervise" in argv:
            argv = (
                [
                    sys.executable,
                    "-c",
                    "import os,time,sys; os.write(int(sys.argv[1]), b'READY\\n'); time.sleep(0.05)",
                    argv[3],
                ]
                if ready
                else [sys.executable, "-c", "pass"]
            )
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(process.os, "pipe", pipe)
    monkeypatch.setattr(process.subprocess, "Popen", popen)
    try:
        started = time.monotonic()
        observed = process.run_command(
            [sys.executable, "-c", "pass"], tmp_path / "logs", timeout=0.2
        )
        assert time.monotonic() - started < 1.0
        assert not observed["shutdown_verified"]
        assert "no replay" in observed["error"]
    finally:
        for descriptor in held:
            os.close(descriptor)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux supervisor shutdown")
def test_stalled_ready_supervisor_has_bounded_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = tmp_path / "stalled_supervisor.py"
    pid_path = tmp_path / "supervisor.pid"
    supervisor.write_text(
        "import os,signal,sys,time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "os.write(int(sys.argv[1]), b'READY\\n')\n"
        "time.sleep(60)\n"
    )
    real_popen = process.subprocess.Popen

    def popen(argv: list[str], **kwargs: Any) -> Any:
        return real_popen([sys.executable, str(supervisor), argv[3]], **kwargs)

    monkeypatch.setattr(process.subprocess, "Popen", popen)
    started = time.monotonic()
    observed = process.run_command([sys.executable, "-c", "pass"], tmp_path / "logs", timeout=0.2)
    assert time.monotonic() - started < 4.5
    assert observed["error"].startswith("TimeoutError")
    assert not observed["shutdown_verified"]
    assert "UNVERIFIED; no replay" in observed["error"]
    assert not Path(f"/proc/{int(pid_path.read_text())}").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper oracle")
def test_normal_exit_reaps_detached_sigterm_ignoring_child(tmp_path: Path) -> None:
    pid_path = tmp_path / "detached.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    leader = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
        f"Path({str(pid_path)!r}).write_text(str(p.pid)); time.sleep(0.1)"
    )
    observed = process.run_command([sys.executable, "-c", leader], tmp_path / "logs", timeout=5)
    assert observed["returncode"] == 0 and observed["error"] is None
    assert observed["shutdown_verified"]
    assert not Path(f"/proc/{int(pid_path.read_text())}").exists()


@pytest.mark.parametrize("refused", [False, True])
def test_windows_job_assignment_still_precedes_gate_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: bool
) -> None:
    """Python orchestration only; not a native Windows kernel qualification."""
    order: list[str] = []

    class Input:
        def write(self, data: bytes) -> None:
            assert data == b"GO\n"
            order.append("GO")

        def close(self) -> None:
            pass

    class Proc:
        stdin = Input()
        returncode: int | None = None if refused else 0

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            order.append("kill")
            self.returncode = 125

        def wait(self, timeout: float) -> int | None:
            assert timeout > 0
            return self.returncode

    class Job:
        def assign(self, proc: Proc) -> None:
            order.append("assign")
            if refused:
                raise OSError("assignment refused")

        def close(self) -> None:
            order.append("job-close")

    monkeypatch.setattr(process, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(process, "WindowsJob", Job)
    monkeypatch.setattr(process.subprocess, "Popen", lambda *a, **k: Proc())
    observed = process.run_command([sys.executable, "-c", "pass"], tmp_path / "logs")
    assert observed["shutdown_verified"]
    if refused:
        assert "GO" not in order and "kill" in order
        assert "assignment refused" in observed["error"]
    else:
        assert order.index("assign") < order.index("GO") < order.index("job-close")
        assert observed["error"] is None


@pytest.fixture
def private_distribution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    site = tmp_path / "site"
    package = site / "private_lifecycle"
    package.mkdir(parents=True)
    metadata = site / "private_lifecycle-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: private-lifecycle\nVersion: 1.0\n"
    )
    for name in ("module.py", "native.so", "native.dll", "native.pyd", "data.bin"):
        (package / name).write_bytes(b"original installed payload\n")
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-312.pyc").write_bytes(b"mutable cache")
    rows = []
    for file in sorted(site.rglob("*")):
        if file.is_file():
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(file.read_bytes()).digest())
                .decode()
                .rstrip("=")
            )
            rows.append(
                [file.relative_to(site).as_posix(), "sha256=" + digest, str(file.stat().st_size)]
            )
    rows.append(["private_lifecycle-1.0.dist-info/RECORD", "", ""])
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    (metadata / "RECORD").write_text(stream.getvalue())
    dist = importlib.metadata.PathDistribution(metadata)
    monkeypatch.setattr(state.importlib.metadata, "distributions", lambda: iter([dist]))
    root = tmp_path / "project"
    root.mkdir()
    (root / "uv.lock").write_text('[[package]]\nname = "ewp-waveform"\nversion = "0.0.0"\n')
    return root, package


@pytest.mark.parametrize(
    "filename", ["module.py", "native.so", "native.dll", "native.pyd", "data.bin"]
)
def test_record_unchanged_payload_mutation_is_refused(
    private_distribution: tuple[Path, Path], filename: str
) -> None:
    root, package = private_distribution
    first = state.environment_details(root)
    assert first == state.environment_details(root)
    record = next(package.parent.glob("*.dist-info/RECORD"))
    original_record = record.read_bytes()
    (package / filename).write_bytes(b"modified installed payload\n")
    assert record.read_bytes() == original_record
    with pytest.raises(ValueError, match="installed distribution payload changed"):
        state.environment_details(root)


def test_unhashed_record_entry_is_still_fingerprinted(
    private_distribution: tuple[Path, Path],
) -> None:
    root, package = private_distribution
    record = next(package.parent.glob("*.dist-info/RECORD"))
    rows = list(csv.reader(io.StringIO(record.read_text())))
    for row in rows:
        if row[0].endswith("module.py"):
            row[1:] = ["", ""]
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    record.write_text(stream.getvalue())
    first = state.environment_details(root)
    (package / "module.py").write_bytes(b"changed without recorded hash")
    assert first != state.environment_details(root)


def test_mutable_bytecode_is_excluded(private_distribution: tuple[Path, Path]) -> None:
    root, package = private_distribution
    first = state.environment_details(root)
    (package / "__pycache__/module.cpython-312.pyc").write_bytes(b"regenerated")
    (package / "__pycache__/unrecorded.pyc").write_bytes(b"new cache")
    assert first == state.environment_details(root)


def test_missing_recorded_payload_fails_closed(private_distribution: tuple[Path, Path]) -> None:
    root, package = private_distribution
    (package / "native.so").unlink()
    with pytest.raises(ValueError, match="installed distribution payload missing"):
        state.environment_details(root)
