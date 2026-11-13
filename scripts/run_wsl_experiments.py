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
import traceback
import uuid
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path.home() / ".local/state/ewp-waveform-experiments"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


def observe(argv: list[str], *, timeout: float = 20) -> dict[str, Any]:
    """Observation failure is evidence, never a synthesized capability success."""
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            # Also covers the explicitly requested builder/uv, whose subprocesses
            # must not survive a startup timeout. Never retry in this namespace.
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = proc.communicate()
            if isinstance(exc, KeyboardInterrupt):
                raise
            return {
                "argv": argv,
                "returncode": None,
                "stdout": stdout,
                "stderr": stderr,
                "error": f"timeout after {timeout} seconds; process group terminated",
            }
        return {
            "argv": argv,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    except OSError as exc:
        return {"argv": argv, "returncode": None, "error": str(exc)}


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
        "captured_utc": dt.datetime.now(dt.UTC).isoformat(),
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


def environment_details() -> dict[str, Any]:
    """Collect every dependency problem rather than stopping at the first missing wheel."""
    import tomllib

    problems = []
    if sys.version_info[:2] != (3, 12):
        problems.append("selected interpreter must be Python 3.12")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    versions = {}
    for requirement in project["project"]["dependencies"]:
        name, expected = requirement.split("==", 1)
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
            ("-encoders", ("prores_ks", "ffv1", "libx264", "rawvideo")),
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


def smoke_manifest(template: dict[str, Any], audio: Path) -> dict[str, Any]:
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
    with (folder / "stdout.txt").open("xb") as stdout, (folder / "stderr.txt").open("xb") as stderr:
        proc = subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--_stage", str(folder / "request.json")],
            cwd=ROOT,
            env=child_env(),
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
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
        if name == "experiments" and not config.get("baseline_skip_reason")
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
    build_roots: list[Path] = []
    if build_needed:
        build_roots = [
            run.parent / (name + "-" + token)
            for name in ("ffmpeg-source", "ffmpeg-build", "ffmpeg-prefix")
        ]
        outside_git([run, *build_roots], audio)
        result = observe(
            [
                str(python),
                str(ROOT / "scripts/experiments_build.py"),
                "--source",
                str(build_roots[0]),
                "--build",
                str(build_roots[1]),
                "--prefix",
                str(build_roots[2]),
                "--execute",
            ],
            timeout=14400,
        )
        save(run / "ffmpeg-builder.json", result)
        if result.get("returncode") != 0:
            raise RuntimeError("isolated FFmpeg builder failed; retained logs, no global install")
        receipt = identity(build_roots[1] / "build-receipt.json")
        pair = tool_pair(build_roots[2] / "bin")
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
        value = smoke_manifest(template, audio) if name == "smoke" else manifest_for(template, name)
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
    if probe_python(Path(config["python"])) != config["environment"]:
        raise ValueError("selected interpreter/dependency identity drift")
    return config


def report(
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
    if (run / "initial-inventory.json").is_file():
        initial = load(run / "initial-inventory.json")
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
    if (run / "startup-prerequisites.json").is_file():
        lines += [
            "## Startup prerequisites and conditional build decision",
            "",
            "```json",
            json.dumps(load(run / "startup-prerequisites.json"), indent=2).replace("```", "'''"),
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
                json.dumps(load(Path(reference["path"])), indent=2).replace("```", "'''"),
                "```",
                "",
            ]
    for name, summary in summaries.items():
        lines += [f"## {name}", "", f"Status: `{summary.get('status', 'UNAVAILABLE')}`", ""]
        if summary.get("report"):
            lines += [f"[Suite human-readable report]({summary['report']})", ""]
            suite_report = Path(summary["report"])
            if suite_report.is_file():
                # Preserve navigation when embedding relative suite artifact links.
                contents = suite_report.read_text(encoding="utf-8")

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
        "--cpu-smoke", action="store_true", help="tiny B/F0 CPU workflow, no FULL or GPU claims"
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
    token = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
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
                planned.update(
                    {
                        name: run.parent / (name + "-" + token)
                        for name in ("ffmpeg-source", "ffmpeg-build", "ffmpeg-prefix")
                    }
                )
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
    return main()


if __name__ == "__main__":
    raise SystemExit(internal_main())
