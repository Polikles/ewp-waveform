#!/usr/bin/env python3
"""One-command, stdlib-first startup for the opt-in WSL experiment suite.

Default: one installed-tool FULL reference, then the complete distributed matrix
except FULL using selected tools. No activation, environment variables, private
configuration or source pin is needed. --build-ffmpeg permits an isolated build
only if the selected pair lacks advertised GPU capabilities; it never forces a
rebuild or installs dependencies/drivers. --cpu-smoke is a tiny synthetic CPU
workflow, NOT the authenticated reference or target GPU qualification.

All startup logic lives here. Rendering, admission, validation and suite recovery
remain application APIs, called by this script in the selected Python 3.12.
"""

from __future__ import annotations

import argparse
import ast
import ctypes
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time
import traceback
import uuid
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path.home() / ".local/state/ewp-waveform-experiments"
OWNERSHIP_RECEIPTS: dict[int, int] = {}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def note_error(exc: BaseException, note: str) -> None:
    # Exception.add_note is 3.11+, but bootstrap discovery supports Python 3.10.
    exc.__dict__.setdefault("__notes__", []).append(note)


def identity(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def verify(item: dict[str, Any]) -> None:
    path = Path(item["path"])
    actual = identity(path)
    if path.is_symlink() or any(actual[key] != item[key] for key in actual):
        raise ValueError(f"frozen artifact changed: {path}")


def save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return cast(dict[str, Any], value)


@contextmanager
def interrupt_signals() -> Iterator[None]:
    """Direct parent TERM and INT follow the same cleanup path, not os._exit."""

    def interrupted(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt(signal.Signals(signum).name)

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def pidfd_api(libc: Any) -> tuple[Callable[..., int], Callable[..., int]]:
    """Prefer stdlib kernel wrappers; older libc may lack its own wrappers."""
    open_fd = getattr(os, "pidfd_open", None)
    if open_fd is None:
        open_fd = libc.pidfd_open
    python_send = getattr(signal, "pidfd_send_signal", None)
    if python_send is None:
        send_fd = libc.pidfd_send_signal
    else:

        def send_fd(fd: int, sig: int, info: Any, flags: int) -> int:
            python_send(fd, sig, info, flags)
            return 0

    return open_fd, send_fd


def supervisor(argv: list[str], receipt_fd: int) -> int:
    """Private Linux subreaper. Its ONLY descendants belong to this invocation.

    setsid does not escape this ancestry. Reparented orphans are adopted here;
    pidfds bind signals to generations, never a reused PID or unrelated group.
    Do not exit (and permit report/unlock) until every owned child is reaped.
    """
    if not sys.platform.startswith("linux"):
        raise RuntimeError("verified descendant supervision requires Linux /proc and pidfds")
    libc = ctypes.CDLL(None, use_errno=True)
    # Standalone CPython may omit os.pidfd_open despite a capable libc/kernel.
    # Resolve both wrappers before launching a child.
    pidfd_open, pidfd_signal = pidfd_api(libc)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, process-local only
        raise OSError(ctypes.get_errno(), "cannot enable private subreaper")
    stopping = False

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    children_path = Path(f"/proc/self/task/{os.getpid()}/children")
    children_path.read_text()  # Validate the kernel ownership interface before launch.
    probe = pidfd_open(os.getpid(), 0)
    if probe < 0:
        raise OSError(ctypes.get_errno(), "pidfd support required before launch")
    os.close(probe)
    # A failed launch/bookkeeping path may need to stop us immediately. Publish
    # readiness only after TERM/INT cleanup and ownership discovery are installed.
    os.write(receipt_fd, b"READY\n")
    try:
        proc = subprocess.Popen(argv)
    except OSError:
        traceback.print_exc()
        os.write(receipt_fd, b"REAPED")  # No child was created.
        os.close(receipt_fd)
        return 127
    owned: dict[int, int] = {}
    deadline: float | None = None
    result: int | None = None
    failed = False
    while True:
        try:
            # Only unreaped DIRECT children are signalled. Their PIDs cannot be
            # recycled before this sole reaper waits. Killing an ancestor adopts
            # its detached workers here, including double forks; repeat to empty.
            for pid in map(int, children_path.read_text().split()):
                if pid not in owned:
                    fd = pidfd_open(pid, 0)
                    if fd < 0:
                        raise OSError(ctypes.get_errno(), "pidfd_open owned child")
                    owned[pid] = fd
            if stopping or result is not None:
                if deadline is None:
                    deadline = time.monotonic() + 2
                sig = signal.SIGTERM if time.monotonic() < deadline else signal.SIGKILL
                for fd in owned.values():
                    if pidfd_signal(fd, sig, None, 0) < 0 and ctypes.get_errno() != 3:
                        raise OSError(ctypes.get_errno(), "pidfd_send_signal owned child")
            for pid, fd in list(owned.items()):
                if pid == proc.pid:
                    result = proc.poll()
                    reaped = result is not None
                else:
                    reaped = os.waitpid(pid, os.WNOHANG)[0] == pid
                if reaped:
                    os.close(fd)
                    del owned[pid]
            if result is not None and not owned and not children_path.read_text().strip():
                os.write(receipt_fd, b"REAPED")
                os.close(receipt_fd)
                return 125 if failed else 128 + -result if result < 0 else result
        except Exception:
            # Never abandon children on a supervisor observation error. Retain
            # the first traceback, stop, and reconcile; persistent inability to
            # observe/reap deliberately holds the owner rather than unlock early.
            if not failed:
                traceback.print_exc()
            failed = stopping = True
            deadline = 0.0
        time.sleep(0.02)


def owned_popen(
    argv: list[str], *, _owned: list[subprocess.Popen[str]], **kwargs: Any
) -> subprocess.Popen[str]:
    """Launch under owned_process's deferral; retain even a failed constructor."""
    # __init__ may fail AFTER creating the OS child. Keep the object beforehand,
    # so that failure cannot erase our only handle to the private supervisor.
    proc: subprocess.Popen[str] = subprocess.Popen.__new__(subprocess.Popen)
    reader, writer = os.pipe()
    ready = False
    try:
        try:
            subprocess.Popen.__init__(
                proc,
                [
                    sys.executable,
                    "-S",
                    str(Path(__file__).resolve()),
                    "--_supervise",
                    str(writer),
                    *argv,
                ],
                start_new_session=True,
                pass_fds=(writer,),
                **kwargs,
            )
        finally:
            os.close(writer)
        if os.read(reader, 6) != b"READY\n":
            raise RuntimeError("ownership supervisor failed before readiness")
        ready = True
        OWNERSHIP_RECEIPTS[proc.pid] = reader
        _owned.append(proc)  # Transfer before the actual Python return event.
        return proc
    except BaseException as exc:
        try:
            if getattr(proc, "pid", None) is not None:
                if not ready:
                    ready = os.read(reader, 6) == b"READY\n"
                if ready:
                    stop_owned(proc, reader=reader)
                else:
                    proc.wait()  # No READY means no stage was launched.
                    os.close(reader)
            else:
                os.close(reader)
        except Exception as cleanup_error:
            note_error(exc, f"shutdown UNVERIFIED: {cleanup_error}; no replay")
        raise


@contextmanager
def owned_process(argv: list[str], **kwargs: Any) -> Iterator[subprocess.Popen[str]]:
    """Make spawn, registration and caller cleanup one protected lifetime.

    Defer Python signal exceptions, not kernel delivery: neither the supervisor
    nor its exec'd stage inherits blocked INT/TERM. The local ownership list is
    populated inside owned_popen, so a return-event interrupt or a wrapper that
    raises before caller assignment cannot lose the handle. This scope also
    protects standalone observe/invoke, without a top-level driver registry.
    """
    owned: list[subprocess.Popen[str]] = []
    pending: list[int] = []
    launching = True

    def interrupted(signum: int, frame: Any) -> None:
        if launching:
            pending.append(signum)
        else:
            raise KeyboardInterrupt(signal.Signals(signum).name)

    previous: dict[int, Any] = {}
    try:
        for s in (signal.SIGINT, signal.SIGTERM):
            previous[s] = signal.signal(s, interrupted)
        try:
            proc = owned_popen(argv, _owned=owned, **kwargs)
            launching = False
            if pending:
                raise KeyboardInterrupt(signal.Signals(pending[0]).name)
            yield proc
        except BaseException as exc:
            launching = True
            for proc in owned:
                if proc.pid in OWNERSHIP_RECEIPTS:
                    try:
                        stop_owned(proc)
                    except Exception as cleanup_error:
                        note_error(exc, f"shutdown UNVERIFIED: {cleanup_error}; no replay")
            if pending and not isinstance(exc, KeyboardInterrupt):
                note_error(exc, f"deferred {signal.Signals(pending[0]).name} during launch")
            raise
        else:
            launching = True
            for proc in owned:
                if proc.pid in OWNERSHIP_RECEIPTS:
                    stop_owned(proc)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def verify_shutdown(proc: subprocess.Popen[str], *, reader: int | None = None) -> None:
    if reader is None:
        reader = OWNERSHIP_RECEIPTS.pop(proc.pid)
    else:
        OWNERSHIP_RECEIPTS.pop(proc.pid, None)
    try:
        if os.read(reader, 32) != b"REAPED":
            raise RuntimeError(
                "ownership shutdown UNVERIFIED; no replay; external reconciliation required"
            )
    finally:
        os.close(reader)


def stop_owned(proc: subprocess.Popen[str], *, reader: int | None = None) -> None:
    # The private supervisor escalates independently of leader/pipes. Ignore
    # further operator signals while joining; preserve the original exception.
    previous = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
        proc.wait()
        verify_shutdown(proc, reader=reader)
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def observe(
    argv: list[str],
    *,
    timeout: float = 20,
    monitor: Callable[[], None] | None = None,
    log_root: Path | None = None,
) -> dict[str, Any]:
    """Bounded observation; return only after the ownership supervisor joins."""
    try:
        with (
            interrupt_signals(),
            contextmanager_logs(log_root) as logs,
            owned_process(
                argv,
                stdout=logs[0] if logs else subprocess.PIPE,
                stderr=logs[1] if logs else subprocess.PIPE,
                text=True,
            ) as proc,
        ):
            error = None
            try:
                deadline = time.monotonic() + timeout
                while True:
                    if monitor:
                        monitor()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"timeout after {timeout} seconds")
                    try:
                        stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
                        verify_shutdown(proc)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException as exc:
                try:
                    if proc.pid in OWNERSHIP_RECEIPTS:
                        stop_owned(proc)
                except Exception as cleanup_error:
                    note_error(exc, f"shutdown UNVERIFIED: {cleanup_error}; no replay")
                    raise exc from cleanup_error
                if not isinstance(exc, (TimeoutError, ValueError)):
                    raise
                error = f"{exc}; owned process group terminated and descendants reaped"
                stdout, stderr = proc.communicate()
            return {
                "argv": argv,
                "returncode": None if error else proc.returncode,
                "stdout": stdout or "",
                "stderr": stderr or "",
                **({"error": error} if error else {}),
                "shutdown_verified": True,
                "log_root": str(log_root) if log_root else None,
            }
    except OSError as exc:
        return {"argv": argv, "returncode": None, "error": str(exc)}


@contextmanager
def contextmanager_logs(root: Path | None) -> Iterator[Any]:
    if root is None:
        yield None
    else:
        with (root / "stdout.txt").open("x") as stdout, (root / "stderr.txt").open("x") as stderr:
            yield stdout, stderr


def read_optional(path: str) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def tool_pair(directory: Path) -> dict[str, Any] | None:
    paths = [directory / name for name in ("ffmpeg", "ffprobe")]
    if not all(p.is_file() and os.access(p, os.X_OK) for p in paths):
        return None
    resolved = [p.resolve() for p in paths]
    if resolved[0].parent != resolved[1].parent or [p.name for p in resolved] != [
        "ffmpeg",
        "ffprobe",
    ]:
        return None
    return {
        name: {**identity(path), "role": "TOOL"}
        for name, path in zip(("ffmpeg", "ffprobe"), resolved, strict=True)
    }


def inventory_pair(pair: dict[str, Any]) -> dict[str, Any]:
    executable = pair["ffmpeg"]["path"]
    observations = {
        option: observe([executable, "-hide_banner", option])
        for option in ("-version", "-buildconf", "-filters", "-encoders", "-hwaccels")
    }
    observations["ffprobe-version"] = observe([pair["ffprobe"]["path"], "-version"])
    libraries: dict[str, Any] = {}
    for name in ("ffmpeg", "ffprobe"):
        record = observe(["ldd", pair[name]["path"]])
        observations["ldd-" + name] = record
        for token in record.get("stdout", "").split():
            if token.startswith("/") and Path(token).is_file():
                libraries[token] = identity(Path(token))
    return {
        "tools": pair,
        "observations": observations,
        "libraries": libraries,
        "qualification": "OBSERVED_INSTALLED_TOOLS",
        "build_receipt": None,
    }


def cgroup_inventory() -> list[dict[str, Any]]:
    """Retain actual control values at every visible membership ancestor (v1/v2)."""
    records = []
    membership = read_optional("/proc/self/cgroup") or ""
    mounts = read_optional("/proc/self/mountinfo") or ""
    controls = (
        "cpu.max",
        "cpuset.cpus",
        "cpuset.cpus.effective",
        "memory.max",
        "memory.current",
        "memory.high",
        "cpu.cfs_quota_us",
        "cpu.cfs_period_us",
        "memory.limit_in_bytes",
        "memory.usage_in_bytes",
        "cpuset.effective_cpus",
    )
    for row in mounts.splitlines():
        before, _, after = row.partition(" - ")
        fields, fs = before.split(), after.split()
        if len(fields) < 5 or len(fs) < 3 or fs[0] not in ("cgroup", "cgroup2"):
            continue
        mount = Path(fields[4].replace("\\040", " "))
        mount_root = Path(fields[3])
        for line in membership.splitlines():
            _, controllers, member = line.split(":", 2)
            if fs[0] == "cgroup2" and controllers:
                continue
            if fs[0] == "cgroup" and not set(controllers.split(",")) & set(fs[2].split(",")):
                continue
            member_path = Path(member)
            relative = (
                member_path.relative_to(mount_root)
                if member_path.is_relative_to(mount_root)
                else Path(member.lstrip("/"))
            )
            current = mount / relative
            while current.is_relative_to(mount):
                records.append(
                    {
                        "path": str(current),
                        "membership": line,
                        "filesystem": fs[0],
                        "controls": {name: read_optional(str(current / name)) for name in controls},
                    }
                )
                if current == mount:
                    break
                current = current.parent
    return records


def storage_inventory(roots: dict[str, Path]) -> dict[str, Any]:
    records = {}
    for name, requested in roots.items():
        requested = requested.expanduser().resolve()
        existing = next(p for p in (requested, *requested.parents) if p.exists())
        usage = shutil.disk_usage(existing)
        stats = os.statvfs(existing)
        records[name] = {
            "requested_path": str(requested),
            "observed_existing_ancestor": str(existing),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "available_bytes": stats.f_bavail * stats.f_frsize,
            "device": existing.stat().st_dev,
        }
    return records


def build_prerequisites(run: Path, *, compile_probe: bool) -> dict[str, Any]:
    """Observe all tools/packages; compile probes never run unless build is requested."""
    versions = {}
    problems = []
    for name in ("git", "cc", "nasm", "make", "pkg-config", "glslc"):
        executable = shutil.which(name)
        record = observe([executable, "--version"]) if executable else {"status": "NOT_FOUND"}
        versions[name] = {"path": executable, **record}
        if not executable or record.get("returncode") != 0:
            problems.append(f"provide working {name} on PATH for isolated FFmpeg build")
    packages = {}
    for name in ("vulkan", "x264"):
        executable = shutil.which("pkg-config")
        record = (
            observe([executable, "--modversion", name]) if executable else {"status": "NOT_FOUND"}
        )
        packages[name] = record
        if record.get("returncode") != 0:
            problems.append(f"provide {name} development headers/pkg-config metadata")
    probes = {}
    if compile_probe:
        folder = run / "build-prerequisites"
        folder.mkdir(mode=0o700)
        if versions["glslc"]["path"]:
            source = folder / "minimal.comp"
            source.write_text("#version 450\nlayout(local_size_x=1) in; void main() {}\n")
            probes["vulkan14_shader"] = observe(
                [
                    versions["glslc"]["path"],
                    "--target-env=vulkan1.4",
                    "--target-spv=spv1.6",
                    str(source),
                    "-o",
                    str(folder / "minimal.spv"),
                ]
            )
            if probes["vulkan14_shader"].get("returncode") != 0:
                problems.append("provide glslc supporting --target-env=vulkan1.4 and SPIR-V1.6")
        if versions["cc"]["path"]:
            source = folder / "headers.c"
            source.write_text(
                "#include <stdint.h>\n#include <vulkan/vulkan.h>\n#include <x264.h>\n"
                "#if VK_HEADER_VERSION_COMPLETE < VK_MAKE_API_VERSION(0,1,3,277)\n"
                "#error Vulkan headers must be >= 1.3.277\n#endif\n"
                "int main(void) { return 0; }\n"
            )
            flags = (
                observe([versions["pkg-config"]["path"], "--cflags", "vulkan", "x264"])
                if versions["pkg-config"]["path"]
                else {}
            )
            probes["headers"] = observe(
                [
                    versions["cc"]["path"],
                    *shlex.split(flags.get("stdout", "")),
                    "-fsyntax-only",
                    str(source),
                ]
            )
            if probes["headers"].get("returncode") != 0:
                problems.append(
                    "provide usable Vulkan >=1.3.277 and x264 C development headers; "
                    "see headers probe"
                )
    return {
        "tools": versions,
        "packages": packages,
        "probes": probes,
        "problems": problems,
        "compile_probe_requested": compile_probe,
    }


def initial_inventory() -> dict[str, Any]:
    """Must precede interpreter discovery, uv, selected PATH or application imports."""
    original_path = os.environ.get("PATH", "")
    directories = list(
        dict.fromkeys(Path(p or ".").resolve() for p in original_path.split(os.pathsep))
    )
    pairs = []
    found_tools: dict[str, list[dict[str, Any]]] = {name: [] for name in ("ffmpeg", "ffprobe")}
    seen = set()
    for directory in directories:
        for name in found_tools:
            path = directory / name
            if path.is_file() and os.access(path, os.X_OK):
                item = {**identity(path), "path_entry": str(path)}
                if item not in found_tools[name]:
                    found_tools[name].append(item)
        pair = tool_pair(directory)
        if pair and pair["ffmpeg"]["path"] not in seen:
            seen.add(pair["ffmpeg"]["path"])
            pairs.append(inventory_pair(pair))
    devices = {}
    for name, arguments in (("nvidia-smi", ["-q"]), ("vulkaninfo", ["--summary"])):
        executable = shutil.which(name)
        devices[name] = observe([executable, *arguments]) if executable else {"status": "NOT_FOUND"}
    return {
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),  # noqa: UP017 (bootstrap 3.10)
        "original_path": original_path,
        "bootstrap_python": {
            "invocation": sys.executable,
            "version": sys.version,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "binary": identity(Path(sys.executable)),
        },
        "host": {
            "platform": platform.platform(),
            "uname": list(platform.uname()),
            "cpu_count": os.cpu_count(),
            "affinity": sorted(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else None,
            "meminfo": read_optional("/proc/meminfo"),
            "cpuinfo": read_optional("/proc/cpuinfo"),
            "cgroup_membership": read_optional("/proc/self/cgroup"),
            "cgroup_ancestors": cgroup_inventory(),
            "os_release": read_optional("/etc/os-release"),
        },
        "devices": devices,
        "installed_pairs": pairs,
        "individual_tools": found_tools,
        "uv_version": observe([str(shutil.which("uv")), "--version"])
        if shutil.which("uv")
        else {"status": "NOT_FOUND"},
        "first_path_tools": {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "uv")},
    }


