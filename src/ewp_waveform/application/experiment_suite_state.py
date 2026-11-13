"""Immutable attempts, namespace identity and finite process-group supervision."""

from __future__ import annotations

import fcntl
import importlib.metadata
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ewp_waveform.application.experiments import (
    available_memory_bytes,
    digest_value,
    load,
    save_new,
    sha,
    source_fingerprint,
)
from ewp_waveform.ffmpeg.experiment_suite import PIN


def artifact(path: Path, role: str = "EVIDENCE") -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing/nonregular artifact: {path}")
    return {
        "path": str(path.resolve()),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def source_identity() -> dict[str, Any]:
    value = source_fingerprint()
    value["distributions"] = sorted(
        [d.metadata["Name"], d.version] for d in importlib.metadata.distributions()
    )
    package = Path(value["imported_product_file"]).parents[2]
    proc = subprocess.run(
        ["git", "-C", str(package), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    value["git_status"] = proc.stdout
    value["environment"] = {
        k: v
        for k, v in sorted(os.environ.items())
        if k.startswith(("EWP_", "VK_", "MESA_", "LIBGL_", "CUDA_"))
    }
    # Analysis cache is deliberately isolated for each attempt, not inherited.
    value["environment"].pop("EWP_ANALYSIS_CACHE", None)
    return value


def validate_roots(roots: list[Path]) -> list[Path]:
    resolved = [p.resolve() for p in roots]
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate growth roots")
    for p in resolved:
        if not p.is_absolute() or any((parent / ".git").exists() for parent in (p, *p.parents)):
            raise ValueError("outputs/accounting roots must be outside Git")
        for q in resolved:
            if p != q and p.is_relative_to(q):
                raise ValueError("growth roots must be disjoint; no double counting")
    return resolved


def parent(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def resources(roots: list[Path]) -> dict[str, Any]:
    paths = {}
    for p in roots:
        existing = parent(p)
        stat = existing.stat()
        usage = shutil.disk_usage(existing)
        paths[str(p)] = {
            "device": stat.st_dev,
            "free_bytes": usage.free,
            "tree_bytes": tree_bytes(p),
        }
    controls: dict[str, Any] = {}
    mount = Path("/sys/fs/cgroup")
    membership = Path("/proc/self/cgroup")
    relative = (
        next(
            (line[3:] for line in membership.read_text().splitlines() if line.startswith("0::")),
            "/",
        )
        if membership.exists()
        else "/"
    )
    candidate = mount / relative.lstrip("/")
    selected = candidate if candidate.is_dir() and candidate.is_relative_to(mount) else mount
    controls["observed_path"] = str(selected)
    for name in ("cpu.max", "cpuset.cpus.effective", "memory.max", "memory.current"):
        p = selected / name
        controls[name] = p.read_text().strip() if p.exists() else None
    # A tighter ancestor memory ceiling still constrains this process.
    ancestor_headroom = []
    for directory in (selected, *selected.parents):
        if not directory.is_relative_to(mount):
            break
        maximum, current = directory / "memory.max", directory / "memory.current"
        if maximum.exists() and current.exists():
            cap = maximum.read_text().strip()
            if cap != "max":
                ancestor_headroom.append(int(cap) - int(current.read_text().strip()))
    controls["ancestor_headroom_bytes"] = min(ancestor_headroom) if ancestor_headroom else None
    return {
        "platform": platform.platform(),
        "release": platform.release(),
        "cpu_count": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "available_memory_bytes": available_memory_bytes(),
        "cgroups": controls,
        "roots": paths,
        "tree_rss": None,
        "tree_rss_note": "not sampled; admission uses available RAM/cgroup headroom",
    }


def memory_headroom(snapshot: dict[str, Any]) -> int:
    value = snapshot["available_memory_bytes"]
    if value is None:
        raise ValueError("available RAM observation required")
    controls = snapshot["cgroups"]
    maximum, current = controls.get("memory.max"), controls.get("memory.current")
    if maximum not in (None, "max") and current is not None:
        value = min(value, int(maximum) - int(current))
    ancestor = controls.get("ancestor_headroom_bytes")
    if ancestor is not None:
        value = min(value, int(ancestor))
    return int(value)


class ResourceLimitError(RuntimeError):
    def __init__(self, reason: str, snapshot: dict[str, Any]) -> None:
        super().__init__(reason)
        self.snapshot = snapshot


def check_envelope(
    session: dict[str, Any], estimate: dict[str, Any], *, elapsed: float = 0, spent: float = 0
) -> dict[str, Any]:
    limits = session["manifest"]["limits"]
    snapshot = resources([Path(p) for p in session["growth_baseline"]])
    growth = sum(
        max(0, v["tree_bytes"] - session["growth_baseline"][p])
        for p, v in snapshot["roots"].items()
    )
    snapshot["observed_growth_bytes"] = growth
    snapshot["elapsed_seconds"] = elapsed
    snapshot["previous_accounted_seconds"] = spent
    snapshot["prospective_allowance"] = estimate
    if growth + estimate["growth_bytes"] > limits["growth_bytes"]:
        raise ResourceLimitError("growth admission/monitor limit", snapshot)
    # Each filesystem counted once, reserve checked against remaining conservative estimate.
    devices: dict[int, int] = {}
    for v in snapshot["roots"].values():
        devices[v["device"]] = min(devices.get(v["device"], v["free_bytes"]), v["free_bytes"])
    if any(free < limits["reserve_bytes"] + estimate["growth_bytes"] for free in devices.values()):
        raise ResourceLimitError("filesystem reserve admission/monitor limit", snapshot)
    if memory_headroom(snapshot) < limits["memory_floor_bytes"] + estimate["memory_bytes"]:
        raise ResourceLimitError("available RAM/cgroup admission/monitor limit", snapshot)
    if (
        spent + elapsed + estimate["seconds"] > limits["seconds"]
        or elapsed > limits["attempt_seconds"]
    ):
        raise ResourceLimitError("finite elapsed-time allowance exhausted", snapshot)
    return {**snapshot, "observed_growth_bytes": growth}


@contextmanager
def lock(run: Path) -> Iterator[None]:
    with (run / "suite.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("suite already owned by another process") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Ledger:
    def __init__(self, run: Path) -> None:
        if any((run / "attempts").glob("*/resource-refusal.json")):
            raise RuntimeError("final resource refusal retained; no successful readback/replay")
        self.path = run / "ledger.jsonl"
        self.rows: list[dict[str, Any]] = []
        previous = "0" * 64
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                row = json.loads(line)
                digest = row.pop("hash")
                if row["previous"] != previous or digest_value(row) != digest:
                    raise ValueError("ledger hash chain corrupted; no repair/replay")
                row["hash"] = digest
                self.rows.append(row)
                previous = digest
        self.previous = previous
        starts: dict[str, dict[str, Any]] = {}
        terminals: set[str] = set()
        for row in self.rows:
            ident = row["id"]
            if row["event"] == "STARTED":
                if ident in starts:
                    raise ValueError("duplicate STARTED identity")
                starts[ident] = row
                verify_artifact(row["request"])
            elif row["event"] == "FINISHED":
                if ident not in starts or ident in terminals:
                    raise ValueError("orphan/duplicate terminal")
                terminals.add(ident)
                verify_artifact(row["result"])
                result = load(Path(row["result"]["path"]))
                for item in result.get("artifacts", []):
                    verify_artifact(item)
            else:
                raise ValueError("unknown ledger event")
        if set(starts) - terminals:
            raise RuntimeError(
                "uncertain STARTED attempt; explicit external reconciliation required"
            )

    def append(self, event: str, ident: str, **fields: Any) -> None:
        row = {"event": event, "id": ident, "previous": self.previous, **fields}
        row["hash"] = digest_value(row)
        with self.path.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.previous = row["hash"]
        self.rows.append(row)

    def results(self) -> dict[str, dict[str, Any]]:
        return {
            row["id"]: load(Path(row["result"]["path"]))
            for row in self.rows
            if row["event"] == "FINISHED"
        }


def verify_artifact(item: dict[str, Any]) -> None:
    p = Path(item["path"])
    if (
        p.is_symlink()
        or not p.is_file()
        or p.stat().st_size != item["bytes"]
        or sha(p) != item["sha256"]
    ):
        raise ValueError("artifact mutation/missing: " + str(p))


def tool(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file():
        raise ValueError("absolute existing tool required")
    return artifact(path.resolve(), "TOOL")


def build_receipt(path: Path, tools: dict[str, Any]) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("source_commit") != PIN or receipt.get("source_dirty") is not False:
        raise ValueError("pinned clean FFmpeg source receipt required")
    if (
        not receipt.get("compiler")
        or not receipt.get("spirv_compiler")
        or not receipt.get("configure_argv")
    ):
        raise ValueError("actual compiler/SPIR-V/configure provenance required")
    for name in ("ffmpeg", "ffprobe"):
        if receipt["tools"][name]["sha256"] != tools[name]["sha256"]:
            raise ValueError("receipt/tool mismatch")
    for item in receipt["evidence"]:
        verify_artifact(item)
    return {"receipt": artifact(path), "value": receipt}


def verify_session(session: dict[str, Any]) -> None:
    if source_identity() != session["source"]:
        raise ValueError("source/interpreter/dependency/environment/host identity drift")
    verify_artifact(session["audio"])
    verify_artifact(session["reference_artifact"])
    if session.get("installed_provenance"):
        verify_artifact(session["installed_provenance"]["inventory"])
    for value in session["tools"].values():
        if value is not None:
            for item in value.values():
                verify_artifact(item)
    if session.get("build"):
        verify_artifact(session["build"]["receipt"])
        value = session["build"]["value"]
        for item in [
            *value["evidence"],
            *value.get("library_identities", {}).values(),
            value["compiler_binary"],
            value["spirv_compiler_binary"],
        ]:
            verify_artifact(item)


def stop_group(proc: subprocess.Popen[bytes]) -> None:
    # Kill the group even after the leader exited; worker children must not leak.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        time.sleep(0.2)
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def observe_group(
    pgid: int,
    seen: set[tuple[int, int]],
    log: Path,
    tools: dict[str, Any],
    samples: dict[tuple[int, int], dict[str, Any]] | None = None,
) -> None:
    """Best-effort sampled Linux process-group argv, including spawned pool FFmpeg."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if os.getpgid(pid) != pgid:
                continue
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            generation = (pid, int(fields[19]))
            if samples is not None:
                previous = samples.get(generation, {})
                samples[generation] = {
                    "pid": pid,
                    "start_ticks": int(fields[19]),
                    "max_observed_threads": max(
                        previous.get("max_observed_threads", 0), int(fields[17])
                    ),
                    "max_observed_rss_bytes": max(
                        previous.get("max_observed_rss_bytes", 0),
                        int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                    ),
                    "observed_cpu_seconds": (int(fields[11]) + int(fields[12]))
                    / os.sysconf("SC_CLK_TCK"),
                    "scope": (
                        "sampled process; transient processes/peaks may be missed; "
                        "RSS is not tree peak"
                    ),
                }
            if generation in seen:
                continue
            raw = (entry / "cmdline").read_bytes()
            exe = (entry / "exe").resolve(strict=True)
            argv = [v.decode(errors="replace") for v in raw.split(b"\0") if v]
            record = {
                "pid": pid,
                "start_ticks": generation[1],
                "exe": str(exe),
                "argv": argv,
                "scope": "sampled process-group member; transient children may be missed",
            }
            if exe.name in ("ffmpeg", "ffprobe") and (
                str(exe) != tools[exe.name]["path"] or sha(exe) != tools[exe.name]["sha256"]
            ):
                raise RuntimeError("spawned media tool does not match frozen executable")
            with log.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
            seen.add(generation)
        except OSError:
            continue


def execute(
    run: Path, session: dict[str, Any], ident: str, request: dict[str, Any], kind: str
) -> dict[str, Any]:
    ledger = Ledger(run)
    existing = ledger.results()
    if ident in existing:
        return existing[ident]  # Readback, never a new throughput observation.
    limits = session["manifest"]["limits"]
    if len(existing) >= limits["attempts"]:
        raise RuntimeError("finite attempt allowance exhausted")
    spent = sum(
        row.get("accounted_wall_seconds", row["worker_wall_seconds"]) for row in existing.values()
    )
    estimate = limits["estimates"][kind]
    before = check_envelope(session, estimate, spent=spent)
    root = run / "attempts" / ident
    root.mkdir(parents=True, exist_ok=False)
    media = Path(session["media_root"]) / ident
    media.mkdir(exist_ok=False)
    tmp = root / "tmp"
    tmp.mkdir()
    request = {
        **request,
        "id": ident,
        "run": str(run),
        "media": str(media),
        "attempt": str(root),
        "session_sha256": sha(run / "session.json"),
    }
    save_new(root / "request.json", request)
    argv = [
        sys.executable,
        "-m",
        "ewp_waveform.application.experiment_suite",
        "_worker",
        "--request",
        str(root / "request.json"),
    ]
    env = {
        **os.environ,
        "TMPDIR": str(tmp),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C",
        "EWP_ANALYSIS_CACHE": str(media / "analysis-cache"),
    }
    ledger.append(
        "STARTED",
        ident,
        request=artifact(root / "request.json"),
        argv=argv,
        resource_admission=before,
        clock="monotonic worker lifetime",
    )
    started = time.monotonic()
    proc = None
    reason = None
    samples: dict[tuple[int, int], dict[str, Any]] = {}
    try:
        with (root / "stdout.txt").open("wb") as out, (root / "stderr.txt").open("wb") as err:
            proc = subprocess.Popen(argv, stdout=out, stderr=err, env=env, start_new_session=True)
            seen: set[tuple[int, int]] = set()
            selected_tools = session["tools"][
                "old" if request.get("cell", {}).get("scenario") == "A" else "new"
            ]
            while proc.poll() is None:
                observe_group(
                    proc.pid, seen, root / "observed-processes.jsonl", selected_tools, samples
                )
                time.sleep(0.2)
                # During execution do not reserve estimated growth/RAM a second time.
                check_envelope(
                    session,
                    {"growth_bytes": 0, "memory_bytes": 0, "seconds": 0},
                    elapsed=time.monotonic() - started,
                    spent=spent,
                )
            if proc.returncode:
                reason = "worker exit " + str(proc.returncode)

    except Exception as exc:
        reason = str(exc)
    finally:
        if proc is not None:
            try:
                stop_group(proc)
            except Exception as exc:
                reason = f"{reason + '; ' if reason else ''}group shutdown: {exc}"
        try:
            save_new(
                root / "process-samples.json",
                {
                    "polling_seconds": 0.2,
                    "processes": list(samples.values()),
                    "termination_reason": reason,
                    "incomplete": reason is not None,
                    "final_sample_guaranteed": False,
                    "scope": (
                        "best-effort process-group sampling; "
                        "not a complete process-tree CPU or RSS measurement"
                    ),
                },
            )
        except Exception as exc:
            reason = f"{reason + '; ' if reason else ''}sample evidence write: {exc}"
    wall = time.monotonic() - started
    worker_result = root / "worker-result.json"
    result: dict[str, Any] = load(worker_result) if worker_result.exists() else {"status": "FAILED"}
    if reason is not None:
        result.update(status="FAILED", error=reason, throughput_fresh=False)
    result.update(
        worker_wall_seconds=wall,
        polling_seconds=0.2,
        poll_overshoot="possible between checks and process-group termination",
        actual_action=result.get("actual_action", "UNKNOWN"),
    )
    files = [
        artifact(p, "ATTEMPT_EVIDENCE")
        for p in root.rglob("*")
        if p.is_file() and p.name != "result.json"
    ]
    partial = [
        artifact(p, "RETAINED_MEDIA_OR_WORK")
        for p in media.rglob("*")
        if p.is_file() and not p.is_symlink()
    ]
    result["artifacts"] = result.get("artifacts", []) + files + partial
    # Snapshot after group shutdown AND artifact hashing. Reserve our own result,
    # ledger row and emergency refusal receipt; this is prospective headroom, not
    # a promise that other filesystem users cannot consume the reserve afterward.
    allowance = 16384 + 2 * len(
        json.dumps({**result, "resource_final": before}, indent=2, sort_keys=True).encode()
    )
    result["final_write_allowance_bytes"] = allowance
    result["final_write_allowance_seconds"] = 0.25
    result["resource_final_scope"] = "post-shutdown/post-hash; prospective receipt headroom"
    try:
        result["resource_final"] = check_envelope(
            session,
            {"growth_bytes": allowance, "memory_bytes": 0, "seconds": 0.25},
            elapsed=time.monotonic() - started,
            spent=spent,
        )
        result["resource_final_status"] = "ADMITTED"
    except ResourceLimitError as exc:
        result.update(
            status="FAILED",
            error=str(exc),
            throughput_fresh=False,
            resource_final=exc.snapshot,
            resource_final_status="REFUSED",
        )
    result["worker_wall_seconds"] = time.monotonic() - started
    # Charge the bounded final-write interval to future admissions as well; do
    # not silently omit receipt I/O from cumulative suite elapsed accounting.
    result["accounted_wall_seconds"] = result["worker_wall_seconds"] + 0.25
    # Fail closed rather than silently exceeding the computed serialization bound.
    if len(json.dumps(result, indent=2, sort_keys=True).encode()) + 4096 > allowance:
        result.update(status="FAILED", error="final receipt size bound", throughput_fresh=False)
    save_new(root / "result.json", result)
    ledger.append("FINISHED", ident, result=artifact(root / "result.json"))
    try:
        final_snapshot = check_envelope(
            session,
            {"growth_bytes": 0, "memory_bytes": 0, "seconds": 0},
            elapsed=time.monotonic() - started,
            spent=spent,
        )
        # The final resource traversal is inside the admitted supervisor interval.
        # Sample after it; reuse its snapshot so refusal does not need another scan.
        complete_elapsed = time.monotonic() - started
        if complete_elapsed > result["accounted_wall_seconds"]:
            raise ResourceLimitError("final receipt elapsed bound exceeded", final_snapshot)
        limits = session["manifest"]["limits"]
        if (
            complete_elapsed > limits["attempt_seconds"]
            or spent + complete_elapsed > limits["seconds"]
        ):
            raise ResourceLimitError("final reconciliation time limit exceeded", final_snapshot)
    except ResourceLimitError as exc:
        if result["status"] != "FAILED":
            # Preserve immutable original bytes; make late external consumption or
            # unexpectedly slow receipt I/O an explicit refusal, never a PASS.
            save_new(root / "resource-refusal.json", {"error": str(exc), "resources": exc.snapshot})
            raise RuntimeError("final resource refusal after evidence writes: " + str(exc)) from exc
    return result
