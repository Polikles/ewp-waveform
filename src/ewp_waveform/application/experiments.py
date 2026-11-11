"""Bounded opt-in experiment application; scripts/experiments.py is only a CLI.

Two non-interchangeable measurements: shared pre-encode codec fixtures and real
production service calls. No imported media, decoded ProRes reference or GPU
fallback is used. All publication here is experimental, never an acceptance gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

from ewp_waveform.ffmpeg import experiments as ff
from ewp_waveform.ffmpeg.process import command_evidence

GIB = 1024**3
IMPLEMENTED = ff.CPU_ADAPTERS
CATALOG = (
    "MAP-CACHE",
    "COLUMN-ARRAY",
    "WORK-ROI",
    "SS-X1",
    "COLOR-CONST",
    "ENC-UTVIDEO",
    "FILTER-4",
    "CPU-12",
    "WSL-OLD-CPU",
    "WSL-NEW-CPU",
    *ff.GPU_ADAPTERS,
    "WSL-FFV1-CPU",
)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return cast(dict[str, Any], value)


def source_fingerprint() -> dict[str, Any]:
    import importlib.metadata

    import ewp_waveform
    import ewp_waveform.application
    import ewp_waveform.ffmpeg
    from ewp_waveform.config import load as configuration

    checkout = Path(configuration.__file__).resolve().parents[3]
    git = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    git_identity = git.stdout.splitlines() if git.returncode == 0 else None
    files: dict[str, str] = {}
    # Module-path precedence is respected, including an author-only staged overlay.
    for package in (ewp_waveform, ewp_waveform.application, ewp_waveform.ffmpeg):
        for directory in reversed(list(package.__path__)):
            for path in sorted(Path(directory).rglob("*.py")):
                key = str(path.relative_to(Path(directory)))
                files[package.__name__ + "/" + key] = sha(path)
    return {
        "git_head_and_tree": git_identity,
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("numpy", "pydantic", "typer")
        },
        "library_thread_environment": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "python": sys.version,
        "interpreter": str(Path(sys.executable).resolve()),
        "interpreter_sha256": sha(Path(sys.executable).resolve()),
        "source_files": files,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "gpu_device": None,
        "gpu_observation": "UNKNOWN_UNLESS_RUNTIME_PROBED",
    }


def tool_identity(name: str) -> dict[str, Any]:
    found = shutil.which(name)
    if not found:
        raise ValueError(f"tool not found: {name}")
    path = Path(found).resolve()
    argv = [str(path), "-version"]
    proc = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=15)
    return {"path": str(path), "sha256": sha(path), "build": proc.stdout, "argv": argv}


def available_memory_bytes() -> int | None:
    """Available physical memory, not an invented process-tree RSS measurement."""
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            return None
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "page_total",
                    "page_available",
                    "virtual_total",
                    "virtual_available",
                    "extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        windll: Any = getattr(ctypes, "windll", None)
        if windll is not None and windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.available)
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
        except (ValueError, OSError):
            return None
    return None


def tree_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def existing_parent(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    if not path.is_dir():
        raise ValueError("destination parent is not a directory")
    return path


def validate_roots(run: Path, media: Path) -> None:
    run, media = run.resolve(), media.resolve()
    if run == media or run in media.parents or media in run.parents:
        raise ValueError("media and evidence namespaces must be disjoint")
    # Neither media nor evidence may be placed inside any Git checkout.
    for root in (run, media):
        if any((parent / ".git").exists() for parent in (root, *root.parents)):
            raise ValueError("generated artifacts must remain outside Git")


@dataclass(frozen=True)
class Limits:
    attempts: int = 36
    seconds: int = 1800
    growth_bytes: int = 2 * GIB
    reserve_bytes: int = 10 * GIB

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if type(value) is not int or value <= 0:
                raise ValueError("positive integer budget required")
        if self.attempts > 36 or self.seconds > 1800 or self.growth_bytes > 2 * GIB:
            raise ValueError("screen envelope exceeds initial cap")
        if self.reserve_bytes < 10 * GIB:
            raise ValueError("at least 10GiB reserve required")


class Ledger:
    """Durable append-only records. Even uncertain STARTED consumes its identity."""

    def __init__(self, run: Path) -> None:
        self.path = run / "ledger.jsonl"

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        previous = "0" * 64
        for line in self.path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)  # A partial last write is a HOLD, never truncated/repaired.
            digest = item.pop("record_sha256")
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            if item["previous"] != previous or hashlib.sha256(encoded).hexdigest() != digest:
                raise ValueError("ledger chain mismatch: HOLD")
            previous = digest
            records.append({**item, "record_sha256": digest})
        return records

    def append(self, event: str, cell: str, **values: Any) -> None:
        records = self.read()
        item = {
            "ordinal": len(records),
            "previous": records[-1]["record_sha256"] if records else "0" * 64,
            "event": event,
            "cell": cell,
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **values,
        }
        encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        item["record_sha256"] = hashlib.sha256(encoded).hexdigest()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @contextmanager
    def locked(self) -> Iterator[None]:
        lock = self.path.parent / "active.lock"
        # Exclusive, fail-closed lock. An unclean parent exit requires inspection;
        # resume never guesses whether its descendants stopped or removes a hold.
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, str(os.getpid()).encode())
            os.close(descriptor)
            yield
        finally:
            lock.unlink()


def manifest(path: Path) -> dict[str, Any]:
    data = load(path)
    if set(data) != {
        "schema_version",
        "design_sha256",
        "candidates",
        "workloads",
        "limits",
        "catalog",
    }:
        raise ValueError("unknown/missing manifest keys")
    if data["schema_version"] != 1:
        raise ValueError("unsupported experiment manifest")
    if len(data["design_sha256"]) != 64 or any(
        c not in "0123456789abcdef" for c in data["design_sha256"]
    ):
        raise ValueError("design digest must be literal lowercase SHA256")
    candidates = data["candidates"]
    if (
        not candidates
        or len(candidates) > 3
        or len(set(candidates)) != len(candidates)
        or any(c not in IMPLEMENTED[1:] for c in candidates)
    ):
        raise ValueError("select one to three implemented CPU candidates")
    workloads = data["workloads"]
    if not 1 <= len(workloads) <= 3:
        raise ValueError("initial screen allows at most three short workloads")
    ids = set()
    for w in workloads:
        if set(w) != {"id", "start", "duration"} or w["id"] not in {"SPEECH4", "QUIET4", "TAIL4"}:
            raise ValueError("only the three short screening workload IDs are admitted")
        if w["id"] in ids:
            raise ValueError("duplicate workload")
        ids.add(w["id"])
        for key in ("start", "duration"):
            if type(w[key]) not in (int, float) or not math.isfinite(w[key]):
                raise ValueError("finite numeric interval required")
        if w["start"] < 0 or not 0 < w["duration"] <= 4:
            raise ValueError("screen intervals must be positive and <=4s; no production32/full")
    Limits(**data["limits"])
    if any(item.get("status") not in {"UNIMPLEMENTED", "NOT_RUN"} for item in data["catalog"]):
        raise ValueError("catalog entries cannot claim implementation/execution")
    return data


def stop_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    elif os.name == "nt":
        # Windows descendant termination is explicit; no shell or CPU fallback.
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    else:
        proc.kill()
    proc.wait(timeout=30)


def bounded_worker(
    run: Path, media: Path, request: dict[str, Any], limits: Limits, *, starting_bytes: int
) -> dict[str, Any]:
    ledger = Ledger(run)
    records = ledger.read()
    starts = [r for r in records if r["event"] == "STARTED"]
    finished_ids = {r["cell"] for r in records if r["event"] == "FINISHED"}
    if any(r["cell"] not in finished_ids for r in starts):
        raise ValueError("HOLD: an uncertain consumed STARTED exists; inspect without rerunning")
    if any(r["cell"] == request["id"] for r in starts):
        raise ValueError("consumed start: never rerun an uncertain, failed or completed attempt")
    elapsed = sum(float(r.get("elapsed_seconds", 0)) for r in records if r["event"] == "FINISHED")
    if len(starts) >= limits.attempts or elapsed >= limits.seconds:
        raise ValueError("attempt/time envelope exhausted")
    envelopes = [r for r in records if r["event"] == "ENVELOPE"]
    if envelopes:
        envelope = envelopes[0]
        if envelope["media"] != str(media.resolve()):
            raise ValueError("one run cannot change media volume/namespace")
        starting_bytes = envelope["media_initial_bytes"]
        evidence_initial = envelope["evidence_initial_bytes"]
    else:
        evidence_initial = tree_bytes(run)
        ledger.append(
            "ENVELOPE",
            "resources",
            media=str(media.resolve()),
            media_initial_bytes=starting_bytes,
            evidence_initial_bytes=evidence_initial,
            max_growth_bytes=2 * GIB,
            minimum_reserve_bytes=10 * GIB,
            ram_plan_bytes=GIB,
            ram_observed_available_bytes=available_memory_bytes(),
        )
    memory = available_memory_bytes()
    if memory is None or memory < GIB:
        raise ValueError("insufficient/unknown available RAM for 1GiB short-screen plan")

    def growth() -> int:
        return int(tree_bytes(media) - starting_bytes + tree_bytes(run) - evidence_initial)

    current_growth = growth()
    free = min(shutil.disk_usage(media).free, shutil.disk_usage(run).free)
    if (
        current_growth >= limits.growth_bytes
        or free - limits.reserve_bytes < limits.growth_bytes - current_growth
    ):
        raise ValueError("disk envelope/reserve refused; retained files are never deleted")
    req_path = run / f"{request['id']}.request.json"
    request = {**request, "launcher_pid": os.getpid()}
    save_new(req_path, request)
    argv = [sys.executable, "-m", "ewp_waveform.application.experiments", "_worker", str(req_path)]
    ledger.append("STARTED", request["id"], argv=argv, request_sha256=sha(req_path))
    t0 = time.perf_counter()
    creation: dict[str, Any] = (
        {"start_new_session": True}
        if os.name == "posix"
        else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    )
    reason = None
    with (
        (run / f"{request['id']}.stdout.txt").open("xb") as out,
        (run / f"{request['id']}.stderr.txt").open("xb") as err,
    ):
        proc = subprocess.Popen(argv, stdout=out, stderr=err, **creation)
        try:
            while proc.poll() is None:
                if time.perf_counter() - t0 > limits.seconds - elapsed:
                    reason = "TIME_LIMIT"
                elif growth() >= limits.growth_bytes:
                    reason = "GROWTH_LIMIT"
                elif shutil.disk_usage(media).free <= limits.reserve_bytes:
                    reason = "DISK_RESERVE"
                if reason:
                    stop_tree(proc)
                    break
                time.sleep(0.1)
        except BaseException:
            stop_tree(proc)
            # STARTED deliberately remains uncertain; no fabricated terminal result.
            raise
    result_path = Path(request["result"])
    if proc.returncode == 0 and result_path.is_file() and reason is None:
        result = load(result_path)
        status = "TECHNICAL_PASS"
    else:
        result = {
            "error": reason or f"worker exit {proc.returncode}",
            "stderr_path": str(run / f"{request['id']}.stderr.txt"),
            "diagnostic": (run / f"{request['id']}.stderr.txt").read_text(errors="replace")[-8192:],
        }
        status = "FAILED"
    ledger.append(
        "FINISHED",
        request["id"],
        status=status,
        elapsed_seconds=time.perf_counter() - t0,
        result_sha256=sha(result_path) if result_path.exists() else None,
        result_path=str(result_path),
        result=result,
    )
    return result


def _probe_request(
    run: Path, media: Path, tools: dict[str, Any], candidate: str, *, gpu: bool = False
) -> dict[str, Any]:
    ident = "probe-" + candidate.lower() + "-" + uuid.uuid4().hex[:8]
    return {
        "kind": "gpu-probe" if gpu else "cpu-probe",
        "id": ident,
        "candidate": candidate,
        "media": str(media / ident),
        "tools": tools,
        "commands": str(run / (ident + ".commands.jsonl")),
        "result": str(run / (ident + ".result.json")),
    }


def preflight(
    run: Path,
    media: Path,
    *,
    enable: list[str],
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    gpu_envelope: Path | None = None,
) -> dict[str, Any]:
    validate_roots(run, media)
    if not enable or len(set(enable)) != len(enable) or any(c not in IMPLEMENTED for c in enable):
        raise ValueError(
            "explicit --enable required; only implemented CPU adapters may be advertised"
        )
    gpu_spec = None
    if gpu_envelope is not None:
        gpu_spec = load(gpu_envelope)
        if (
            set(gpu_spec) != {"target", "adapters", "limits"}
            or gpu_spec["target"] != "WSL_GPU"
            or "microsoft" not in platform.release().lower()
        ):
            raise ValueError("GPU runtime probes require an explicit same-WSL target envelope")
        Limits(**gpu_spec["limits"])
        if not gpu_spec["adapters"] or any(
            name not in ff.GPU_ADAPTERS for name in gpu_spec["adapters"]
        ):
            raise ValueError("unknown/empty GPU adapter request; no fallback")
    tools = {"ffmpeg": tool_identity(ffmpeg), "ffprobe": tool_identity(ffprobe)}
    run.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    starting = tree_bytes(media)
    limits = Limits()
    result: dict[str, Any] = {
        "source": source_fingerprint(),
        "tools": tools,
        "enabled": enable,
        "adapters": {},
        "gpu": {},
        "free_bytes_before": shutil.disk_usage(media).free,
        "available_memory_bytes": available_memory_bytes(),
        "ram_plan_bytes": GIB,
    }
    with Ledger(run).locked():
        for candidate in dict.fromkeys(("CPU-BASE", *enable)):
            request = _probe_request(run, media, tools, candidate)
            outcome = bounded_worker(run, media, request, limits, starting_bytes=starting)
            result["adapters"][candidate] = {
                "status": "READY" if outcome.get("validation", {}).get("passed") else "SKIP",
                "probe": outcome,
                "nle": "PENDING",
            }
        for name in ff.GPU_ADAPTERS:
            result["gpu"][name] = {
                "status": "SKIP",
                "reason": "separate target GPU envelope required; NOT_RUN",
            }
        if gpu_spec is not None:
            gpu_limits = Limits(**gpu_spec["limits"])
            for name in gpu_spec["adapters"]:
                request = _probe_request(run, media, tools, name, gpu=True)
                outcome = bounded_worker(run, media, request, gpu_limits, starting_bytes=starting)
                result["gpu"][name] = {
                    "status": "RUNTIME_PASS"
                    if outcome.get("validation", {}).get("passed")
                    else "SKIP",
                    "probe": outcome,
                    "device": outcome.get("device"),
                    "baseline": "NOT_RUN; fresh same-WSL CPU baseline required",
                }
        path = run / ("preflight-" + uuid.uuid4().hex + ".json")
        save_new(path, result)
    return {"preflight": str(path), **result}


def prepare(
    run: Path,
    media: Path,
    *,
    manifest_path: Path,
    audio: Path,
    input_sha256: str,
    preflight_path: Path,
    enable: list[str],
    nle_record: Path | None = None,
) -> dict[str, Any]:
    validate_roots(run, media)
    data = manifest(manifest_path)
    if len(input_sha256) != 64 or any(c not in "0123456789abcdef" for c in input_sha256):
        raise ValueError("literal lowercase input SHA256 required")
    if not audio.is_file() or sha(audio) != input_sha256:
        raise ValueError("input identity mismatch")
    cap = load(preflight_path)
    if cap["source"] != source_fingerprint():
        raise ValueError("source/interpreter/host changed after preflight")
    for name, item in cap["tools"].items():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"{name} changed after preflight")
    if set(enable) != set(data["candidates"]):
        raise ValueError(
            "explicit enabled adapters must exactly match selected manifest candidates"
        )
    from ewp_waveform.application.service import plan_jobs

    # Production read-only planning proves effective source clipping before allocation.
    frozen_workloads = []
    for w in data["workloads"]:
        _, preset, _, plans, _ = plan_jobs(
            audio,
            preset_name="iuris-ribbon-refined",
            output_dir=media,
            formats=["prores4444"],
            start=w["start"],
            duration=w["duration"],
        )
        if len(plans) != 1 or plans[0].media is None or plans[0].action == "BLOCKED":
            raise ValueError("source could not be planned")
        if w["start"] + w["duration"] > plans[0].media.duration_seconds:
            raise ValueError("screen interval extends past EOF")
        frozen_workloads.append(
            {
                **w,
                "preset": preset.model_dump(mode="json"),
                "frames": math.ceil(w["duration"] * preset.canvas.fps),
                "fps": str(Fraction(str(preset.canvas.fps))),
                "width": preset.canvas.width,
                "height": preset.canvas.height,
            }
        )
    nle = load(nle_record) if nle_record else None
    ffv1_nle_pass = bool(
        nle
        and nle.get("codec") == "ffv1"
        and nle.get("container") == "matroska"
        and nle.get("studio_version")
        and nle.get("platform")
        and all(nle.get(k) is True for k in ("import", "alpha", "seek"))
    )
    cells = []
    for wi, w in enumerate(frozen_workloads):
        for ci, name in enumerate(enable):
            # One deterministic AB / BA pair per selected candidate/workload/scope.
            order = ("CPU-BASE", name) if (wi + ci) % 2 == 0 else (name, "CPU-BASE")
            for scope in ("codec", "service"):
                for position, variant in enumerate(order):
                    skip = None
                    if cap["adapters"].get(variant, {}).get("status") != "READY":
                        skip = "adapter runtime probe did not pass"
                    if name == "ENC-FFV1" and not ffv1_nle_pass:
                        skip = (
                            "FFV1 Studio import/alpha/seek prerequisite PENDING; "
                            "tiny probe retained"
                        )
                    if scope == "service" and name == "ENC-FFV1":
                        skip = "FFV1 production format contract deliberately not expanded"
                    cells.append(
                        {
                            "id": f"{w['id'].lower()}-{name.lower()}-{scope}-{position}",
                            "workload": w["id"],
                            "pair": name,
                            "variant": variant,
                            "scope": scope,
                            "skip": skip,
                        }
                    )
    # Preparation consumes one attempt per clip. Reject an overfull matrix up front.
    limits = Limits(**data["limits"])
    consumed = sum(r["event"] == "STARTED" for r in Ledger(run).read())
    planned = len(frozen_workloads) + sum(not c["skip"] for c in cells)
    if consumed + planned > limits.attempts:
        raise ValueError(
            "planned probes+fixtures+cells exceed attempt cap; select fewer workloads/candidates"
        )
    run.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    session = {
        "schema_version": 1,
        "manifest": data,
        "manifest_sha256": sha(manifest_path),
        "preflight": str(preflight_path.resolve()),
        "preflight_sha256": sha(preflight_path),
        "source": cap["source"],
        "tools": cap["tools"],
        "audio": str(audio.resolve()),
        "input_sha256": input_sha256,
        "media": str(media.resolve()),
        "workloads": frozen_workloads,
        "cells": cells,
        "initial_media_bytes": tree_bytes(media),
        "nle": nle,
        "created_monotonic": time.monotonic(),
        "analysis_cache": "isolated empty per service call",
        "context": (
            "production clipped analysis; frozen noise absolute source origin; "
            "not full-source context"
        ),
    }
    with Ledger(run).locked():
        save_new(run / "session.json", session)
        Ledger(run).append("PREPARED", "session", session_sha256=sha(run / "session.json"))
    return {
        "session": str(run / "session.json"),
        "cells": cells,
        "planned_attempts": planned,
        "consumed_attempts": consumed,
        "fixtures": "NOT_RUN; batch/resume prepares each once before codec/service cells",
    }


def verified_session(run: Path) -> dict[str, Any]:
    session = load(run / "session.json")
    prepared = next(r for r in Ledger(run).read() if r["event"] == "PREPARED")
    if prepared["session_sha256"] != sha(run / "session.json"):
        raise ValueError("frozen session changed")
    if session["source"] != source_fingerprint():
        raise ValueError("frozen source/interpreter/host changed")
    for item in session["tools"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("frozen encoder/probe binary changed")
    if sha(Path(session["audio"])) != session["input_sha256"]:
        raise ValueError("source input changed")
    return session


def readback(ledger: Ledger, ident: str) -> dict[str, Any] | None:
    rows = [r for r in ledger.read() if r["cell"] == ident]
    started = any(r["event"] == "STARTED" for r in rows)
    terminal = next((r for r in rows if r["event"] == "FINISHED"), None)
    if not started:
        return None
    if terminal is None:
        raise ValueError(f"HOLD uncertain consumed STARTED: {ident}; never automatically rerun")
    if terminal["status"] != "TECHNICAL_PASS":
        raise ValueError(f"HOLD failed consumed attempt: {ident}")
    path = Path(terminal["result_path"])
    if sha(path) != terminal["result_sha256"]:
        raise ValueError("completed result changed: HOLD")
    result = load(path)
    if (
        result.get("commands_path")
        and sha(Path(result["commands_path"])) != result["commands_sha256"]
    ):
        raise ValueError("completed commands changed: HOLD")
    for item in result.get("artifacts", []):
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("completed artifact changed: HOLD")
    ledger.append("READBACK", ident, actual_action="READBACK_NOT_PROCESS", throughput_fresh=False)
    return result


def run_cells(run: Path, *, cell: str | None = None) -> dict[str, Any]:
    session = verified_session(run)
    media, ledger = Path(session["media"]), Ledger(run)
    limits = Limits(**session["manifest"]["limits"])
    chosen = [c for c in session["cells"] if cell is None or c["id"] == cell]
    if not chosen:
        raise ValueError("unknown cell identity")
    with ledger.locked():
        for c in chosen:
            if c["skip"]:
                if not any(r["cell"] == c["id"] for r in ledger.read()):
                    ledger.append("SKIP", c["id"], reason=c["skip"], throughput_fresh=False)
                continue
            w = next(w for w in session["workloads"] if w["id"] == c["workload"])
            prep_id = w["id"].lower() + "-fixture"
            prepared = readback(ledger, prep_id)
            if prepared is None:
                req = {
                    "kind": "prepare",
                    "id": prep_id,
                    "session": str(run / "session.json"),
                    "workload": w,
                    "media": str(media / prep_id),
                    "commands": str(run / (prep_id + ".commands.jsonl")),
                    "result": str(run / (prep_id + ".result.json")),
                }
                prepared = bounded_worker(
                    run, media, req, limits, starting_bytes=session["initial_media_bytes"]
                )
                if not prepared.get("fixture"):
                    raise ValueError("fixture preparation failed; no automatic retry")
            if readback(ledger, c["id"]) is not None:
                verify_pair(ledger, session, c)
                continue
            req = {
                "kind": "cell",
                **c,
                "session": str(run / "session.json"),
                "workload_config": w,
                "fixture": prepared,
                "media": str(media / c["id"]),
                "commands": str(run / (c["id"] + ".commands.jsonl")),
                "result": str(run / (c["id"] + ".result.json")),
            }
            result = bounded_worker(
                run, media, req, limits, starting_bytes=session["initial_media_bytes"]
            )
            if not result.get("validation", {}).get("passed"):
                raise ValueError("screen failed; retained without retry")
            verify_pair(ledger, session, c)
    return report(run)


def verify_pair(ledger: Ledger, session: dict[str, Any], cell: dict[str, Any]) -> None:
    members = [
        c
        for c in session["cells"]
        if c["pair"] == cell["pair"]
        and c["scope"] == cell["scope"]
        and c["workload"] == cell["workload"]
    ]
    finished = {r["cell"]: r for r in ledger.read() if r["event"] == "FINISHED"}
    if len(members) != 2 or not all(c["id"] in finished for c in members):
        return
    member_ids = sorted(c["id"] for c in members)
    if any(
        r["event"] == "PAIR_REJECTED" and sorted(r.get("members", [])) == member_ids
        for r in ledger.read()
    ):
        raise ValueError("paired effective-difference rejection remains HOLD")
    if any(
        r["event"] == "PAIR_VERIFIED" and sorted(r["members"]) == member_ids for r in ledger.read()
    ):
        return
    control = next(finished[c["id"]]["result"] for c in members if c["variant"] == "CPU-BASE")
    candidate = next(finished[c["id"]]["result"] for c in members if c["variant"] != "CPU-BASE")
    try:
        if control["frozen_context"] != candidate["frozen_context"]:
            raise ValueError("effective paired input/analysis/normalization/noise context changed")
        ff.check_effective_diff(
            control["effective_settings"], candidate["effective_settings"], cell["pair"]
        )
        ff.check_command_diff(control["encode_argv"], candidate["encode_argv"], cell["pair"])
    except ValueError as exc:
        ledger.append(
            "PAIR_REJECTED", cell["id"], error=str(exc), members=member_ids, throughput_fresh=False
        )
        raise
    ledger.append(
        "PAIR_VERIFIED",
        cell["id"],
        members=[c["id"] for c in members],
        effective_config_and_argv_differences=cell["pair"],
        visual_review="PENDING",
    )


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def prepare_fixture(request: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.application import render as rendering
    from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
    from ewp_waveform.application.render_fixed import FixedHooks, run_fixed_pipeline
    from ewp_waveform.application.service import plan_jobs
    from ewp_waveform.application.timing import PhaseTimes

    w, root = request["workload"], Path(request["media"])
    root.mkdir()
    raw = root / "canonical-before-encode.rgba"
    _, preset, performance, plans, _ = plan_jobs(
        Path(session["audio"]),
        preset_name="iuris-ribbon-refined",
        output_dir=root,
        formats=["prores4444"],
        start=w["start"],
        duration=w["duration"],
    )
    # Existing production short-clip path is serial even with jobs=2.
    performance = performance.model_copy(deep=True)
    performance.processing.update(jobs=2, ffmpeg_threads=0)
    plan = plans[0]
    assert plan.media is not None
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}
    clock = PhaseTimes()
    appearance = resolve_fixed_axis_appearance(preset)
    commands = Path(request["commands"])

    class Hooks:
        def __getattr__(self, name: str) -> Any:
            return getattr(rendering, name)

        def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def encode_rgba_stream(self, frames: Any, **kwargs: Any) -> None:
            ff.finish_fixture(
                frames,
                raw,
                ffmpeg=session["tools"]["ffmpeg"]["path"],
                command_log=commands,
                **kwargs,
            )

    class Publication:
        def publish_mov(self, path: Path, *, failure_message: str) -> None:
            if not raw.is_file():
                raise ValueError(failure_message)

        def publish_png(self, path: Path) -> None:
            raise ValueError("no simultaneous PNG fixture")

    started = time.perf_counter()
    with command_evidence(commands):
        run_fixed_pipeline(
            cast(FixedHooks, Hooks()),
            job=plan.job,
            media=plan.media,
            preset=preset,
            performance=performance,
            appearance=appearance,
            spectrum_contour=False,
            ribbon_ss=appearance.ribbon_ss,
            source_sha=session["input_sha256"],
            clip_start=w["start"],
            clip_duration=w["duration"],
            expected_frames=w["frames"],
            work=root / "work",
            producing_mov=True,
            producing_png=False,
            glow=rendering._glow_sigma(preset),
            threads=0,
            note=lambda _: None,
            lifecycle=Publication(),
            analysis=analysis,
            normalization=normalization,
            clock=clock,
        )
    preparation_seconds = time.perf_counter() - started
    crop = ff.freeze_crop(raw, width=w["width"], height=w["height"], frames=w["frames"], margin=4)
    if sha(Path(session["audio"])) != session["input_sha256"]:
        raise ValueError("input mutated during preparation")
    return {
        "fixture": str(raw),
        "artifacts": [artifact(raw)],
        "crop": asdict(crop),
        "crop_transform": crop.record(),
        "preparation_seconds": preparation_seconds,
        "scope": "PRODUCTION_PIPELINE_PRE_ENCODE_RGBA8_NOT_A_SERVICE_TIMING",
        "analysis": analysis,
        "normalization": normalization,
        "appearance": appearance.identity(),
        "preset": preset.model_dump(mode="json"),
        "performance": performance.model_dump(mode="json"),
        "validation": {"passed": True, "frames": w["frames"]},
    }


def run_cell(request: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    w, fixture = request["workload_config"], request["fixture"]
    root = Path(request["media"])
    root.mkdir()
    commands = Path(request["commands"])
    crop = ff.Crop(**fixture["crop"])
    name = request["variant"]
    settings = ff.codec_settings(name, crop)
    diffs = ff.check_effective_diff(ff.codec_settings("CPU-BASE", crop), settings, name)
    raw = Path(fixture["fixture"])
    if sha(raw) != fixture["artifacts"][0]["sha256"]:
        raise ValueError("shared canonical fixture changed")
    service_result = None
    if request["scope"] == "codec":
        output = root / ("tested-master.mkv" if name == "ENC-FFV1" else "tested-master.mov")
        argv = ff.codec_argv(
            session["tools"]["ffmpeg"]["path"],
            raw,
            output,
            width=w["width"],
            height=w["height"],
            fps=w["fps"],
            candidate=name,
            crop=crop,
        )
        control = ff.codec_argv(
            session["tools"]["ffmpeg"]["path"],
            raw,
            output,
            width=w["width"],
            height=w["height"],
            fps=w["fps"],
            candidate="CPU-BASE",
            crop=crop,
        )
        ff.check_command_diff(control, argv, name)
        ff.record_command(commands, argv, phase="timed-codec")
        start = time.perf_counter()
        result = subprocess.run(argv, capture_output=True, check=True)
        wall = time.perf_counter() - start
        if result.stderr.strip():
            raise ValueError("encoder diagnostics")
        scope = "CODEC_ONLY_SHARED_RGBA8_INPUT_INCLUDES_REQUIRED_CONVERSION_AND_CONTAINER"
    else:
        from ewp_waveform.application.experiments_render import ServiceExperiment
        from ewp_waveform.application.service import render

        perf = root / "performance.toml"
        perf.write_text(
            'schema_version=1\nname="experiment"\n[processing]\njobs=2\nffmpeg_threads=0\n'
            "[workdirs]\npersistent=false\nkeep_on_success=false\nkeep_on_failure=true\n"
            f"root={json.dumps(str(root / 'work'))}\n",
            encoding="utf-8",
        )
        os.environ["EWP_ANALYSIS_CACHE"] = str(root / "analysis-cache")
        start = time.perf_counter()
        with command_evidence(commands):
            payloads = render(
                Path(session["audio"]),
                output_dir=root / "output",
                preset_name="iuris-ribbon-refined",
                performance_name=str(perf),
                formats=["prores4444"],
                start=w["start"],
                duration=w["duration"],
                force=True,
                experiment=ServiceExperiment(
                    ff.EncodeExperiment(name, crop if name == "CROP-OUT" else None, commands)
                ),
            )
        wall = time.perf_counter() - start
        service_result = cast(dict[str, Any], payloads[0])
        if (
            service_result["job"]["status"] != "SUCCEEDED"
            or not service_result["validation"]["passed"]
            or service_result.get("resume_history")
            or service_result.get("performance", {}).get("extras", {}).get("reused_output_formats")
        ):
            raise ValueError("service was not fresh validated PROCESS")
        output = Path(service_result["outputs"][0]["path"])
        actual = [
            load_line
            for load_line in map(json.loads, commands.read_text().splitlines())
            if load_line["phase"] == "application-encode"
        ]
        if len(actual) != 1:
            raise ValueError("only observed serial production encode admitted")
        argv = actual[0]["argv"]
        scope = "ACTUAL_APPLICATION_SERVICE_RENDER_INCLUDES_VALIDATION_AND_PUBLICATION"
    width = crop.width if name == "CROP-OUT" else w["width"]
    height = crop.height if name == "CROP-OUT" else w["height"]
    validation = ff.inspect_master(
        session["tools"]["ffmpeg"]["path"],
        session["tools"]["ffprobe"]["path"],
        output,
        width=width,
        height=height,
        fps=w["fps"],
        frames=w["frames"],
        candidate=name,
        command_log=commands,
        reference=raw,
        crop=crop if name == "CROP-OUT" else None,
    )
    if name == "ENC-FFV1" and validation["decoded_rgba_sha256"] != sha(raw):
        raise ValueError("FFV1 did not preserve the common canonical buffer")
    if service_result:
        if service_result["normalization"] != fixture["normalization"]:
            raise ValueError("effective production normalization differs from frozen preparation")
        if service_result["resolved_visual_config"]["effective_preset"] != fixture["preset"]:
            raise ValueError("effective visual configuration changed")
        recipe = dict(service_result["resolved_visual_config"]["fixed_axis_recipe"])
        recipe.pop("experiment", None)
        if recipe != fixture["appearance"]:
            raise ValueError("effective application recipe differs from frozen preparation")
    return {
        "scope": scope,
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "wall_seconds": wall,
        "timer": (
            "perf_counter before/after codec process; setup/hash/full validation excluded"
            if request["scope"] == "codec"
            else (
                "perf_counter before/after actual service.render; "
                "production hashing/validation/publication included; "
                "external full validation excluded"
            )
        ),
        "encode_argv": argv,
        "frozen_context": {
            "input_sha256": session["input_sha256"],
            "fixture_sha256": fixture["artifacts"][0]["sha256"],
            "workload": w,
            "appearance": fixture["appearance"],
            "normalization": fixture["normalization"],
        },
        "effective_settings": settings,
        "effective_differences": diffs,
        "crop_transform": crop.record() if name == "CROP-OUT" else None,
        "validation": validation,
        "service_result": service_result,
        "artifacts": [artifact(output)],
        "commands_sha256": sha(commands),
        "commands_path": str(commands),
        "visual_review": "PENDING",
        "nle_review": "PENDING",
        "viewing_derivatives": "NOT_RUN; create only after timed cells in a separate admitted task",
    }


def worker(request_path: Path) -> None:
    request = load(request_path)
    if request.get("launcher_pid") != os.getppid():
        raise ValueError("internal worker requires its admitted live parent; no replay")
    records = Ledger(request_path.parent).read()
    if any(r["event"] == "FINISHED" and r["cell"] == request["id"] for r in records):
        raise ValueError("completed worker request cannot be replayed")
    start = next(
        r
        for r in Ledger(request_path.parent).read()
        if r["event"] == "STARTED" and r["cell"] == request["id"]
    )
    if start["request_sha256"] != sha(request_path):
        raise ValueError("worker request changed after durable STARTED")
    tools = request.get("tools") or load(Path(request["session"]))["tools"]
    os.environ["PATH"] = os.pathsep.join(
        dict.fromkeys(
            [str(Path(item["path"]).parent) for item in tools.values()]
            + os.environ.get("PATH", "").split(os.pathsep)
        )
    )
    for name, item in tools.items():
        found = shutil.which(name)
        if (
            found is None
            or Path(found).resolve() != Path(item["path"])
            or sha(Path(found)) != item["sha256"]
        ):
            raise ValueError("effective executable resolution does not match frozen tools")
    if request["kind"] in {"cpu-probe", "gpu-probe"}:
        root = Path(request["media"])
        root.mkdir()
        tools, name = request["tools"], request["candidate"]
        raw, out = (
            root / "probe.rgba",
            root
            / (
                "probe.mov" if "PRORES" in name or name in {"CPU-BASE", "CROP-OUT"} else "probe.mkv"
            ),
        )
        commands = Path(request["commands"])
        if request["kind"] == "gpu-probe":
            argv = ff.gpu_probe_argv(tools["ffmpeg"]["path"], name, out)
        else:
            frame = bytes([199, 230, 236, 0]) * 256
            active = bytearray(frame)
            for y in range(4, 12):
                for x in range(4, 12):
                    active[(y * 16 + x) * 4 + 3] = 128
            raw.write_bytes(bytes(active) * 2)
            crop = ff.Crop(2, 2, 12, 12, 16, 16)
            argv = ff.codec_argv(
                tools["ffmpeg"]["path"],
                raw,
                out,
                width=16,
                height=16,
                fps="30/1",
                candidate=name,
                crop=crop,
                threads=1,
            )
        ff.record_command(commands, argv, phase="runtime-alpha-probe")
        subprocess.run(argv, capture_output=True, check=True, timeout=30)
        dims = 12 if name == "CROP-OUT" else 16
        validation = ff.inspect_master(
            tools["ffmpeg"]["path"],
            tools["ffprobe"]["path"],
            out,
            width=dims,
            height=dims,
            fps="30/1",
            frames=2,
            candidate="ENC-FFV1" if name in {"GPU-TRANSFER", "GPU-BLUR", "GPU-FFV1"} else name,
            command_log=commands,
        )
        if name == "ENC-FFV1" and validation["decoded_rgba_sha256"] != sha(raw):
            raise ValueError("tiny FFV1 alpha probe was not lossless relative to common input")
        result = {
            "validation": validation,
            "artifacts": [artifact(out)],
            "device": None,
            "device_note": (
                "runtime success does not identify physical device; "
                "unknown unless separately observed"
            ),
        }
    else:
        session = verified_session(Path(request["session"]).parent)
        result = (
            prepare_fixture(request, session)
            if request["kind"] == "prepare"
            else run_cell(request, session)
        )
    save_new(Path(request["result"]), result)


def report(run: Path) -> dict[str, Any]:
    ledger = Ledger(run).read()
    session = load(run / "session.json") if (run / "session.json").exists() else None
    cells = []
    for c in session["cells"] if session else []:
        records = [r for r in ledger if r["cell"] == c["id"]]
        finish = next((r for r in records if r["event"] == "FINISHED"), None)
        skip = any(r["event"] == "SKIP" for r in records)
        started = any(r["event"] == "STARTED" for r in records)
        status = (
            finish["status"]
            if finish
            else "SKIP"
            if skip
            else "HOLD_UNCERTAIN"
            if started
            else "NOT_RUN"
        )
        result = finish.get("result") if finish else None
        if finish and finish["status"] == "TECHNICAL_PASS" and result is not None:
            try:
                if sha(Path(finish["result_path"])) != finish["result_sha256"]:
                    raise ValueError("result changed")
                for item in result.get("artifacts", []):
                    if sha(Path(item["path"])) != item["sha256"]:
                        raise ValueError("artifact changed")
                if (
                    result.get("commands_path")
                    and sha(Path(result["commands_path"])) != result["commands_sha256"]
                ):
                    raise ValueError("commands changed")
            except (OSError, ValueError):
                status = "HOLD_READBACK_CHANGED"
        cells.append(
            {
                **c,
                "status": status,
                "actual_action": "PROCESS" if finish else "NOT_RUN",
                "report_action": "READBACK_NOT_PROCESS",
                "result": {**result, "throughput_fresh": False} if result else None,
                "fresh_on_resume": False,
                "speedup": None,
            }
        )
    return {
        "cells": cells,
        "cell_count": len(cells),
        "render_fixture_attempts": sum(r["event"] == "STARTED" for r in ledger),
        "measured_screen_seconds": sum(
            r.get("elapsed_seconds", 0) for r in ledger if r["event"] == "FINISHED"
        ),
        "catalog": [{"id": c, "status": "UNIMPLEMENTED", "execution": "NOT_RUN"} for c in CATALOG],
        "visual_review": "PENDING",
        "nle_review": "PENDING",
        "speedup": None,
        "scope_note": (
            "codec and service costs are separate; no automatic visual acceptance "
            "or cross-host/whole-renderer speedup"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Argparse transport only; operations above own all application behavior."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "prepare", "one", "batch", "resume", "report"):
        p = sub.add_parser(command)
        p.add_argument("--run", type=Path, required=True)
        if command in {"preflight", "prepare"}:
            p.add_argument("--media-root", type=Path, required=True)
            p.add_argument("--enable", action="append", required=True, choices=IMPLEMENTED)
        if command == "preflight":
            p.add_argument("--ffmpeg", default="ffmpeg")
            p.add_argument("--ffprobe", default="ffprobe")
            p.add_argument("--gpu-envelope", type=Path)
        if command == "prepare":
            p.add_argument("--manifest", type=Path, required=True)
            p.add_argument("--audio", type=Path, required=True)
            p.add_argument("--input-sha256", required=True)
            p.add_argument("--preflight", type=Path, required=True)
            p.add_argument("--nle-record", type=Path)
        if command == "one":
            p.add_argument("--cell", required=True)
    p = sub.add_parser("_worker", help=argparse.SUPPRESS)
    p.add_argument("request", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "_worker":
            worker(args.request)
            return 0
        if args.command == "preflight":
            value = preflight(
                args.run,
                args.media_root,
                enable=args.enable,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                gpu_envelope=args.gpu_envelope,
            )
        elif args.command == "prepare":
            value = prepare(
                args.run,
                args.media_root,
                manifest_path=args.manifest,
                audio=args.audio,
                input_sha256=args.input_sha256,
                preflight_path=args.preflight,
                enable=args.enable,
                nle_record=args.nle_record,
            )
        elif args.command == "report":
            value = report(args.run)
        else:
            value = run_cells(args.run, cell=args.cell if args.command == "one" else None)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"experiment refused/held: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
