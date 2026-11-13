"""Private process-tree supervision, with no shell or optional dependencies.

Windows: a gate child cannot launch work before assignment to a kill-on-close
Job Object. The parent owns the non-inheritable job handle. Linux: a private
subreaper adopts and reaps even detached grandchildren. Never use taskkill by PID.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


def windows_last_error() -> int:
    return int(getattr(ctypes, "get_last_error", ctypes.get_errno)())


class WindowsJob:
    """Real kernel Job Object; fail closed if assignment is prohibited."""

    def __init__(self) -> None:
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.api: Any = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        for name, restype, args in (
            ("CreateJobObjectW", w.HANDLE, [ctypes.c_void_p, w.LPCWSTR]),
            ("SetInformationJobObject", w.BOOL, [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]),
            ("AssignProcessToJobObject", w.BOOL, [w.HANDLE, w.HANDLE]),
            ("TerminateJobObject", w.BOOL, [w.HANDLE, w.UINT]),
            (
                "QueryInformationJobObject",
                w.BOOL,
                [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p],
            ),
            ("CloseHandle", w.BOOL, [w.HANDLE]),
        ):
            fn = getattr(self.api, name)
            fn.restype, fn.argtypes = restype, args
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(windows_last_error(), "CreateJobObjectW failed")
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.api.CloseHandle(self.handle)
            raise OSError(windows_last_error(), "SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen[bytes]) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, int(proc._handle)):  # type: ignore[attr-defined]
            raise OSError(
                windows_last_error(),
                "Job Object assignment refused; no work launched",
            )

    def close(self) -> None:
        if not self.handle:
            return
        try:
            if not self.api.TerminateJobObject(self.handle, 125):
                raise OSError(windows_last_error(), "TerminateJobObject failed")
            # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four 64-bit times, then DWORDs.
            data = ctypes.create_string_buffer(48)
            deadline = time.monotonic() + 15
            while True:
                if not self.api.QueryInformationJobObject(self.handle, 1, data, len(data), None):
                    raise OSError(windows_last_error(), "Job Object accounting unavailable")
                active = ctypes.c_uint32.from_buffer(data, 40).value
                if active == 0:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Job Object shutdown UNVERIFIED; no replay")
                time.sleep(0.02)
        finally:
            self.api.CloseHandle(self.handle)
            self.handle = None


def supervise(argv: list[str], receipt_fd: int, parent_pid: int) -> int:
    """Linux-only sole reaper, private to one bounded command."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0):  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "parent-death supervision unavailable")
    if libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "private subreaper unavailable")
    stopping = False

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    children.read_text()
    if os.getppid() != parent_pid:
        return 125  # Parent died before the private handshake; launch no work.
    os.write(receipt_fd, b"READY\n")
    try:
        proc = subprocess.Popen(argv)
    except OSError:
        traceback.print_exc()
        os.write(receipt_fd, b"REAPED")
        return 127
    result: int | None = None
    deadline: float | None = None
    while True:
        owned = list(map(int, children.read_text().split()))
        if stopping or result is not None:
            if deadline is None:
                deadline = time.monotonic() + 1
            for pid in owned:
                # Unreaped direct children cannot have their PID recycled.
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM if time.monotonic() < deadline else signal.SIGKILL)
        for pid in owned:
            if pid == proc.pid:
                status = proc.poll()
                if status is not None:
                    result = status
            else:
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)
        if result is not None and not children.read_text().strip():
            os.write(receipt_fd, b"REAPED")
            os.close(receipt_fd)
            return result if result >= 0 else 128 - result
        time.sleep(0.02)


def tail_text(path: Path, maximum: int = 16000) -> str:
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - maximum))
        return stream.read(maximum).decode("utf-8", errors="replace")


def run_command(
    argv: list[str],
    root: Path,
    *,
    timeout: float = 60,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    monitor: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Retain exact argv/stdout/stderr; return after verified tree shutdown."""
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("nonempty list[str] argv required")
    root.mkdir(parents=True, exist_ok=False)
    (root / "command.json").write_text(
        json.dumps(
            {"argv": argv, "timeout_seconds": timeout, "cwd": str(cwd) if cwd else None}, indent=2
        )
    )
    proc: subprocess.Popen[bytes] | None = None
    job: WindowsJob | None = None
    reader: int | None = None
    writer: int | None = None
    error: str | None = None
    verified = False
    started = time.perf_counter()
    interrupted: BaseException | None = None
    with (root / "stdout.txt").open("xb") as stdout, (root / "stderr.txt").open("xb") as stderr:
        try:
            kwargs: dict[str, Any] = {
                "stdout": stdout,
                "stderr": stderr,
                "env": env,
                "cwd": cwd,
                "shell": False,
            }
            if os.name == "nt":
                job = WindowsJob()
                proc = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--gate", *argv],
                    stdin=subprocess.PIPE,
                    **kwargs,
                )
                job.assign(proc)
                assert proc.stdin is not None
                proc.stdin.write(b"GO\n")
                proc.stdin.close()
            elif sys.platform.startswith("linux"):
                reader, writer = os.pipe()
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--supervise",
                        str(writer),
                        str(os.getpid()),
                        *argv,
                    ],
                    pass_fds=(writer,),
                    start_new_session=True,
                    **kwargs,
                )
                os.close(writer)
                writer = None
                if os.read(reader, 6) != b"READY\n":
                    raise RuntimeError("private supervisor did not become ready; no work launched")
            else:
                raise RuntimeError("only Linux/WSL and native Windows supervision are supported")
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if monitor:
                    monitor()
                if time.monotonic() > deadline:
                    raise TimeoutError(f"timeout after {timeout:g}s")
                time.sleep(0.1)
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                interrupted = exc
        finally:
            if writer is not None:
                os.close(writer)
            if job is not None:
                job.close()
                verified = True
            if proc is not None:
                if proc.poll() is None:
                    if os.name == "nt":
                        proc.kill()  # Suspended/gated failed assignment, or already empty job.
                    else:
                        proc.terminate()  # Private subreaper cleans all descendants before exiting.
                proc.wait(timeout=20)
                if reader is not None:
                    verified = os.read(reader, 32) == b"REAPED"
                    os.close(reader)
                    if not verified:
                        error = (error or "") + "; ownership shutdown UNVERIFIED; no replay"
            else:
                verified = True  # No process was created.
    value = {
        "argv": argv,
        "returncode": proc.returncode if proc else None,
        "error": error,
        "shutdown_verified": verified,
        "wall_seconds": time.perf_counter() - started,
        "stdout": tail_text(root / "stdout.txt"),
        "stderr": tail_text(root / "stderr.txt"),
        "logs": str(root),
        "supervision": "WINDOWS_JOB_KILL_ON_CLOSE"
        if os.name == "nt"
        else "LINUX_PRIVATE_SUBREAPER",
    }
    (root / "result.json").write_text(json.dumps(value, indent=2))
    if interrupted:
        raise interrupted
    return value


if __name__ == "__main__":
    if sys.argv[1] == "--gate":
        if sys.stdin.buffer.readline() != b"GO\n":
            raise SystemExit(125)
        raise SystemExit(subprocess.call(sys.argv[2:], shell=False))
    if sys.argv[1] == "--supervise":
        raise SystemExit(supervise(sys.argv[4:], int(sys.argv[2]), int(sys.argv[3])))
    raise SystemExit(2)
