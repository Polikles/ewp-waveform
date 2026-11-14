"""Portable experiment identities, original-host inventory and append-only state.

This module is stdlib-only. It intentionally does not import the Linux-only old
experiment-suite modules, production service, NumPy, or optional Torch.
"""

from __future__ import annotations

import ast
import base64
import csv
import ctypes
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_process import ResourceAdmissionError


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    path = path.expanduser().absolute()
    return {
        "path": str(path),
        "resolved": str(path.resolve(strict=True)),
        "bytes": path.stat().st_size,
        "sha256": sha(path),
    }


def verify(item: dict[str, Any]) -> None:
    if identity(Path(item["path"])) != item:
        raise ValueError(f"frozen artifact changed: {item['path']}; use a new namespace")


def save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_optional(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def resources() -> dict[str, Any]:
    """Guest RAM/affinity, not physical Windows host claims from inside WSL."""
    affinity: list[int] | None = None
    total: int | None = None
    available: int | None = None
    controls: dict[str, Any] = {}
    if hasattr(os, "sched_getaffinity"):
        affinity = sorted(os.sched_getaffinity(0))
    if os.name == "nt":
        from ctypes import wintypes as w

        class Memory(ctypes.Structure):
            _fields_ = [
                ("length", w.DWORD),
                ("load", w.DWORD),
                *[
                    (n, ctypes.c_uint64)
                    for n in (
                        "total",
                        "available",
                        "total_page",
                        "available_page",
                        "total_virtual",
                        "available_virtual",
                        "extended",
                    )
                ],
            ]

        api: Any = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if api.GlobalMemoryStatusEx(ctypes.byref(memory)):
            total, available = memory.total, memory.available
        api.GetCurrentProcess.restype = w.HANDLE
        api.GetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p]
        process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
        if api.GetProcessAffinityMask(
            api.GetCurrentProcess(), ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            affinity = [
                i for i in range(ctypes.sizeof(process_mask) * 8) if process_mask.value & (1 << i)
            ]
        controls["windows_job_limits"] = "inherited guest restrictions; not overridden"
    elif sys.platform.startswith("linux"):
        info = read_optional(Path("/proc/meminfo")) or ""
        values = {
            line.split(":")[0]: int(line.split()[1]) * 1024
            for line in info.splitlines()
            if line.startswith(("MemTotal:", "MemAvailable:"))
        }
        total, available = values.get("MemTotal"), values.get("MemAvailable")
        controls["membership"] = read_optional(Path("/proc/self/cgroup"))
        # Retain all visible cgroup-v2 ancestors, including guest quota/affinity.
        membership = controls["membership"] or ""
        for line in membership.splitlines():
            if not line.startswith("0::"):
                continue
            root = Path("/sys/fs/cgroup")
            current = root / line.split(":", 2)[2].lstrip("/")
            while current.is_relative_to(root):
                values_at = {
                    name: read_optional(current / name)
                    for name in ("memory.max", "memory.current", "cpu.max", "cpuset.cpus.effective")
                }
                controls[str(current)] = values_at
                limit, used = values_at["memory.max"], values_at["memory.current"]
                if limit and used and limit.strip().isdigit() and used.strip().isdigit():
                    headroom = max(0, int(limit) - int(used))
                    available = headroom if available is None else min(available, headroom)
                if current == root:
                    break
                current = current.parent
    return {
        "cpu_count": os.cpu_count(),
        "affinity": affinity,
        "ram_total_bytes": total,
        "ram_available_bytes": available,
        "scope": "current guest OS, not external host",
        "controls": controls,
        "process_tree_peak_rss_bytes": None,
    }


def outside_git(paths: list[Path], audio: Path | None = None) -> None:
    for path in paths:
        resolved = path.resolve()
        git_root = next((p for p in (resolved, *resolved.parents) if (p / ".git").exists()), None)
        if git_root is not None:
            # Explicit ignored external ops storage is not product source/media in Git.
            # Fail closed for ordinary/untracked/tracked paths and the product checkout.
            import subprocess

            product = Path(__file__).resolve().parents[3]
            ignored = subprocess.run(
                ["git", "-C", str(git_root), "check-ignore", "-q", "--", str(resolved)],
                capture_output=True,
                timeout=20,
                check=False,
            )
            actual_root = subprocess.run(
                ["git", "-C", str(git_root), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if actual_root.returncode or Path(actual_root.stdout.strip()).resolve() != git_root:
                raise ValueError(f"generated data must be outside Git: {resolved}")
            tracked = subprocess.run(
                ["git", "-C", str(git_root), "ls-files", "--", str(resolved)],
                capture_output=True,
                timeout=20,
                check=False,
            )
            if (
                resolved.is_relative_to(product)
                or ignored.returncode != 0
                or tracked.returncode != 0
                or tracked.stdout.strip()
            ):
                raise ValueError(
                    "generated data must be outside Git "
                    f"(or ignored external ops storage): {resolved}"
                )
        if audio and audio.resolve().is_relative_to(resolved):
            raise ValueError("source audio must be outside writable output roots")


def source_identity(root: Path) -> dict[str, Any]:
    paths = [root / "pyproject.toml", root / "uv.lock"]
    requirements = root / "requirements-torch-experiment.txt"
    if requirements.is_file():
        paths.append(requirements)
    for name in (
        "src",
        "scripts",
        "presets",
        "performance",
        "config",
        "examples/experiments",
        "requirements",
    ):
        folder = root / name
        if folder.is_dir():
            paths.extend(
                p
                for p in folder.rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and p.suffix in (".py", ".toml", ".json", ".txt")
            )
    files = {str(p.relative_to(root)): sha(p) for p in sorted(paths)}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    git: dict[str, Any] = {"available": False, "commit": None, "tree": None}
    if (root / ".git").exists():
        import subprocess

        def query(*arguments: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(root), *arguments],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            return result.stdout.strip()

        git = {
            "available": True,
            "commit": query("rev-parse", "HEAD"),
            "tree": query("rev-parse", "HEAD^{tree}"),
            "status": query("status", "--porcelain=v1", "--untracked-files=all"),
        }
    return {
        "root": str(root),
        "git": git,
        "sha256": digest,
        "files": files,
        "scope": "source/scripts/visual+performance config/lock bytes; not Git timestamps",
    }


def marker_applies(marker: str) -> bool:
    """Fail-closed evaluator for the committed lock's marker grammar (no eval)."""
    env = {
        "sys_platform": sys.platform,
        "os_name": os.name,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "python_version": platform.python_version()[:4],
        "python_full_version": platform.python_version(),
        "extra": "",
    }

    def operand(node: ast.AST) -> str:
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        raise ValueError(f"unsupported lock marker: {marker}")

    def walk(node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp):
            result = [walk(n) for n in node.values]
            return all(result) if isinstance(node.op, ast.And) else any(result)
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
            if left.replace(".", "").isdigit() and right.replace(".", "").isdigit():
                a, b = tuple(map(int, left.split("."))), tuple(map(int, right.split(".")))
                if isinstance(op, ast.Lt):
                    return a < b
                if isinstance(op, ast.LtE):
                    return a <= b
                if isinstance(op, ast.Gt):
                    return a > b
                if isinstance(op, ast.GtE):
                    return a >= b
        raise ValueError(f"unsupported lock marker: {marker}")

    return walk(ast.parse(marker, mode="eval").body)


def distribution_payload(dist: importlib.metadata.Distribution) -> dict[str, Any]:
    """Stream-authenticate installed bytes, not just the RECORD describing them.

    RECORD hashes/sizes are checked when provided; unhashed entries (including
    RECORD itself) still enter the actual SHA-256 manifest. Cache bytecode is
    deliberately excluded. Enumeration is the installed distribution's file
    inventory; application/editable source is authenticated by source_identity.
    This preflight work is outside all rendering timers. Its command envelope is
    retained separately; elapsed timings must not enter a reusable fingerprint.
    """
    # Distribution.files filters missing paths on Python 3.12. Parse the raw
    # RECORD so a deleted payload cannot disappear silently from admission.
    record = dist.read_text("RECORD")
    name = dist.metadata["Name"]
    if not record:
        raise ValueError(f"installed distribution RECORD inventory unavailable: {name}")
    manifest = hashlib.sha256()
    count, size = 0, 0
    for row in sorted(csv.reader(io.StringIO(record))):
        if len(row) != 3 or not row[0]:
            raise ValueError(f"malformed installed distribution RECORD: {name}")
        entry, recorded_hash, recorded_size = row
        relative = Path(entry)
        if relative.suffix.lower() in (".pyc", ".pyo") or "__pycache__" in relative.parts:
            continue
        path = Path(str(dist.locate_file(entry)))
        if not path.is_file():
            raise ValueError(f"installed distribution payload missing: {name}: {entry}")
        item = identity(path)
        if recorded_size and int(recorded_size) != item["bytes"]:
            raise ValueError(
                f"installed distribution payload changed (RECORD size): {name}: {entry}"
            )
        if recorded_hash:
            mode, expected_hash = recorded_hash.split("=", 1)
            if mode == "sha256":
                digest = bytes.fromhex(item["sha256"])
            else:
                value = hashlib.new(mode)
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(block)
                digest = value.digest()
            observed_hash = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            if observed_hash != expected_hash:
                raise ValueError(
                    f"installed distribution payload changed (RECORD hash): {name}: {entry}"
                )
        manifest.update(json.dumps({"entry": entry, **item}, sort_keys=True).encode("utf-8"))
        manifest.update(b"\n")
        count += 1
        size += item["bytes"]
    return {
        "name": name,
        "version": dist.version,
        "root": str(Path(str(dist.locate_file(""))).resolve()),
        "sha256": manifest.hexdigest(),
        "files": count,
        "bytes": size,
        "scope": "installed RECORD payload bytes/paths; hashes validated; excludes pyc/pyo caches",
    }


def environment_details(root: Path, *, optional: bool = False) -> dict[str, Any]:
    import tomllib

    if sys.version_info[:2] != (3, 12):
        raise ValueError("selected worker must be Python 3.12")
    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    project = next(p for p in packages if p["name"] == "ewp-waveform")
    pending = list(project.get("dependencies", []))
    expected: dict[str, str] = {}
    while pending:
        edge = pending.pop()
        if edge.get("marker") and not marker_applies(edge["marker"]):
            continue
        candidates = [
            p
            for p in packages
            if p["name"] == edge["name"]
            and (not edge.get("version") or p.get("version") == edge["version"])
        ]
        if len(candidates) != 1:
            raise ValueError(f"ambiguous lock edge: {edge}")
        package = candidates[0]
        if package["name"] in expected:
            continue
        expected[package["name"]] = package["version"]
        pending.extend(package.get("dependencies", []))
    runtime_expected = dict(expected)
    optional_expected: dict[str, str] = {}
    if optional:
        from ewp_waveform.application.portable_experiments_setup import cuda_lock

        for line in cuda_lock(root).read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^ \\]+)", line)
            if match:
                optional_expected[match[1]] = match[2]
        if optional_expected.get("torch") != "2.9.1+cu128":
            raise ValueError("committed CUDA closure missing pinned torch; no reuse/install")
        expected.update(optional_expected)
    actual: dict[str, str | None] = {}
    problems = []
    for name, version in expected.items():
        try:
            actual[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual[name] = None
        if actual[name] != version:
            problems.append(f"{name}={actual[name]} (locked {version})")
    if problems:
        raise ValueError("locked runtime dependency mismatch: " + "; ".join(problems))
    installed = sorted(
        importlib.metadata.distributions(),
        key=lambda d: (d.metadata["Name"], d.version, str(d.locate_file(""))),
    )
    distributions = [(d.metadata["Name"], d.version) for d in installed]
    if optional:
        torch_version = next((v for name, v in distributions if name.lower() == "torch"), None)
        if torch_version != "2.9.1+cu128":
            raise ValueError(
                "explicit CUDA worker requires pinned torch2.9.1+cu128; "
                f"observed {torch_version}; use --cuda --install-cuda for isolated setup"
            )
    metadata_files = []
    payloads = []
    for dist in installed:
        payloads.append(distribution_payload(dist))
        for entry in sorted(dist.files or [], key=str):
            if str(entry).endswith(("/METADATA", "/RECORD", "/direct_url.json")):
                path = Path(str(dist.locate_file(entry)))
                if path.is_file():
                    metadata_files.append(identity(path))
    return {
        "python": str(Path(sys.executable).absolute()),
        "binary": identity(Path(sys.executable)),
        "version": sys.version,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "locked_runtime": runtime_expected,
        "locked_optional": optional_expected,
        "runtime_versions": actual,
        "distributions": distributions,
        "distribution_metadata": metadata_files,
        "distribution_payloads": payloads,
        "interpreter_scope": (
            "selected executable hash/version; stdlib/external system libraries not inventoried"
        ),
        "optional_worker": optional,
        "package_selection": "explicit existing environment; no install"
        if optional
        else "uv.lock runtime closure",
    }


def append_event(run: Path, row: dict[str, Any]) -> None:
    path = run / "events.jsonl"
    previous = sha(path) if path.exists() else "0" * 64
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({**row, "previous_sha256": previous}, sort_keys=True, allow_nan=False) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def completed_steps(run: Path) -> dict[str, dict[str, Any]]:
    path = run / "events.jsonl"
    if not path.exists():
        return {}
    prefix = b""
    starts: set[str] = set()
    complete: dict[str, dict[str, Any]] = {}
    for line in path.read_bytes().splitlines(keepends=True):
        row = json.loads(line)
        previous = hashlib.sha256(prefix).hexdigest() if prefix else "0" * 64
        if row["previous_sha256"] != previous:
            raise ValueError("event hash chain changed; no replay")
        prefix += line
        name = row["name"]
        if row["event"] == "STARTED":
            if name in starts:
                raise ValueError("duplicate STARTED; no replay")
            starts.add(name)
            verify(row["request"])
        elif row["event"] in ("SUCCEEDED", "FAILED", "SKIPPED"):
            if name not in starts or name in complete:
                raise ValueError("orphan/duplicate terminal; no replay")
            for item in row["artifacts"]:
                verify(item)
            if row["event"] == "FAILED":
                raise ValueError(f"retained FAILED {name}; use a new namespace, never retry")
            complete[name] = row["value"]
        elif row["event"] == "DISPATCH_REFUSED":
            raise ResourceAdmissionError(
                "retained post-evidence dispatch refusal; use a new namespace, no replay: "
                + str(row["value"].get("error"))
            )
        else:
            raise ValueError("unknown event; no replay")
    if starts != complete.keys():
        raise ValueError("uncertain STARTED work; reconcile externally, no replay")
    return complete


@contextmanager
def lock(run: Path) -> Any:
    path = run / "owner.lock"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        yield
    finally:
        os.close(descriptor)
        path.unlink()


class ResourceLimitError(ResourceAdmissionError):
    """Global capacity/RAM refusal; never an optional backend capability failure."""


def tree_usage(
    roots: list[Path], *, max_entries: int | None = None, timeout_seconds: float | None = None
) -> dict[str, Any]:
    """Global inode dedup across overlapping roots and uv hardlink cache/envs.

    POSIX allocation uses st_blocks (512-byte units), including directory blocks.
    Other platforms conservatively use logical bytes and explicitly label that
    fallback; no claim of NTFS compressed/sparse allocation measurement is made.
    Symlinks are not followed. Races/disappearing files fail closed, not undercount.
    """
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    seen: set[tuple[int, int] | str] = set()
    logical, allocated, files = 0, 0, 0
    allocation_known = True
    for root in roots:
        if not root.exists():
            continue
        pending = [root]
        while pending:
            if (max_entries is not None and len(seen) >= max_entries) or (
                deadline is not None and time.monotonic() >= deadline
            ):
                raise ValueError("storage inspection bound exceeded; no partial total claimed")
            path = pending.pop()
            stat = path.lstat()
            key = (stat.st_dev, stat.st_ino) if stat.st_ino else str(path.absolute())
            if key in seen:
                continue
            seen.add(key)
            if path.is_symlink():
                continue
            blocks = getattr(stat, "st_blocks", None)
            if blocks is None:
                allocation_known = False
            allocated += stat.st_size if blocks is None else blocks * 512
            if path.is_dir():
                pending.extend(path.iterdir())
            elif path.is_file():
                files += 1
                logical += stat.st_size
    return {
        "logical_bytes": logical,
        "allocated_bytes": allocated if allocation_known else None,
        "budget_bytes": allocated,
        "budget_basis": "allocated blocks"
        if allocation_known
        else "logical fallback (allocation unavailable)",
        "files": files,
        "deduplication": "global (device,inode), overlapping roots and hardlinks counted once",
    }


def tree_bytes(root: Path) -> int:
    # Compatibility callers need the same allocation basis as check_budget.
    return int(tree_usage([root])["budget_bytes"])


def check_budget(run: Path, media: Path, limits: dict[str, Any]) -> dict[str, Any]:
    roots = [Path(p) for p in limits.get("accounting_roots", [run, media])]
    usage = tree_usage(roots)
    growth = max(0, usage["budget_bytes"] - limits.get("baseline_bytes", 0))
    reserve_roots = list(
        dict.fromkeys(
            [
                *roots,
                run,
                media,
                *(Path(p) for p in limits.get("reserve_roots", [])),
            ]
        )
    )
    free_by_root = {str(p): shutil.disk_usage(p).free for p in reserve_roots}
    space = min(free_by_root.values())
    host = resources()
    if growth > limits["growth_bytes"] or space < limits["reserve_bytes"]:
        raise ResourceLimitError(
            f"disk budget refused/crossed: growth={growth}, free={space}, "
            f"basis={usage['budget_basis']}, scope={limits.get('budget_scope', 'run+media')}"
        )
    available = host["ram_available_bytes"]
    if available is None or available < limits["memory_floor_bytes"]:
        raise ResourceLimitError(f"guest RAM headroom unavailable/below floor: {available}")
    if limits.get("campaign_limits"):
        check_budget(run, media, limits["campaign_limits"])
    return {
        "growth_bytes": growth,
        "free_bytes": space,
        "accounting_roots": list(map(str, roots)),
        "reserve_roots": list(map(str, reserve_roots)),
        "filesystem_free_bytes": free_by_root,
        "storage": usage,
        "resources": host,
        "scope": limits.get(
            "budget_scope", "run+media sampled allocation; no kernel quota; peaks may be missed"
        ),
    }