def outside_git(paths: list[Path], audio: Path | None = None) -> None:
    resolved = [p.resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate output roots")
    for path in resolved:
        if any((p / ".git").exists() for p in (path, *path.parents)):
            raise ValueError(f"output root must be outside Git: {path}")
        if audio and audio.resolve().is_relative_to(path):
            raise ValueError("source audio must not be inside output roots")
        if any(path != other and path.is_relative_to(other) for other in resolved):
            raise ValueError("output/accounting roots must be disjoint")


def source_identity() -> dict[str, Any]:
    def git(*args: str) -> str:
        p = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True, timeout=20
        )
        return p.stdout.strip()

    status = git("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError("clean exact source checkout required; commit candidate first: " + status)
    return {
        "checkout": str(ROOT),
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": status,
        "driver": identity(Path(__file__)),
        "lock": identity(ROOT / "uv.lock"),
        "pyproject": identity(ROOT / "pyproject.toml"),
    }


def child_env() -> dict[str, str]:
    # This is child-local, after the original inventory. Never mutate operator PATH.
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}


def lock_marker_applies(marker: str) -> bool:
    """Evaluate the committed lock's marker subset with stdlib, fail closed.

    No eval, installed packaging dependency or guessing unknown marker syntax.
    Future locks using other PEP 508 syntax require an explicit driver update.
    """
    environment = {
        "sys_platform": sys.platform,
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "platform_python_implementation": platform.python_implementation(),
        "implementation_name": sys.implementation.name,
        "implementation_version": platform.python_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_full_version": platform.python_version(),
        "extra": "",
    }

    def operand(node: ast.AST) -> str:
        if isinstance(node, ast.Name) and node.id in environment:
            return environment[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        raise ValueError(f"unsupported locked dependency marker: {marker}")

    def evaluate(node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = operand(node.left), operand(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.In):
                return left in right
            if isinstance(op, ast.NotIn):
                return left not in right
            # Numeric Python version comparisons only, never lexicographic 3.9/3.12.
            names = [n.id for n in (node.left, node.comparators[0]) if isinstance(n, ast.Name)]
            if (
                any(
                    n in {"python_version", "python_full_version", "implementation_version"}
                    for n in names
                )
                and re.fullmatch(r"\d+(\.\d+)*", left)
                and re.fullmatch(r"\d+(\.\d+)*", right)
            ):
                a, b = tuple(map(int, left.split("."))), tuple(map(int, right.split(".")))
                if isinstance(op, ast.Lt):
                    return a < b
                if isinstance(op, ast.LtE):
                    return a <= b
                if isinstance(op, ast.Gt):
                    return a > b
                if isinstance(op, ast.GtE):
                    return a >= b
        raise ValueError(f"unsupported locked dependency marker: {marker}")

    try:
        return evaluate(ast.parse(marker, mode="eval").body)
    except SyntaxError as exc:
        raise ValueError(f"unsupported locked dependency marker: {marker}") from exc


def runtime_lock() -> dict[str, str]:
    import tomllib

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = lock["package"]
    project = next(p for p in packages if p["name"] == "ewp-waveform")
    pending = list(project.get("dependencies", []))
    expected: dict[str, str] = {}
    while pending:
        edge = pending.pop()
        if edge.get("marker") and not lock_marker_applies(edge["marker"]):
            continue
        candidates = [
            p
            for p in packages
            if p["name"] == edge["name"]
            and ("version" not in edge or p["version"] == edge["version"])
            and ("source" not in edge or p["source"] == edge["source"])
            and (
                not p.get("resolution-markers")
                or any(lock_marker_applies(m) for m in p["resolution-markers"])
            )
        ]
        if len(candidates) != 1 or edge.get("extra"):
            raise ValueError(f"ambiguous/unsupported locked runtime dependency: {edge}")
        package = candidates[0]
        name, version = package["name"], package["version"]
        if name in expected:
            if expected[name] != version:
                raise ValueError(f"conflicting locked dependency: {name}")
            continue
        expected[name] = version
        pending.extend(package.get("dependencies", []))
    return dict(sorted(expected.items()))


def environment_details() -> dict[str, Any]:
    """Collect every dependency problem rather than stopping at the first missing wheel."""
    import tomllib

    problems = []
    if sys.version_info[:2] != (3, 12):
        problems.append("selected interpreter must be Python 3.12")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    versions = {}
    closure = runtime_lock()
    for name, expected in closure.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        if actual != expected:
            problems.append(f"locked dependency mismatch: {name} {actual} != {expected}")
        versions[name] = actual
    spec = importlib.util.find_spec("ewp_waveform")
    expected_file = ROOT / "src/ewp_waveform/__init__.py"
    if spec is None or spec.origin is None:
        problems.append("selected Python cannot import this checkout")
    elif Path(spec.origin).resolve() != expected_file.resolve():
        problems.append("selected Python imports another source checkout")
    try:
        distribution_version = importlib.metadata.version("ewp-waveform")
    except importlib.metadata.PackageNotFoundError:
        distribution_version = None
        problems.append("ewp-waveform distribution missing; use the locked project environment")
    if problems:
        raise ValueError("Python environment prerequisites:\n- " + "\n- ".join(problems))
    return {
        "python": sys.executable,
        "binary": identity(Path(sys.executable)),
        "version": sys.version,
        "prefix": sys.prefix,
        "dependencies": versions,
        "runtime_lock_closure": closure,
        "base_prefix": sys.base_prefix,
        "project_distribution": distribution_version,
        "source_project_version": project["project"]["version"],
        "package": identity(expected_file),
    }


def probe_python(python: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [str(python), str(Path(__file__).resolve()), "--_environment"],
        env=child_env(),
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if proc.returncode:
        raise ValueError("Python environment unavailable: " + proc.stderr.strip())
    return cast(dict[str, Any], json.loads(proc.stdout))


def select_python(explicit: Path | None, run: Path) -> tuple[Path, dict[str, Any]]:
    candidate = explicit.expanduser().absolute() if explicit else ROOT / ".venv/bin/python"
    try:
        return candidate, probe_python(candidate)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        if explicit:
            raise
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("need a working checkout .venv, --python /existing/python3.12, or uv")
    result = observe(
        [uv, "sync", "--frozen", "--python", "3.12", "--project", str(ROOT)], timeout=900
    )
    save(run / "uv-sync.json", result)
    if result.get("returncode") != 0:
        raise RuntimeError(
            "uv sync --frozen failed; see uv-sync.json; no dependency versions changed"
        )
    return candidate, probe_python(candidate)


def select_tools(
    inventory: dict[str, Any],
    ffmpeg: Path | None,
    ffprobe: Path | None,
    *,
    allow_missing: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pairs = inventory["installed_pairs"]
    first = inventory["first_path_tools"]
    baseline = tool_pair(Path(first["ffmpeg"]).parent) if first["ffmpeg"] else None
    if not first["ffprobe"] or (
        baseline and baseline["ffprobe"]["path"] != str(Path(first["ffprobe"]).resolve())
    ):
        baseline = None
    if (ffmpeg is None) != (ffprobe is None):
        raise ValueError("--ffmpeg and --ffprobe must be supplied together")
    if ffmpeg is not None and ffprobe is not None:
        ffmpeg, ffprobe = ffmpeg.expanduser().resolve(), ffprobe.expanduser().resolve()
        pair = tool_pair(ffmpeg.parent)
        if (
            pair is None
            or pair["ffmpeg"]["path"] != str(ffmpeg)
            or (pair["ffprobe"]["path"] != str(ffprobe))
        ):
            raise ValueError("selected tools must be real ffmpeg/ffprobe in one bin directory")
        selected = next((p for p in pairs if p["tools"] == pair), None)
        return baseline, selected if selected is not None else inventory_pair(pair)

    def score(pair: dict[str, Any]) -> int:
        observations = pair["observations"]
        filters = observations["-filters"].get("stdout", "")
        encoders = observations["-encoders"].get("stdout", "")
        return (
            100 * int(gpu_suitable(pair))
            + sum(name in filters for name in ("hwupload", "gblur_vulkan"))
            + sum(name in encoders for name in ("prores_ks_vulkan", "ffv1_vulkan"))
            + int("vulkan" in observations["-hwaccels"].get("stdout", ""))
        )

    if not pairs:
        if allow_missing:
            return baseline, None
        raise ValueError("no suitable installed ffmpeg/ffprobe pair found")
    # These are advertised capabilities only. The suite must still prove the runtime device.
    return baseline, max(pairs, key=score)


def advertised(observed: dict[str, Any], option: str, name: str) -> bool:
    text = observed.get("observations", {}).get(option, {}).get("stdout", "")
    return bool(re.search(r"(?m)^\s*[A-Z.]{1,8}\s+" + re.escape(name) + r"\s", text))


def gpu_suitable(selected: dict[str, Any] | None) -> bool:
    if selected is None:
        return False
    return (
        all(
            advertised(selected, option, name)
            for option, names in (
                ("-filters", ("hwupload", "hwdownload", "gblur_vulkan")),
                ("-encoders", ("prores_ks_vulkan", "ffv1_vulkan")),
            )
            for name in names
        )
        and "vulkan" in selected["observations"]["-hwaccels"].get("stdout", "").split()
    )


def baseline_skip_reason(observed: dict[str, Any] | None) -> str | None:
    if observed is None:
        return (
            "original PATH has no real same-directory ffmpeg/ffprobe pair; "
            "CPU FULL baseline NOT_RUN"
        )
    missing = [
        name
        for option, names in (
            ("-encoders", ("prores_ks", "ffv1", "rawvideo")),
            (
                "-filters",
                ("format", "scale", "split", "gblur", "blend", "crop", "geq", "lut", "alphamerge"),
            ),
        )
        for name in names
        if not advertised(observed, option, name)
    ]
    # Only known missing advertised capabilities skip. An unreadable inventory or
    # malformed graph must fail in the maintained runtime preflight, not become a skip.
    failed = any(
        observed.get("observations", {}).get(option, {}).get("returncode") != 0
        for option in ("-filters", "-encoders")
    )
    return (
        ("original CPU baseline lacks advertised capabilities: " + ", ".join(missing))
        if missing and not failed
        else None
    )


def startup_prerequisites(
    args: argparse.Namespace, run: Path, initial: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """Gather actionable tool/build/environment errors before uv or configure."""
    problems = []
    baseline = selected = None
    try:
        baseline, selected = select_tools(
            initial, args.ffmpeg, args.ffprobe, allow_missing=args.build_ffmpeg
        )
    except ValueError as exc:
        problems.append(str(exc))
    build_needed = args.build_ffmpeg and not gpu_suitable(selected)
    candidate = args.python.expanduser().absolute() if args.python else ROOT / ".venv/bin/python"
    environment_error = None
    try:
        probe_python(candidate)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        environment_error = str(exc)
        if args.python or not shutil.which("uv"):
            problems.append(environment_error + "; supply a locked Python3.12 environment or uv")
    prereqs = initial.get("build_prerequisites", {})
    if build_needed:
        prereqs = build_prerequisites(run, compile_probe=True)
        problems.extend(prereqs["problems"])
    result = {
        "problems": problems,
        "python_environment_problem": environment_error,
        "build_requested": args.build_ffmpeg,
        "build_needed": build_needed,
        "build_prerequisites": prereqs,
        "baseline_skip_reason": baseline_skip_reason(
            next((p for p in initial["installed_pairs"] if p["tools"] == baseline), None)
        ),
    }
    save(run / "startup-prerequisites.json", result)
    if problems:
        raise ValueError(
            "Startup prerequisites (no uv/configure executed):\n- " + "\n- ".join(problems)
        )
    return baseline, selected, build_needed


def manifest_for(template: dict[str, Any], mode: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(json.dumps(template))
    value["cells"] = [
        c for c in value["cells"] if (c["scenario"] == "FULL") == (mode == "reference")
    ]
    used = {c["workload"] for c in value["cells"]}
    value["workloads"] = [w for w in value["workloads"] if w["id"] in used]
    return value


def smoke_manifest(
    template: dict[str, Any],
    audio: Path,
    *,
    include_old: bool = False,
) -> dict[str, Any]:
    with wave.open(str(audio), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    if duration < 0.1:
        raise ValueError("CPU smoke needs at least 0.1 seconds of PCM WAV")
    value: dict[str, Any] = json.loads(json.dumps(template))
    value.update(
        input_sha256=digest(audio),
        source_duration_seconds=duration,
        workloads=[{"id": "tiny", "kind": "short", "start": 0.0, "duration": 0.1, "frames": 6}],
        cells=[
            {"id": "tiny-B", "scenario": "B", "workload": "tiny"},
            {"id": "tiny-F0", "scenario": "F0", "workload": "tiny"},
        ],
    )
    value["limits"].update(
        attempts=12,
        seconds=300.0,
        attempt_seconds=120.0,
        growth_bytes=32 * 1024**2,
        memory_floor_bytes=32 * 1024**2,
    )
    if include_old:
        value["cells"].insert(0, {"id": "tiny-A", "scenario": "A", "workload": "tiny"})
    for estimate in value["limits"]["estimates"].values():
        estimate.update(growth_bytes=4 * 1024**2, memory_bytes=128 * 1024**2, seconds=30.0)
    return value


def create_smoke_audio(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(
            b"".join(
                struct.pack("<h", int(14000 * math.sin(2 * math.pi * 330 * index / 48000)))
                for index in range(4800)
            )
        )


def append_event(run: Path, value: dict[str, Any]) -> None:
    path = run / "driver-events.jsonl"
    previous = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "0" * 64
    row = {**value, "previous_file_sha256": previous}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def completed_steps(run: Path) -> dict[str, dict[str, Any]]:
    """Reject uncertain/failed attempts; verify immutable logs before any resumption."""
    path = run / "driver-events.jsonl"
    if not path.exists():
        return {}
    prefix = b""
    starts: set[str] = set()
    complete: dict[str, dict[str, Any]] = {}
    for line in path.read_bytes().splitlines(keepends=True):
        row = json.loads(line)
        expected = hashlib.sha256(prefix).hexdigest() if prefix else "0" * 64
        if row["previous_file_sha256"] != expected:
            raise ValueError("driver event chain changed")
        prefix += line
        name = row["name"]
        if row["event"] == "STARTED":
            if name in starts:
                raise ValueError("duplicate driver STARTED step")
            starts.add(name)
            verify(row["request"])
        elif row["event"] in ("SUCCEEDED", "FAILED"):
            if name not in starts or name in complete:
                raise ValueError("orphan/duplicate driver terminal")
            for item in row["artifacts"]:
                verify(item)
            if row["event"] == "FAILED":
                raise ValueError("retained FAILED driver step; use a fresh namespace, never retry")
            complete[name] = row["value"]
        else:
            raise ValueError("unknown driver event")
    if starts - complete.keys():
        raise ValueError(
            "uncertain STARTED driver step; external reconciliation required; no retry"
        )
    return complete


def stage(request: dict[str, Any]) -> dict[str, Any]:
    """Selected-interpreter bridge; application APIs own all actual suite behavior."""
    from ewp_waveform.application import experiment_suite as suite
    from ewp_waveform.application.experiment_suite_state import lock

    operation = request["operation"]
    run = Path(request["run"])
    if operation == "prepare":
        args = dict(request["args"])
        for key in (
            "run",
            "media_root",
            "manifest",
            "audio",
            "ffmpeg",
            "ffprobe",
            "reference",
            "build_receipt",
            "old_ffmpeg",
            "old_ffprobe",
            "installed_provenance",
        ):
            args[key] = Path(args[key]) if args.get(key) is not None else None
        args["account_root"] = [Path(p) for p in args["account_root"]]
        return suite.prepare(argparse.Namespace(**args))
    if operation == "export":
        with lock(run):
            return suite.export_results(run)
    if operation == "verify":
        from ewp_waveform.application.experiment_suite_state import Ledger

        with lock(run):
            suite.session_at(run)
            results = Ledger(run).results()
            if any(r["status"] == "FAILED" for r in results.values()):
                raise ValueError("retained FAILED suite attempt; no resume or retry")
            return {"status": "VERIFIED", "attempts": len(results)}
    return suite.dispatch(run, operation)


def invoke(
    python: Path,
    run: Path,
    name: str,
    request: dict[str, Any],
    *,
    accepted: tuple[str, ...],
    record: bool = True,
) -> dict[str, Any]:
    folder = run / "steps" / name
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    output = folder / "value.json"
    request = {**request, "result_path": str(output)}
    save(folder / "request.json", request)
    if record:
        append_event(
            run, {"name": name, "event": "STARTED", "request": identity(folder / "request.json")}
        )
    with (
        interrupt_signals(),
        (folder / "stdout.txt").open("xb") as stdout,
        (folder / "stderr.txt").open("xb") as stderr,
        owned_process(
            [str(python), str(Path(__file__).resolve()), "--_stage", str(folder / "request.json")],
            cwd=ROOT,
            env=child_env(),
            stdout=stdout,
            stderr=stderr,
        ) as proc,
    ):
        try:
            proc.wait()
            verify_shutdown(proc)
        except BaseException as exc:
            try:
                if proc.pid in OWNERSHIP_RECEIPTS:
                    stop_owned(proc)
            except Exception as cleanup_error:
                note_error(exc, f"shutdown UNVERIFIED: {cleanup_error}; no replay")
            raise
    value = (
        load(output)
        if output.exists()
        else {"status": "FAILED", "error": "stage exited without result"}
    )
    good = proc.returncode == 0 and value.get("status") in accepted
    if record:
        artifacts = [identity(p) for p in sorted(folder.iterdir()) if p.is_file()]
        for key in ("json", "report"):
            if value.get(key) and Path(value[key]).is_file():
                artifacts.append(identity(Path(value[key])))
        append_event(
            run,
            {
                "name": name,
                "event": "SUCCEEDED" if good else "FAILED",
                "returncode": proc.returncode,
                "value": value,
                "artifacts": artifacts,
            },
        )
    if not good:
        raise RuntimeError(f"{name}: {value}; inspect {folder}")
    return value


def prepare_request(config: dict[str, Any], name: str) -> dict[str, Any]:
    suite = config["suites"][name]
    roots = config["roots"]
    own = {suite["run"], suite["media"]}
    tools = config["baseline_tools"] if name == "reference" else config["selected_tools"]
    old = (
        config["baseline_tools"]
        if name in ("experiments", "smoke") and not config.get("baseline_skip_reason")
        else None
    )
    if old and all(old[key]["sha256"] == tools[key]["sha256"] for key in old):
        old = None  # Identical installed binaries are not an old/new build contrast.
    return {
        "operation": "prepare",
        "run": suite["run"],
        "args": {
            "run": suite["run"],
            "media_root": suite["media"],
            "manifest": suite["manifest"]["path"],
            "audio": config["audio"]["path"],
            "source_commit": config["source"]["commit"],
            "reference": config["reference"]["path"],
            "ffmpeg": tools["ffmpeg"]["path"],
            "ffprobe": tools["ffprobe"]["path"],
            "old_ffmpeg": old["ffmpeg"]["path"] if old else None,
            "old_ffprobe": old["ffprobe"]["path"] if old else None,
            "build_receipt": config["build_receipt"]["path"]
            if name == "experiments" and config["build_receipt"]
            else None,
            "installed_provenance": config[
                "baseline_inventory" if name == "reference" else "selected_inventory"
            ]["path"],
            "device": config["device"],
            "expect_device_regex": config["expect_device_regex"],
            "account_root": [p for p in roots if p not in own],
        },
    }


def execute_suites(
    config: dict[str, Any], run: Path, done: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    summaries = dict(config.get("skipped_suites", {}))
    python = Path(config["python"])
    for name in ("reference", "experiments", "smoke"):
        if name not in config["suites"]:
            continue
        suite = config["suites"][name]
        for operation, accepted in (
            ("prepare", ("PREPARED_NOT_RUN",)),
            ("preflight", ("SUCCEEDED",)),
            ("batch", ("TECHNICAL_COMPLETE", "COMPLETE_WITH_SKIPS")),
            ("views", ("TECHNICAL_COMPLETE", "COMPLETE_WITH_SKIPS")),
            ("export", ("TECHNICAL_COMPLETE", "COMPLETE_WITH_SKIPS")),
        ):
            label = name + "-" + operation
            request = (
                prepare_request(config, name)
                if operation == "prepare"
                else {"operation": operation, "run": suite["run"]}
            )
            result = (
                done[label]
                if label in done
                else invoke(python, run, label, request, accepted=accepted)
            )
            summaries[name] = result
    return summaries


BUILD_LIMITS = {
    "growth_bytes": 12 * 1024**3,
    "reserve_bytes": 4 * 1024**3,
    "memory_bytes": 4 * 1024**3,
    "memory_floor_bytes": 512 * 1024**2,
    "seconds": 14400,
    "jobs": 2,
}


def build_tree_bytes(root: Path) -> int:
    total = 0
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                stat = (Path(directory) / name).lstat()
                total += max(stat.st_size, stat.st_blocks * 512)
            except FileNotFoundError:
                continue
    return total


def build_memory() -> dict[str, Any]:
    text = read_optional("/proc/meminfo") or ""
    match = re.search(r"(?m)^MemAvailable:\s+(\d+) kB", text)
    if not match:
        raise ValueError("build admission: MemAvailable unavailable")
    headroom = int(match[1]) * 1024
    ancestors = cgroup_inventory()
    for ancestor in ancestors:
        controls = ancestor["controls"]
        for limit_key, used_key in (
            ("memory.max", "memory.current"),
            ("memory.high", "memory.current"),
            ("memory.limit_in_bytes", "memory.usage_in_bytes"),
        ):
            limit = controls.get(limit_key)
            if limit is not None and limit.strip() != "max":
                used = controls.get(used_key)
                if used is None:
                    raise ValueError(
                        f"build admission: unreadable cgroup usage at {ancestor['path']}"
                    )
                headroom = min(headroom, int(limit) - int(used))
    return {"headroom_bytes": headroom, "cgroup_ancestors": ancestors}


def owned_rss() -> int:
    rows: dict[int, tuple[int, int]] = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            rows[int(path.parent.name)] = (int(fields[1]), int(fields[21]))
        except (OSError, ValueError, IndexError):
            continue
    owned = set(OWNERSHIP_RECEIPTS)
    while True:
        found = {pid for pid, (parent, _) in rows.items() if parent in owned}
        if found <= owned:
            break
        owned |= found
    return sum(rows[pid][1] for pid in owned if pid in rows) * os.sysconf("SC_PAGE_SIZE")


def check_build_budget(parent: Path, limits: dict[str, int], *, admission: bool) -> dict[str, Any]:
    storage = storage_inventory({"toolchain": parent})["toolchain"]
    growth = build_tree_bytes(parent)
    memory = build_memory()
    rss = owned_rss() if not admission else 0
    problems = []
    required_disk = limits["reserve_bytes"] + (limits["growth_bytes"] if admission else 0)
    if min(storage["available_bytes"], storage["free_bytes"]) < required_disk:
        problems.append("disk availability/reserve")
    if growth > limits["growth_bytes"]:
        problems.append("source/build/prefix/log growth")
    required_memory = limits["memory_floor_bytes"] + (limits["memory_bytes"] if admission else 0)
    if memory["headroom_bytes"] < required_memory:
        problems.append("host/cgroup RAM headroom")
    if rss > limits["memory_bytes"]:
        problems.append("owned process RSS")
    snapshot = {
        "storage": storage,
        "growth_bytes": growth,
        "memory": memory,
        "owned_rss_bytes": rss,
        "admission": admission,
    }
    if problems:
        raise ValueError(
            "separate build budget refused/crossed: "
            + ", ".join(problems)
            + "; snapshot="
            + json.dumps(snapshot, sort_keys=True)
        )
    return snapshot


def run_builder(python: Path, run: Path, parent: Path) -> dict[str, Any]:
    parent.mkdir(mode=0o700, exist_ok=False)
    limits = dict(BUILD_LIMITS)
    envelope = {
        "limits": limits,
        "root": str(parent),
        "scope": "Separate build-only envelope: all nested source (including .git), build, "
        "TMPDIR, prefix and logs. Sampling every <=0.2s plus scan cost, not an OS "
        "hard quota; overshoot possible. Suite budgets admit afresh relative to "
        "their own baselines. NOT an all-in startup/workflow growth or time cap.",
    }
    save(parent / "envelope.json", envelope)
    try:
        admitted = check_build_budget(parent, limits, admission=True)
        save(parent / "admission.json", admitted)
        started = time.monotonic()

        def monitor() -> None:
            if time.monotonic() - started >= limits["seconds"]:
                raise ValueError("separate build elapsed-time budget crossed")
            sample = check_build_budget(parent, limits, admission=False)
            with (parent / "resource-samples.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {"elapsed_seconds": time.monotonic() - started, **sample}, sort_keys=True
                    )
                    + "\n"
                )

        result = observe(
            [
                str(python),
                str(ROOT / "scripts/experiments_build.py"),
                "--source",
                str(parent / "source"),
                "--build",
                str(parent / "build"),
                "--prefix",
                str(parent / "prefix"),
                "--jobs",
                str(limits["jobs"]),
                "--execute",
            ],
            timeout=limits["seconds"],
            monitor=monitor,
            log_root=parent,
        )
        save(run / "ffmpeg-builder.json", result)
        monitor()  # Fence short builds/terminal growth between polling observations.
        if result.get("returncode") != 0:
            raise RuntimeError(
                "isolated FFmpeg builder failed; retained logs, no retry/global install"
            )
        save(
            parent / "terminal.json",
            {
                "status": "SUCCEEDED",
                "result": result,
                "final": check_build_budget(parent, limits, admission=False),
            },
        )
        return {
            **envelope,
            "artifacts": [identity(path) for path in sorted(parent.iterdir()) if path.is_file()],
        }
    except BaseException as exc:
        with suppress(OSError):
            save(
                parent / "FAILED.json",
                {
                    "status": "FAILED_OR_REFUSED",
                    "error": str(exc),
                    "type": type(exc).__name__,
                    "retry": "FORBIDDEN",
                },
            )
        raise


def current_reference(reference: Path) -> dict[str, Any] | None:
    pointer = load(reference).get("current_VM1_reference")
    if pointer is None:
        return None
    if not isinstance(pointer, str) or Path(pointer).is_absolute():
        raise ValueError("current_VM1_reference must be a checkout-relative versioned artifact")
    path = (ROOT / pointer).resolve(strict=True)
    if not path.is_relative_to(ROOT):
        raise ValueError("current_VM1_reference escapes checkout")
    return identity(path)


def freeze_new(
    args: argparse.Namespace, run: Path, initial: dict[str, Any], token: str
) -> dict[str, Any]:
    source = source_identity()  # Before any uv/setup; exact HEAD, never a historical source pin.
    media_parent = (args.media_parent or run.parent).expanduser().resolve()
    outside_git([media_parent])
    template_path = ROOT / "examples/experiments/wsl-suite.json"
    template = load(template_path)
    fixture_root = run.parent / ("smoke-fixture-" + token)
    audio = (
        args.audio.expanduser().resolve(strict=True)
        if args.audio
        else fixture_root / "synthetic-smoke.wav"
    )
    if args.cpu_smoke and not args.audio:
        outside_git([run, fixture_root])
        fixture_root.mkdir(mode=0o700)
        create_smoke_audio(audio)
    audio_identity = identity(audio)
    if not args.cpu_smoke and audio_identity["sha256"] != template["input_sha256"]:
        raise ValueError("authenticated source WAV SHA-256 mismatch; no setup or media executed")
    outside_git([run], audio)
    baseline, selected, build_needed = startup_prerequisites(args, run, initial)
    python, environment = select_python(args.python, run)
    baseline_observed = next(
        (p for p in initial["installed_pairs"] if p["tools"] == baseline), None
    )
    baseline_skip = baseline_skip_reason(baseline_observed)
    save(
        run / "baseline-tools.json",
        baseline_observed or {"status": "NOT_FOUND", "reason": baseline_skip},
    )
    receipt = None
    build_envelope = None
    build_roots: list[Path] = []
    if build_needed:
        parent = run.parent / ("ffmpeg-toolchain-" + token)
        build_roots = [parent]
        outside_git([run, *build_roots], audio)
        build_envelope = run_builder(python, run, parent)
        receipt = identity(parent / "build/build-receipt.json")
        pair = tool_pair(parent / "prefix/bin")
        if pair is None:
            raise ValueError("builder did not produce a valid isolated tool pair")
        selected = inventory_pair(pair)
        selected["qualification"] = "BUILD_RECEIPT_PENDING_SUITE_VERIFICATION"
        selected["build_receipt"] = receipt
    if selected is None:
        raise ValueError("no selected tools available after conditional build")
    save(run / "selected-tools.json", selected)
    suites: dict[str, dict[str, Any]] = {}
    names = (
        ["smoke"]
        if args.cpu_smoke
        else ["reference"] + ([] if args.reference_only else ["experiments"])
    )
    skipped_suites = {}
    if "reference" in names and baseline_skip:
        names.remove("reference")
        skipped_suites["reference"] = {
            "status": "COMPLETE_WITH_SKIPS",
            "actual_action": "NOT_RUN",
            "reason": baseline_skip,
            "throughput_fresh": False,
        }
    for name in names:
        include_old = bool(
            baseline
            and not baseline_skip
            and any(baseline[key]["sha256"] != selected["tools"][key]["sha256"] for key in baseline)
        )
        value = (
            smoke_manifest(template, audio, include_old=include_old)
            if name == "smoke"
            else manifest_for(template, name)
        )
        path = run / (name + "-manifest.json")
        save(path, value)
        suites[name] = {
            "run": str(run.parent / (name + "-run-" + token)),
            "media": str(media_parent / (name + "-media-" + token)),
            "manifest": identity(path),
        }
    roots = [
        run,
        *build_roots,
        *(Path(s[key]) for s in suites.values() for key in ("run", "media")),
    ]
    outside_git(roots, audio)
    if source_identity() != source:
        raise ValueError("source changed during environment/build setup")
    config = {
        "schema_version": 1,
        "run": str(run),
        "source": source,
        "audio": audio_identity,
        "python": str(python),
        "environment": environment,
        "initial_inventory": identity(run / "initial-inventory.json"),
        "baseline_tools": baseline,
        "baseline_skip_reason": baseline_skip,
        "selected_tools": selected["tools"],
        "baseline_inventory": identity(run / "baseline-tools.json"),
        "selected_inventory": identity(run / "selected-tools.json"),
        "reference": identity(ROOT / "examples/experiments/vm-reference.json"),
        "current_reference": current_reference(ROOT / "examples/experiments/vm-reference.json"),
        "template": identity(template_path),
        "build_receipt": receipt,
        "suites": suites,
        "skipped_suites": skipped_suites,
        "fixture_baseline": {
            "root": str(fixture_root),
            "bytes": audio_identity["bytes"],
            "audio": audio_identity,
            "scope": "immutable input baseline created before suite accounting; "
            "excluded input root, driver root included",
        }
        if args.cpu_smoke and not args.audio
        else None,
        "build_requested": args.build_ffmpeg,
        "build_performed": build_needed,
        "build_envelope": build_envelope,
        "roots": [str(p) for p in roots],
        "mode": "cpu-smoke"
        if args.cpu_smoke
        else "reference-only"
        if args.reference_only
        else "complete",
        "device": args.device,
        "expect_device_regex": args.expect_device_regex,
    }
    save(run / "driver.json", config)
    save(run / "driver-seal.json", identity(run / "driver.json"))
    return config


def verify_config(run: Path) -> dict[str, Any]:
    verify(load(run / "driver-seal.json"))
    config = load(run / "driver.json")
    if config["schema_version"] != 1 or config["run"] != str(run):
        raise ValueError("driver namespace identity mismatch; copied/relocated runs cannot resume")
    if config["source"] != source_identity():
        raise ValueError("exact source/driver identity drift; resume refused")
    outside_git([Path(p) for p in config["roots"]])
    for key in (
        "audio",
        "initial_inventory",
        "baseline_inventory",
        "selected_inventory",
        "reference",
        "template",
    ):
        verify(config[key])
    for tools in (config["baseline_tools"], config["selected_tools"]):
        if tools is None:
            continue
        for item in tools.values():
            verify(item)
    for inventory in (config["baseline_inventory"], config["selected_inventory"]):
        for item in load(Path(inventory["path"])).get("libraries", {}).values():
            verify(item)
    for suite in config["suites"].values():
        verify(suite["manifest"])
    if config["build_receipt"]:
        verify(config["build_receipt"])
    if config.get("current_reference"):
        verify(config["current_reference"])
    if config.get("build_envelope"):
        for artifact in config["build_envelope"]["artifacts"]:
            verify(artifact)
    if probe_python(Path(config["python"])) != config["environment"]:
        raise ValueError("selected interpreter/dependency identity drift")
    return config


def evidence_json(path: Path) -> dict[str, Any]:
    try:
        return load(path)
    except Exception as exc:
        return {
            "evidence_status": "UNAVAILABLE_UNVERIFIED",
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def evidence_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Evidence UNAVAILABLE / UNVERIFIED: {path}: {type(exc).__name__}: {exc}"


def report(
    run: Path,
    status: str,
    error: str | None,
    config: dict[str, Any] | None,
    summaries: dict[str, Any],
) -> Path:
    try:
        return detailed_report(run, status, error, config, summaries)
    except Exception as report_error:
        # Minimal Markdown depends on no secondary evidence/JSON serialization.
        folder = run / "reports"
        folder.mkdir(mode=0o700, exist_ok=True)
        path = folder / ("emergency-" + uuid.uuid4().hex + ".md")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                f"# WSL experiment driver\n\nStatus: **HOLD**\n\nRun: `{run}`\n\n"
                f"Original status: {status}\n\nOriginal error: {error}\n\n"
                f"Detailed report unavailable/unverified: {type(report_error).__name__}: "
                f"{report_error}\n\nVisual / Studio PENDING; promotion NOT_APPROVED.\n"
            )
        print(
            f"Detailed reporting failed; minimal Markdown: {path}: {report_error}", file=sys.stderr
        )
        return path


def detailed_report(
    run: Path,
    status: str,
    error: str | None,
    config: dict[str, Any] | None,
    summaries: dict[str, Any],
) -> Path:
    folder = run / "reports"
    folder.mkdir(mode=0o700, exist_ok=True)
    number = len(list(folder.glob("report-*.json"))) + 1
    path = folder / f"report-{number:04d}.json"
    value = {
        "status": status,
        "error": error,
        "run": str(run),
        "original_inventory": str(run / "initial-inventory.json")
        if (run / "initial-inventory.json").is_file()
        else None,
        "driver_config": str(run / "driver.json") if config else None,
        "mode": config["mode"] if config else None,
        "scope": "CPU_SMOKE_ONLY_NOT_AUTHENTICATED_FULL_OR_GPU"
        if config and config["mode"] == "cpu-smoke"
        else "DECLARED_MODE_ONLY",
        "source": config["source"] if config else None,
        "selected_environment": config["environment"] if config else None,
        "baseline_tools": config["baseline_tools"] if config else None,
        "selected_tools": config["selected_tools"] if config else None,
        "suites": summaries,
        "visual": "PENDING",
        "studio": "PENDING",
        "promotion": "NOT_APPROVED",
    }
    save(path, value)
    lines = [
        "# WSL experiment driver",
        "",
        f"Status: **{status}**",
        "",
        f"Run: `{run}`",
        "",
        "Visual / Resolve Studio: PENDING; promotion NOT_APPROVED.",
        "",
        f"[Original host/tool inventory]({run / 'initial-inventory.json'})",
        "",
    ]
    if error:
        lines += ["## Failure / HOLD", "", "```text", error.replace("```", "'''"), "```", ""]
    initial = evidence_json(run / "initial-inventory.json")
    if initial:
        host = initial.get("host", {})
        initial_summary = {
            k: initial.get(k)
            for k in (
                "captured_utc",
                "original_path",
                "bootstrap_python",
                "uv_version",
                "first_path_tools",
                "individual_tools",
                "storage",
                "build_prerequisites",
                "devices",
                "evidence_status",
                "error",
            )
        }
        initial_summary["host"] = {
            k: host.get(k)
            for k in (
                "platform",
                "uname",
                "cpu_count",
                "affinity",
                "meminfo",
                "cgroup_membership",
                "cgroup_ancestors",
                "os_release",
            )
        }
        lines += [
            "## Initial environment (before setup)",
            "",
            "```json",
            json.dumps(initial_summary, indent=2).replace("```", "'''"),
            "```",
            "",
        ]
    prerequisites = evidence_json(run / "startup-prerequisites.json")
    if prerequisites:
        lines += [
            "## Startup prerequisites and conditional build decision",
            "",
            "```json",
            json.dumps(prerequisites, indent=2).replace("```", "'''"),
            "```",
            "",
        ]
    if config:
        if config["mode"] == "cpu-smoke":
            lines += [
                "**CPU SMOKE ONLY — no authenticated FULL, production32 or GPU qualification.**",
                "",
            ]
        lines += [
            f"Mode: `{config['mode']}`",
            "",
            f"Source: `{config['source']['commit']}`",
            "",
            f"Selected Python: `{config['python']}`",
            "",
            f"[Selected environment and frozen driver config]({run / 'driver.json'})",
            "",
            f"[Original baseline tools]({run / 'baseline-tools.json'})",
            "",
            f"[Selected tools / observed provenance]({run / 'selected-tools.json'})",
            "",
        ]
        lines += [
            "## Selected environment / tool identities",
            "",
            "```json",
            json.dumps(
                {
                    k: config.get(k)
                    for k in (
                        "environment",
                        "baseline_tools",
                        "baseline_skip_reason",
                        "selected_tools",
                        "build_requested",
                        "build_performed",
                        "build_receipt",
                        "fixture_baseline",
                        "build_envelope",
                        "roots",
                    )
                },
                indent=2,
            ).replace("```", "'''"),
            "```",
            "",
        ]
        reference = config.get("reference")
        if reference:
            lines += [
                f"[Authenticated historical VM reference contract]({reference['path']})",
                "",
                "Historical VM correspondence is an environment comparison, "
                "not isolated GPU acceleration.",
                "",
            ]
            lines += [
                "### Historical VM reference",
                "",
                "```json",
                json.dumps(evidence_json(Path(reference["path"])), indent=2).replace("```", "'''"),
                "```",
                "",
            ]
        current = config.get("current_reference")
        if current:
            lines += [
                "## Versioned current VM.1 reference — actual measured source",
                "",
                "Separate measurement at its recorded source, NOT a measurement "
                "of this driver correction or this run. Best-effort embedding; frozen "
                "identity verified on resume.",
                "",
                f"[Current reference metadata]({current['path']})",
                "",
                "```json",
                json.dumps(evidence_json(Path(current["path"])), indent=2).replace("```", "'''"),
                "```",
                "",
            ]
    for name, summary in summaries.items():
        lines += [f"## {name}", "", f"Status: `{summary.get('status', 'UNAVAILABLE')}`", ""]
        if summary.get("report"):
            lines += [f"[Suite human-readable report]({summary['report']})", ""]
            suite_report = Path(summary["report"])
            contents = evidence_text(suite_report)
            if contents:
                # Preserve navigation when embedding relative suite artifact links.

                def absolute_link(match: re.Match[str], parent: Path = suite_report.parent) -> str:
                    target = match.group(1)
                    if target.startswith(("/", "#", "http:", "https:", "file:")):
                        return match.group(0)
                    return "](" + str((parent / target).resolve()) + ")"

                contents = re.sub(r"\]\(([^)]+)\)", absolute_link, contents)
                lines += [
                    "### Embedded suite results / comparable pairs / validation / "
                    "deduplicated MOV and MP4 navigation",
                    "",
                    contents,
                    "",
                ]
        if summary.get("json"):
            lines += [f"[Suite JSON]({summary['json']})", ""]
        if summary.get("error"):
            lines += ["```text", str(summary["error"]).replace("```", "'''"), "```", ""]
        if summary.get("reason"):
            lines += [f"NOT_RUN / skip reason: {summary['reason']}", ""]
    markdown = path.with_suffix(".md")
    with markdown.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return markdown


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio", type=Path, help="absolute path to the authenticated source WAV")
    p.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="external parent for automatic disjoint run/media/build directories",
    )
    p.add_argument(
        "--media-parent",
        "--media-root",
        dest="media_parent",
        type=Path,
        help="optional separate external parent for bulky media; metadata stays in output-root",
    )
    p.add_argument(
        "--resume", type=Path, help="known driver run; never retries FAILED/STARTED steps"
    )
    p.add_argument("--python", type=Path, help="existing locked Python 3.12 environment")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument(
        "--reference-only", action="store_true", help="installed-tool stock FULL only"
    )
    modes.add_argument(
        "--cpu-smoke",
        action="store_true",
        help="tiny B/F0 (plus original A when tools differ) CPU workflow, no FULL/GPU claims",
    )
    p.add_argument(
        "--build-ffmpeg",
        action="store_true",
        help="permit isolated pinned build only if selected advertised GPU capabilities "
        "are insufficient; not a forced rebuild; no dependency installs",
    )
    p.add_argument(
        "--ffmpeg", type=Path, help="optional installed selected ffmpeg (not the original baseline)"
    )
    p.add_argument("--ffprobe", type=Path, help="matching selected ffprobe")
    p.add_argument("--device", default="RTX 3090")
    p.add_argument("--expect-device-regex", default=r"RTX\s*3090")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not args.resume and not args.audio and not args.cpu_smoke:
        p.error("--audio is required except for --resume or synthetic --cpu-smoke")
    if args.resume and (
        args.audio
        or args.python
        or args.reference_only
        or args.cpu_smoke
        or args.build_ffmpeg
        or args.ffmpeg
        or args.ffprobe
        or args.media_parent
    ):
        p.error("--resume uses only the frozen known run; no setup or execution overrides")
    now = dt.datetime.now(dt.timezone.utc)  # noqa: UP017 (bootstrap 3.10)
    token = now.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    run = (
        args.resume.expanduser().resolve()
        if args.resume
        else args.output_root.expanduser().resolve() / ("run-" + token)
    )
    config = None
    summaries: dict[str, Any] = {}
    status, error = "HOLD", None
    locked = None
    owned = False
    os.umask(0o077)  # New child-created suite/build directories are private, including ancestors.
    try:
        outside_git([run])
        if args.resume:
            if not run.is_dir() or not (run / "driver-seal.json").is_file():
                raise ValueError(
                    "resume requires an existing sealed driver run; no guessing or adoption"
                )
            verify(load(run / "driver-seal.json"))
        else:
            run.mkdir(mode=0o700, parents=True, exist_ok=False)
        import fcntl

        locked = (run / "driver.lock").open("a")
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owned = True
        initial = (
            initial_inventory()
        )  # Original environment, before *any* setup/selected subprocess.
        planned = {
            "driver": run,
            "requested_output_root": args.output_root,
            "requested_media_parent": args.media_parent or run.parent,
        }
        if not args.resume:
            names = (
                ["smoke"]
                if args.cpu_smoke
                else ["reference"] + ([] if args.reference_only else ["experiments"])
            )
            for name in names:
                planned[name + "_suite"] = run.parent / (name + "-run-" + token)
                planned[name + "_media"] = (args.media_parent or run.parent) / (
                    name + "-media-" + token
                )
            if args.build_ffmpeg:
                planned["ffmpeg-toolchain"] = run.parent / ("ffmpeg-toolchain-" + token)
            if args.cpu_smoke and not args.audio:
                planned["immutable_fixture"] = run.parent / ("smoke-fixture-" + token)
        initial["storage"] = storage_inventory(planned)
        initial["build_prerequisites"] = build_prerequisites(run, compile_probe=False)
        print(
            json.dumps(
                {
                    "planned_absolute_directories": {
                        k: str(v.expanduser().resolve()) for k, v in planned.items()
                    },
                    "note": "printed before setup/execution; conditional build/reference "
                    "directories may remain uncreated",
                },
                indent=2,
            ),
            file=sys.stderr,
            flush=True,
        )
        if args.resume:
            save(run / ("resume-inventory-" + token + ".json"), initial)
            done = completed_steps(
                run
            )  # No selected-interpreter process before uncertain-step check.
            config = verify_config(run)
            print(
                json.dumps(
                    {
                        "frozen_execution_directories": {
                            "driver": str(run),
                            "suites": config["suites"],
                            "growth_roots": config["roots"],
                        }
                    },
                    indent=2,
                ),
                file=sys.stderr,
                flush=True,
            )
            # Even a fully complete driver must re-authenticate suite session,
            # ledger, requests, results and media. Cached export paths are not proof.
            for name, suite in config["suites"].items():
                if (
                    name + "-prepare" in done
                    and not (Path(suite["run"]) / "session.json").is_file()
                ):
                    raise ValueError("prepared suite namespace missing; no successful resume")
                if (Path(suite["run"]) / "session.json").is_file():
                    invoke(
                        Path(config["python"]),
                        run,
                        "resume-verify-" + name + "-" + token,
                        {"operation": "verify", "run": suite["run"]},
                        accepted=("VERIFIED",),
                    )
        else:
            save(run / "initial-inventory.json", initial)
            config = freeze_new(args, run, initial, token)
            done = {}
        summaries = execute_suites(config, run, done)
        status = (
            "COMPLETE_WITH_SKIPS"
            if any(s["status"] == "COMPLETE_WITH_SKIPS" for s in summaries.values())
            else "TECHNICAL_COMPLETE"
        )
    except (Exception, KeyboardInterrupt) as exc:
        error = f"{type(exc).__name__}: {exc}"
        if getattr(exc, "__notes__", None):
            error += "\n" + "\n".join(exc.__notes__)
        # Always retain the top-level report, including startup/prepare/preflight failures.
        # Read-only export is allowed after a failure; it never dispatches or retries media.
        if config:
            for name, suite in config["suites"].items():
                if not (Path(suite["run"]) / "session.json").is_file():
                    continue
                try:
                    summaries[name] = invoke(
                        Path(config["python"]),
                        run,
                        "diagnostic-export-" + name + "-" + token,
                        {"operation": "export", "run": suite["run"]},
                        accepted=(
                            "TECHNICAL_COMPLETE",
                            "COMPLETE_WITH_SKIPS",
                            "INCOMPLETE",
                            "HOLD",
                        ),
                        record=False,
                    )
                except Exception as export_error:
                    summaries[name] = {"status": "UNAVAILABLE", "error": str(export_error)}
    if not owned:
        # Never write into an unknown resume directory or an active owner's run.
        # A new external failure namespace preserves an actual report instead.
        fallback = args.output_root.expanduser().resolve() / ("startup-failure-" + token)
        try:
            outside_git([fallback])
            fallback.mkdir(mode=0o700, parents=True, exist_ok=False)
            run = fallback
        except OSError as exc:
            print(
                json.dumps(
                    {"status": "HOLD", "error": error, "report_error": str(exc), "report": None}
                ),
                file=sys.stderr,
            )
            if locked:
                locked.close()
            return 2
        except ValueError:
            print(json.dumps({"status": "HOLD", "error": error, "report": None}), file=sys.stderr)
            if locked:
                locked.close()
            return 2
    try:
        report_path = report(run, status, error, config, summaries)
        if report_path.name.startswith("emergency-"):
            status = "HOLD"
            error = (
                error + "; " if error else ""
            ) + "detailed report unavailable; minimal Markdown retained"
    except Exception as report_error:
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "error": error,
                    "report_error": str(report_error),
                    "report": None,
                }
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if locked:
            locked.close()
    print(
        json.dumps(
            {"status": status, "run": str(run), "report": str(report_path), "error": error},
            indent=2,
        )
    )
    return 0 if status in ("TECHNICAL_COMPLETE", "COMPLETE_WITH_SKIPS") else 2


def internal_main() -> int:
    if sys.argv[1:2] == ["--_supervise"]:
        return supervisor(sys.argv[3:], int(sys.argv[2]))
    if sys.argv[1:2] == ["--_environment"]:
        try:
            print(json.dumps(environment_details(), sort_keys=True))
            return 0
        except Exception:
            traceback.print_exc()
            return 2
    if sys.argv[1:2] == ["--_stage"]:
        request = load(Path(sys.argv[2]))
        try:
            value = stage(request)
        except Exception as exc:
            traceback.print_exc()
            value = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        save(Path(request["result_path"]), value)
        return 0
    with interrupt_signals():
        return main()


def compatibility_main(argv: list[str] | None = None) -> int:
    """One maintained ordinary workflow; keep frozen legacy protocol recovery.

    Historical sessions are not converted/adopted by the portable driver. A failed
    legacy campaign still refuses replay under its original integrity checks.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] in (["--_supervise"], ["--_environment"], ["--_stage"]):
        return internal_main()
    resume: str | None = None
    for index, argument in enumerate(arguments):
        if argument == "--resume" and index + 1 < len(arguments):
            resume = arguments[index + 1]
        elif argument.startswith("--resume="):
            resume = argument.partition("=")[2]
    if resume and (Path(resume).expanduser() / "driver-seal.json").is_file():
        with interrupt_signals():
            return main(arguments)
    sys.path.insert(0, str(ROOT / "src"))
    from ewp_waveform.application.portable_experiments import main as portable_main

    return portable_main(arguments)


if __name__ == "__main__":
    raise SystemExit(compatibility_main())
