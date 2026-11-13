"""Portable experiment identities, original-host inventory and append-only state.

This module is stdlib-only. It intentionally does not import the Linux-only old
experiment-suite modules, production service, NumPy, or optional Torch.
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any


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
    distributions = sorted(
        (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
    )
    if optional:
        torch_version = next((v for name, v in distributions if name.lower() == "torch"), None)
        if torch_version != "2.9.1+cu128":
            raise ValueError(
                "explicit CUDA worker requires pinned torch2.9.1+cu128; "
                f"observed {torch_version}; use --cuda --install-cuda for isolated setup"
            )
    metadata_files = []
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
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
        "locked_runtime": expected,
        "runtime_versions": actual,
        "distributions": distributions,
        "distribution_metadata": metadata_files,
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


def tree_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def check_budget(run: Path, media: Path, limits: dict[str, Any]) -> dict[str, Any]:
    growth = tree_bytes(run) + tree_bytes(media)
    space = min(shutil.disk_usage(run).free, shutil.disk_usage(media).free)
    host = resources()
    if growth > limits["growth_bytes"] or space < limits["reserve_bytes"]:
        raise ValueError(f"disk budget refused/crossed: growth={growth}, free={space}")
    available = host["ram_available_bytes"]
    if available is None or available < limits["memory_floor_bytes"]:
        raise ValueError(f"guest RAM headroom unavailable/below floor: {available}")
    return {
        "growth_bytes": growth,
        "free_bytes": space,
        "resources": host,
        "scope": "run+media sampled sizes; no kernel quota; peaks may be missed",
    }
