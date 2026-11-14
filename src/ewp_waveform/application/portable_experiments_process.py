"""Private process-tree supervision, with no shell or optional dependencies.

Windows: a gate child cannot launch work before assignment to a kill-on-close
Job Object. The parent owns the non-inheritable job handle. Linux: a private
subreaper adopts and reaps even detached grandchildren. Never use taskkill by PID.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import math
import os
import select
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ProcessOwnershipError(RuntimeError):
    """No further dispatch is safe without authenticated process-tree shutdown."""


class ResourceAdmissionError(ValueError):
    """A supervisor monitor refused global capacity admission; do not retry implicitly."""

    def __init__(
        self, message: str, *, storage_observations: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.storage_observations = storage_observations or []


class StorageObservationError(ValueError):
    """Accounting could not establish storage usage; not proof of a limit breach."""

    def __init__(
        self, message: str, *, storage_observations: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.storage_observations = storage_observations or []


class MonitorFailureError(RuntimeError):
    """Unexpected accounting-monitor defect; dispatch must remain fenced."""


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


def supervise(argv: list[str], receipt_fd: int, parent_pid: int, gate_fd: int) -> int:
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
        # Ownership is established before READY, but work stays gated until the
        # parent has checked its launch deadline and budget. Parent death/abort
        # closes the private pipe; stdin of the actual command is unchanged.
        permitted = os.read(gate_fd, 3) == b"GO\n"
    finally:
        os.close(gate_fd)
    if not permitted or stopping or os.getppid() != parent_pid:
        os.write(receipt_fd, b"REAPED")
        return 125
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
    final_monitor: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Retain exact argv/logs and bound launch-through-exit, including READY.

    Shutdown has a separate bounded grace for the sole reaper. Missing ownership
    receipts always fail closed, even when the direct supervisor was killed.
    """
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("nonempty list[str] argv required")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("finite positive command timeout required")
    started = time.perf_counter()
    deadline = time.monotonic() + timeout
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
    gate_reader: int | None = None
    gate_writer: int | None = None
    ready = False
    error: str | None = None
    verified = False
    interrupted: BaseException | None = None
    resource_errors: list[str] = []
    storage_errors: list[str] = []
    monitor_errors: list[str] = []
    incomplete_samples = 0

    def monitor_check(*, final: bool = False) -> None:
        nonlocal incomplete_samples
        selected_monitor = final_monitor if final and final_monitor is not None else monitor
        if selected_monitor:
            try:
                sample = selected_monitor()
                if isinstance(sample, dict):
                    storage = sample.get("storage", {})
                    if storage.get("complete") is False or storage.get("incomplete_samples"):
                        # Keep real incomplete observations, including resamples that
                        # subsequently reconciled. Never present them as exact totals.
                        with (root / "storage-observations.jsonl").open("a", encoding="utf-8") as f:
                            f.write(json.dumps(sample, sort_keys=True, allow_nan=False) + "\n")
                        incomplete_samples += 1
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                target = (
                    resource_errors
                    if isinstance(exc, ResourceAdmissionError)
                    else storage_errors
                    if isinstance(exc, (StorageObservationError, OSError))
                    else monitor_errors
                )
                if detail not in target:
                    target.append(detail)
                incomplete = getattr(exc, "storage_observations", None)
                if incomplete:
                    try:
                        with (root / "storage-observations.jsonl").open("a", encoding="utf-8") as f:
                            f.write(
                                json.dumps({"error": detail, "incomplete_samples": incomplete})
                                + "\n"
                            )
                        incomplete_samples += 1
                    except OSError as evidence_error:
                        storage_errors.append(
                            f"incomplete sample retention failed: {evidence_error}"
                        )
                raise

    def failure_scope() -> str | None:
        if not verified:
            return "GLOBAL_PROCESS_OWNERSHIP"
        if resource_errors:
            return "GLOBAL_RESOURCE_ADMISSION"
        if storage_errors:
            return "GLOBAL_STORAGE_OBSERVATION"
        if monitor_errors:
            return "GLOBAL_MONITOR_FAILURE"
        return None

    def record_error(exc: BaseException) -> None:
        nonlocal error, interrupted
        detail = f"{type(exc).__name__}: {exc}"
        if error is None:
            error = detail
        elif detail not in error:
            error += "; " + detail
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            interrupted = exc

    def check() -> None:
        monitor_check(final=proc is None)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timeout after {timeout:g}s (launch-through-exit)")

    with (root / "stdout.txt").open("xb") as stdout, (root / "stderr.txt").open("xb") as stderr:
        try:
            # Admission is before *any* process creation, including private setup.
            check()
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
                check()
                assert proc.stdin is not None
                proc.stdin.write(b"GO\n")
                proc.stdin.close()
            elif sys.platform.startswith("linux"):
                reader, writer = os.pipe()
                gate_reader, gate_writer = os.pipe()
                os.set_blocking(reader, False)
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--supervise",
                        str(writer),
                        str(os.getpid()),
                        str(gate_reader),
                        *argv,
                    ],
                    pass_fds=(writer, gate_reader),
                    start_new_session=True,
                    **kwargs,
                )
                os.close(writer)
                writer = None
                os.close(gate_reader)
                gate_reader = None
                receipt = b""
                while receipt != b"READY\n":
                    check()
                    if proc.poll() is not None:
                        raise RuntimeError(
                            "private supervisor exited before READY; no work launched"
                        )
                    readable, _, _ = select.select(
                        [reader], [], [], min(0.05, max(0, deadline - time.monotonic()))
                    )
                    if not readable:
                        continue
                    part = os.read(reader, 6 - len(receipt))
                    receipt += part
                    if not part or not b"READY\n".startswith(receipt):
                        raise RuntimeError(
                            "private supervisor did not become ready; no work launched"
                        )
                ready = True
                check()
                os.write(gate_writer, b"GO\n")
                os.close(gate_writer)
                gate_writer = None
            else:
                raise RuntimeError("only Linux/WSL and native Windows supervision are supported")
            while True:
                # Check before terminal polling as well: a fast successful writer
                # must not skip budget/deadline admission between samples.
                check()
                if proc.poll() is not None:
                    break
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        except BaseException as exc:
            record_error(exc)
        finally:
            for descriptor in (writer, gate_reader, gate_writer):
                if descriptor is not None:
                    os.close(descriptor)
            if job is not None:
                try:
                    job.close()
                    verified = True
                except BaseException as exc:
                    record_error(exc)
            if proc is not None:
                try:
                    if proc.poll() is None:
                        if os.name == "nt":
                            proc.kill()  # Gated assignment failure, or already empty job.
                        elif not ready:
                            # Startup has not established ownership. GO was never
                            # sent, so no command can have launched; don't wait on
                            # a stalled/TERM-ignoring interpreter startup hook.
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.terminate()  # Sole reaper owns detached descendants.
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # A broken supervisor cannot hold the caller indefinitely.
                        # Killing its session is NOT an ownership receipt.
                        if os.name == "nt":
                            proc.kill()
                        else:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=1)
                except BaseException as exc:
                    record_error(exc)
                    verified = False
                finally:
                    if proc.stdin is not None:
                        try:
                            proc.stdin.close()
                        except OSError as exc:
                            record_error(exc)
                    if reader is not None:
                        # Never wait for EOF: an inherited writer could remain open.
                        try:
                            receipt = os.read(reader, 32)
                        except BlockingIOError:
                            receipt = b""
                        finally:
                            os.close(reader)
                        verified = ready and proc.returncode is not None and receipt == b"REAPED"
                if not verified:
                    error = (error or "") + "; ownership shutdown UNVERIFIED; no replay"
            else:
                if reader is not None:
                    os.close(reader)
                verified = True  # No process was created.
    try:
        # Tree shutdown can itself retain output beyond the last live sample.
        monitor_check(final=True)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timeout after {timeout:g}s (launch-through-exit)")
    except BaseException as exc:
        record_error(exc)
    value = {
        "argv": argv,
        "returncode": proc.returncode if proc else None,
        "error": error,
        "shutdown_verified": verified,
        "resource_refused": bool(resource_errors),
        "resource_errors": resource_errors,
        "storage_observation_failed": bool(storage_errors),
        "storage_observation_errors": storage_errors,
        "monitor_failed": bool(monitor_errors),
        "monitor_errors": monitor_errors,
        "incomplete_storage_samples": incomplete_samples,
        "failure_scope": failure_scope(),
        "wall_seconds": time.perf_counter() - started,
        "stdout": tail_text(root / "stdout.txt"),
        "stderr": tail_text(root / "stderr.txt"),
        "logs": str(root),
        "supervision": "WINDOWS_JOB_KILL_ON_CLOSE"
        if os.name == "nt"
        else "LINUX_PRIVATE_SUBREAPER",
    }
    (root / "result.json").write_text(json.dumps(value, indent=2))
    try:
        monitor_check(final=True)  # Include retained command/result logs, not just payload.
    except BaseException as exc:
        record_error(exc)
        value["error"] = error
        value["resource_refused"] = bool(resource_errors)
        value["storage_observation_failed"] = bool(storage_errors)
        value["monitor_failed"] = bool(monitor_errors)
        value["failure_scope"] = failure_scope()
        (root / "result.json").write_text(json.dumps(value, indent=2))
    # A final reconciliation can observe an incomplete-then-complete scan too.
    if value["incomplete_storage_samples"] != incomplete_samples:
        value["incomplete_storage_samples"] = incomplete_samples
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
        raise SystemExit(
            supervise(sys.argv[5:], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
        )
    raise SystemExit(2)
