"""Maintained single-command experiment application for Linux/WSL and Windows.

Only this module's stdlib bootstrap runs in the invoking interpreter. Every
production/backend action is a separately supervised Python 3.12 worker. Optional
backend failures are retained independently and never prevent CPU/CUDA dispatch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import shutil
import struct
import sys
import traceback
import uuid
import wave
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_process import run_command
from ewp_waveform.application.portable_experiments_reporting import (
    diagnostic_bundle as diagnostic_bundle,
)
from ewp_waveform.application.portable_experiments_reporting import (
    report as report,
)
from ewp_waveform.application.portable_experiments_state import (
    append_event,
    check_budget,
    completed_steps,
    environment_details,
    identity,
    load,
    lock,
    outside_git,
    resources,
    save,
    source_identity,
    verify,
)

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "scripts/run_experiments.py"
DEFAULT_SHA256 = "e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b"
DEFAULT_BYTES = 37985180


def child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}


def discover_tools(path: str) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {"ffmpeg": [], "ffprobe": []}
    for directory in dict.fromkeys(path.split(os.pathsep)):
        for name, entries in found.items():
            candidate = Path(directory or ".") / (name + (".exe" if os.name == "nt" else ""))
            if candidate.is_file() and os.access(candidate, os.X_OK):
                item = identity(candidate)
                if item not in entries:
                    entries.append(item)
    return found


def original_inventory(run: Path, media: Path) -> dict[str, Any]:
    """Persist original environment BEFORE any interpreter/PATH or uv selection."""
    original_path = os.environ.get("PATH", "")
    value: dict[str, Any] = {
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),  # noqa: UP017
        "original_path": original_path,
        "platform": platform.platform(),
        "os_release": Path("/etc/os-release").read_text(errors="replace")
        if Path("/etc/os-release").is_file()
        else None,
        "bootstrap_python": {
            "version": sys.version,
            "prefix": sys.prefix,
            "binary": identity(Path(sys.executable)),
        },
        "resources": resources(),
        "tools": discover_tools(original_path),
        "first_path_tools": {
            name: shutil.which(name)
            for name in ("ffmpeg", "ffprobe", "uv", "nvidia-smi", "vulkaninfo")
        },
        "storage": {
            "run_free_bytes": shutil.disk_usage(run).free,
            "media_free_bytes": shutil.disk_usage(media).free,
        },
        "original_environment": {
            name: os.environ.get(name)
            for name in (
                "VIRTUAL_ENV",
                "CONDA_PREFIX",
                "CUDA_VISIBLE_DEVICES",
                "VK_ICD_FILENAMES",
                "VK_DRIVER_FILES",
                "OMP_NUM_THREADS",
                "NUMBER_OF_PROCESSORS",
                "WSL_DISTRO_NAME",
            )
        },
    }
    save(run / "original-environment.json", value)
    observations: dict[str, Any] = {}
    for name, arguments in (
        ("uv", ["--version"]),
        ("nvidia-smi", ["--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]),
        ("vulkaninfo", ["--summary"]),
    ):
        executable = value["first_path_tools"][name]
        observations[name] = (
            {
                "binary": identity(Path(executable)),
                **run_command([executable, *arguments], run / ("original-" + name), timeout=20),
            }
            if executable
            else {"status": "NOT_FOUND"}
        )
    save(run / "original-observations.json", observations)
    return value


def python_candidates() -> list[Path]:
    return [ROOT / ".venv/Scripts/python.exe", ROOT / ".venv/bin/python"]


def probe_python(python: Path, folder: Path, *, optional: bool = False) -> dict[str, Any]:
    observed = run_command(
        [str(python), str(DRIVER), "--_environment", *(["--_optional"] if optional else [])],
        folder,
        env=child_env(),
        cwd=ROOT,
        timeout=60,
    )
    if observed["returncode"] != 0 or observed["error"]:
        raise ValueError(
            f"Python environment unavailable: {observed['error']}\n{observed['stderr']}"
        )
    # Full environment provenance may exceed the bounded stdout excerpt.
    return json.loads((folder / "stdout.txt").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def select_python(explicit: Path | None, run: Path) -> tuple[Path, dict[str, Any]]:
    candidates = [explicit.expanduser().absolute()] if explicit else python_candidates()
    for index, candidate in enumerate(candidates):
        if candidate.is_file():
            try:
                return candidate, probe_python(candidate, run / f"python-candidate-{index}")
            except ValueError:
                if explicit:
                    raise
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("provide uv, checkout .venv, or --python pointing to a frozen Python 3.12")
    # Never repair an existing user environment: setup gets its own namespace.
    target = run / "python-env"
    outside_git([target])
    observed = run_command(
        [uv, "sync", "--frozen", "--no-dev", "--python", "3.12", "--project", str(ROOT)],
        run / "uv-sync",
        timeout=900,
        env={
            **child_env(),
            "UV_PROJECT_ENVIRONMENT": str(target),
            "UV_CACHE_DIR": str(run / "uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(run / "python-managed"),
        },
        cwd=ROOT,
    )
    if observed["returncode"] != 0 or observed["error"]:
        raise ValueError(
            "uv sync --frozen failed; no dependency versions changed\n" + observed["stderr"]
        )
    selected = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return selected, probe_python(selected, run / "selected-python")


def inventory_pair(ffmpeg: Path, ffprobe: Path, root: Path) -> dict[str, Any]:
    pair = {"ffmpeg": identity(ffmpeg), "ffprobe": identity(ffprobe)}
    # Production adapters resolve names via PATH. Require a matching same-bin pair.
    if ffmpeg.parent.resolve() != ffprobe.parent.resolve():
        raise ValueError("ffmpeg and ffprobe must be in the same bin directory")
    names = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
    if (ffmpeg.name.lower(), ffprobe.name.lower()) != names:
        raise ValueError("tool names must be ffmpeg/ffprobe (native Windows .exe supported)")
    observations = {}
    for label, argv in (
        ("version", [str(ffmpeg), "-version"]),
        ("buildconf", [str(ffmpeg), "-buildconf"]),
        ("filters", [str(ffmpeg), "-filters"]),
        ("encoders", [str(ffmpeg), "-encoders"]),
        ("hwaccels", [str(ffmpeg), "-hwaccels"]),
        ("ffprobe-version", [str(ffprobe), "-version"]),
    ):
        record = run_command(argv, root / label)
        observations[label] = record
        if record["returncode"] != 0 or record["error"]:
            raise ValueError(f"tool inventory failed: {argv!r}: {record['stderr']}")
    libraries: list[dict[str, Any]] = []
    if sys.platform.startswith("linux") and shutil.which("ldd"):
        for name, item in pair.items():
            record = run_command([str(shutil.which("ldd")), item["path"]], root / ("ldd-" + name))
            for token in record["stdout"].split():
                if token.startswith("/") and Path(token).is_file():
                    info = identity(Path(token))
                    if info not in libraries:
                        libraries.append(info)
    elif os.name == "nt":
        libraries = [identity(p) for p in sorted(ffmpeg.parent.glob("*.dll"))]
    return {
        "tools": pair,
        "observations": observations,
        "libraries": libraries,
        "provenance": "OBSERVED_INSTALLED_TOOLS; no invented pinned build receipt",
    }


def tool_score(pair: dict[str, Any]) -> int:
    inventory = pair["observations"]
    return sum(
        name in inventory["filters"]["stdout"] for name in ("hwupload", "gblur_vulkan")
    ) + sum(name in inventory["encoders"]["stdout"] for name in ("prores_ks_vulkan", "ffv1_vulkan"))


def choose_tools(
    args: argparse.Namespace, original: dict[str, Any], run: Path, media: Path, python: Path
) -> tuple[Any, Any, Any]:
    first = original["first_path_tools"]
    installed = None
    discovery: list[dict[str, Any]] = []
    if first["ffmpeg"] and first["ffprobe"]:
        try:
            installed = inventory_pair(
                Path(first["ffmpeg"]), Path(first["ffprobe"]), run / "installed-tools"
            )
        except Exception as exc:
            discovery.append({"role": "installed baseline", "error": str(exc)})
    candidates = [installed] if installed else []
    if not args.ffmpeg and not args.prepare_ffmpeg:
        for index, item in enumerate(original["tools"]["ffmpeg"]):
            ffmpeg = Path(item["path"])
            ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if not ffprobe.is_file() or (installed and item == installed["tools"]["ffmpeg"]):
                continue
            try:
                verify(item)
                candidates.append(
                    inventory_pair(ffmpeg, ffprobe, run / f"discovered-tools-{index}")
                )
            except Exception as exc:
                discovery.append(
                    {"role": "discovered candidate", "path": str(ffmpeg), "error": str(exc)}
                )
    acquisition = None
    selected: dict[str, Any] | None
    if args.prepare_ffmpeg:
        setup = run / "tool-acquisition"
        setup.mkdir()
        request = {
            "operation": "prepare-tools",
            "media": str(run / "ffmpeg-tools"),
            "result_path": str(setup / "value.json"),
        }
        save(setup / "request.json", request)
        limits = {
            "growth_bytes": args.max_growth_gib * 1024**3,
            "reserve_bytes": args.reserve_gib * 1024**3,
            "memory_floor_bytes": 128 * 1024**2,
        }
        check_budget(run, media, limits)
        observed = run_command(
            [str(python), str(DRIVER), "--_worker", str(setup / "request.json")],
            setup / "process",
            env=child_env(),
            cwd=ROOT,
            timeout=900,
            monitor=lambda: check_budget(run, media, limits),
        )
        if observed["returncode"] != 0 or observed["error"]:
            raise ValueError(
                "pinned native Windows tool acquisition failed:\n" + observed["stderr"]
            )
        acquisition = load(setup / "value.json")["acquisition"]
        selected = inventory_pair(
            Path(acquisition["ffmpeg"]), Path(acquisition["ffprobe"]), run / "selected-tools"
        )
    elif args.ffmpeg:
        selected = inventory_pair(
            args.ffmpeg.expanduser().absolute(),
            args.ffprobe.expanduser().absolute(),
            run / "selected-tools",
        )
    else:
        selected = max(candidates, key=tool_score) if candidates else None
    save(
        run / "tool-discovery.json",
        {
            "problems": discovery,
            "acquisition": acquisition,
            "selection_basis": "advertised capabilities only; runtime probes follow",
        },
    )
    return installed, selected, acquisition


def make_smoke_audio(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(
            b"".join(
                struct.pack("<h", int(14000 * math.sin(2 * math.pi * 330 * i / 48000)))
                for i in range(4800)
            )
        )


def freeze(
    args: argparse.Namespace, run: Path, media: Path, original: dict[str, Any]
) -> dict[str, Any]:
    source = source_identity(ROOT)
    if source["git"].get("status") and not args.cpu_smoke:
        raise ValueError("clean committed source checkout required for authenticated experiments")
    if args.audio:
        audio = args.audio.expanduser().resolve(strict=True)
    else:
        audio = media / "synthetic-smoke.wav"
        make_smoke_audio(audio)
    item = identity(audio)
    if not args.cpu_smoke and (item["sha256"] != DEFAULT_SHA256 or item["bytes"] != DEFAULT_BYTES):
        raise ValueError(
            "authenticated source SHA-256/byte-size mismatch; no setup/render attempted"
        )
    if args.audio:
        outside_git([run, media], audio)
    python, environment = select_python(args.python, run)
    if (args.ffmpeg is None) != (args.ffprobe is None):
        raise ValueError("--ffmpeg and --ffprobe must be supplied together")
    installed, selected, tool_acquisition = choose_tools(args, original, run, media, python)
    if selected is None:
        raise ValueError(
            "no usable FFmpeg/ffprobe pair; native Windows may opt into --prepare-ffmpeg"
        )
    cuda_environment = None
    cuda_setup = None
    cuda_error = None
    cuda_python = (args.cuda_python or python).expanduser().absolute()
    if args.cuda:
        try:
            if args.install_cuda:
                from ewp_waveform.application.portable_experiments_setup import install_cuda

                cuda_python, cuda_setup = install_cuda(
                    python,
                    environment,
                    run,
                    media,
                    {
                        "growth_bytes": args.max_growth_gib * 1024**3,
                        "reserve_bytes": args.reserve_gib * 1024**3,
                        "memory_floor_bytes": 128 * 1024**2,
                    },
                    child_env(),
                )
            cuda_environment = probe_python(
                cuda_python,
                run / "cuda-environment",
                optional=True,
            )
        except Exception as exc:
            cuda_error = str(exc)  # Optional; CPU and Vulkan still run.
    if source_identity(ROOT) != source:
        raise ValueError("source changed during bootstrap; use a new namespace")
    template = load(ROOT / "examples/experiments/wsl-suite.json")
    config = {
        "schema_version": 1,
        "run": str(run),
        "media": str(media),
        "source": source,
        "audio": item,
        "environment": environment,
        "python": str(python),
        "original": identity(run / "original-environment.json"),
        "original_observations": identity(run / "original-observations.json"),
        "original_path": original["original_path"],
        "original_environment": original["original_environment"],
        "installed": installed,
        "selected": selected,
        "tool_acquisition": tool_acquisition,
        "smoke": args.cpu_smoke,
        "preflight_only": args.preflight_only,
        "full": args.full or args.reference_only,
        "reference_only": args.reference_only,
        "production32": not args.no_production32,
        "cuda": args.cuda,
        "cuda_environment": cuda_environment,
        "cuda_error": cuda_error,
        "cuda_python": str(cuda_python),
        "cuda_setup": cuda_setup,
        "device": args.device,
        "expected_device": args.expect_device_regex,
        "visual_overrides": template["visual_overrides"],
        "limits": {
            "growth_bytes": args.max_growth_gib * 1024**3,
            "reserve_bytes": args.reserve_gib * 1024**3,
            "memory_floor_bytes": 128 * 1024**2,
            "stage_timeout": args.timeout,
        },
        "claim": "opt-in experiments; production defaults unchanged; GUI future only",
    }
    save(run / "config.json", config)
    save(run / "config-seal.json", identity(run / "config.json"))
    return config


def verify_config(run: Path, verification: Path) -> dict[str, Any]:
    verify(load(run / "config-seal.json"))
    config = load(run / "config.json")
    if config.get("cuda_error"):
        raise ValueError("retained CUDA environment/setup failure; use a new namespace, no replay")
    if config.get("cuda_setup"):
        for key in ("requirements", "lock", "receipt", "uv"):
            verify(config["cuda_setup"][key])
    if config["run"] != str(run) or config["source"] != source_identity(ROOT):
        raise ValueError("frozen namespace/source changed; use a new namespace")
    if config["original_path"] != os.environ.get("PATH", ""):
        raise ValueError("original PATH changed; use a new namespace")
    for name, value in config["original_environment"].items():
        if os.environ.get(name) != value:
            raise ValueError(f"original environment {name} changed; use a new namespace")
    for item in (config["audio"], config["original"], config["original_observations"]):
        verify(item)
    for pair in (config["installed"], config["selected"]):
        if pair:
            for item in (*pair["tools"].values(), *pair["libraries"]):
                verify(item)
    if probe_python(Path(config["python"]), verification / "python") != config["environment"]:
        raise ValueError("selected environment changed; use a new namespace")
    if config["cuda_environment"] and (
        probe_python(Path(config["cuda_python"]), verification / "cuda", optional=True)
        != config["cuda_environment"]
    ):
        raise ValueError("optional CUDA environment changed; use a new namespace")
    return config


def invoke(
    config: dict[str, Any],
    name: str,
    request: dict[str, Any],
    *,
    optional: bool = False,
    python: str | None = None,
) -> dict[str, Any]:
    run, media = Path(config["run"]), Path(config["media"])
    root = run / "steps" / name
    root.mkdir(parents=True, exist_ok=False)
    request = {
        "original_path": config["original_path"],
        "audio": config["audio"]["path"],
        "device": config["device"],
        "expected_device": config["expected_device"],
        "visual_overrides": config["visual_overrides"],
        "media": str(media / name),
        "evidence": str(root),
        "result_path": str(root / "value.json"),
        **request,
    }
    save(root / "request.json", request)
    append_event(
        run, {"name": name, "event": "STARTED", "request": identity(root / "request.json")}
    )
    try:
        observed = run_command(
            [python or config["python"], str(DRIVER), "--_worker", str(root / "request.json")],
            root / "process",
            cwd=ROOT,
            env=child_env(),
            timeout=config["limits"]["stage_timeout"],
            monitor=lambda: check_budget(run, media, config["limits"]),
        )
        value: dict[str, Any] = (
            load(root / "value.json")
            if (root / "value.json").is_file()
            else {"status": "FAILED", "error": "worker exited without result"}
        )
        good = (
            not value.get("attempt_failures")
            and observed["returncode"] == 0
            and not observed["error"]
            and value.get("status") in ("SUCCEEDED", "SKIPPED", "NOT_SUPPORTED", "NOT_APPLICABLE")
        )
        if not good:
            value = {
                **value,
                "status": "FAILED",
                "process_error": observed["error"],
                "stderr_excerpt": observed["stderr"],
                "argv": observed["argv"],
            }
        value["optional"] = optional
        value["command"] = observed
        value["cold_process_wall_seconds"] = observed["wall_seconds"]
        stage_media = Path(request["media"])
        command_logs = [root / "commands.jsonl"]
        if stage_media.exists():
            command_logs.extend(stage_media.rglob("commands.jsonl"))
        commands = list(value.get("commands", []))
        for command_log in command_logs:
            if command_log.is_file():
                commands.extend(json.loads(line) for line in command_log.read_text().splitlines())
        value["commands"] = list({json.dumps(c, sort_keys=True): c for c in commands}.values())
        diagnostics = list(root.glob("*.stderr"))
        if stage_media.exists():
            diagnostics.extend(stage_media.rglob("*.stderr"))
        from ewp_waveform.application.portable_experiments_process import tail_text

        value["diagnostic_excerpts"] = {str(path): tail_text(path, 4000) for path in diagnostics}
        # Freeze every textual diagnostic, result, and actual media output on terminal.
        artifacts = [identity(p) for p in sorted(root.rglob("*")) if p.is_file()]
        artifacts.extend(value.get("artifacts", []))
        stage_media = Path(request["media"])
        if stage_media.exists():
            artifacts.extend(identity(p) for p in sorted(stage_media.rglob("*")) if p.is_file())
        artifacts = list({item["path"]: item for item in artifacts}.values())
        append_event(
            run,
            {
                "name": name,
                "event": "SUCCEEDED" if good else "FAILED",
                "value": value,
                "artifacts": artifacts,
            },
        )
        if not observed["shutdown_verified"]:
            raise RuntimeError("process-tree ownership shutdown UNVERIFIED; no further dispatch")
        if not good and not optional:
            raise RuntimeError(
                f"required {name} failed: {value.get('error')}; {observed['stderr']}"
            )
        return value
    except (KeyboardInterrupt, SystemExit):
        # STARTED remains uncertain, intentionally fencing resume after interruption.
        raise


def skip(config: dict[str, Any], name: str, reason: str) -> dict[str, Any]:
    root = Path(config["run"]) / "steps" / name
    root.mkdir(parents=True, exist_ok=False)
    save(root / "request.json", {"reason": reason})
    append_event(
        Path(config["run"]),
        {"name": name, "event": "STARTED", "request": identity(root / "request.json")},
    )
    value = {
        "status": "SKIPPED",
        "actual_action": "NOT_RUN",
        "reason": reason,
        "render_fps": None,
        "wall_seconds": None,
        "throughput_fresh": False,
    }
    save(root / "value.json", value)
    append_event(
        Path(config["run"]),
        {
            "name": name,
            "event": "SKIPPED",
            "value": value,
            "artifacts": [identity(root / "value.json")],
        },
    )
    return value


def backend_passed(results: dict[str, Any], name: str) -> bool:
    value = results.get("backends", {})
    # Contract: per-backend independent statuses; never one global GPU pass/fail.
    item = value.get(name, {}) if isinstance(value, dict) else {}
    same_build = value.get("same_build_control", {}).get("status", "PASS")
    return same_build == "PASS" and item.get("status") in ("SUCCEEDED", "SUPPORTED", "PASS")


def execute(config: dict[str, Any], done: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results = dict(done)
    selected = config["selected"]["tools"]
    tools = {name: item["path"] for name, item in selected.items()}

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if name not in results:
            results[name] = invoke(config, name, {**tools, **request}, **kwargs)
        return results[name]

    def skipped(name: str, reason: str) -> None:
        if name not in results:
            results[name] = skip(config, name, reason)

    plan = step("audio-plan", {"operation": "audio-plan", "smoke": config["smoke"]})
    workloads = plan["workloads"]
    qualification: dict[str, Any] = {}
    if not config["smoke"]:
        qualification = step("backend-qualification", {"operation": "qualify"}, optional=True)
    else:
        skipped("backend-qualification", "CPU smoke only; no GPU qualification requested")
    if config["preflight_only"]:
        return results
    same_build = bool(
        config["installed"]
        and all(
            item["sha256"] == config["installed"]["tools"][name]["sha256"]
            for name, item in selected.items()
        )
    )
    for w in workloads:
        base = {"operation": "service", "workload": w}
        cpu = step(w["id"] + "-cpu-selected", base)
        if config["installed"] and not same_build:
            step(
                w["id"] + "-cpu-installed",
                {
                    **base,
                    **{name: item["path"] for name, item in config["installed"]["tools"].items()},
                },
                optional=True,
            )
        if config["smoke"] or config.get("reference_only"):
            continue
        for backend, variant in (
            ("transfer", "TRANSFER"),
            ("blur", "BLUR"),
            ("prores", "PRORES-GPU"),
        ):
            label = w["id"] + "-" + backend
            if backend_passed(qualification, backend):
                if backend == "prores":
                    matched = step(
                        w["id"] + "-prores-cpu-matched", {**base, "variant": "PRORES-MATCHED"}
                    )
                    reference = matched["output"]
                else:
                    reference = cpu["output"]
                step(label, {**base, "variant": variant, "reference": reference}, optional=True)
            else:
                skipped(
                    label,
                    f"{backend} independently not qualified; "
                    "inspect backend-qualification diagnostics",
                )
        ffv1_cpu = step(
            w["id"] + "-ffv1-cpu",
            {"operation": "codec", "workload": w, "reference": cpu["output"], "gpu": False},
            optional=True,
        )
        if backend_passed(qualification, "ffv1") and ffv1_cpu["status"] == "SUCCEEDED":
            step(
                w["id"] + "-ffv1-gpu",
                {"operation": "codec", "workload": w, "reference": cpu["output"], "gpu": True},
                optional=True,
            )
        else:
            skipped(w["id"] + "-ffv1-gpu", "FFV1 independently not qualified or CPU oracle failed")
        # Independent branch: no Vulkan success is required to try explicit CUDA.
        if config["cuda"] and config["cuda_environment"]:
            numpy_control = step(
                w["id"] + "-cuda-numpy",
                {
                    "operation": "cuda",
                    "backend": "numpy",
                    "workload": w,
                    "reference": cpu["output"],
                },
                optional=True,
                python=config["cuda_python"],
            )
            reference = (
                numpy_control.get("output") if numpy_control["status"] == "SUCCEEDED" else None
            )
            for suffix, backend in (
                ("-cuda-torch-cpu", "torch-cpu"),
                ("-cuda-transfer", "transfer-cuda"),
                ("-cuda", "cuda"),
            ):
                step(
                    w["id"] + suffix,
                    {
                        "operation": "cuda",
                        "backend": backend,
                        "workload": w,
                        "reference": reference,
                    },
                    optional=True,
                    python=config["cuda_python"],
                )
        else:
            skipped(
                w["id"] + "-cuda",
                config["cuda_error"] or "CUDA opt-in not requested; Torch not installed",
            )
    # Production pool check is explicit in the worker and retained, never replaced
    # by short serial renders or a synthetic subprocess benchmark.
    if config["production32"] and not config["smoke"]:
        step(
            "production32",
            {
                "operation": "service",
                "workload": {
                    "id": "production32",
                    "kind": "production32",
                    "start": 25.0,
                    "duration": 32.0,
                    "frames": 1920,
                },
            },
        )
    if config["full"]:
        # Full is always stock CPU; optional failed GPU candidates are not promoted.
        full_tools = config.get("installed") if config.get("reference_only") else config["selected"]
        if not full_tools:
            skipped("full", "installed CPU reference tool pair unavailable")
        else:
            step(
                "full",
                {
                    "operation": "service",
                    **{name: item["path"] for name, item in full_tools["tools"].items()},
                    "workload": {
                        "id": "full",
                        "kind": "full",
                        "start": None,
                        "duration": None,
                        "frames": 23741,
                    },
                },
            )
    return results


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio", type=Path)
    p.add_argument(
        "--output-root", type=Path, default=Path.home() / ".local/state/ewp-portable-experiments"
    )
    p.add_argument("--media-root", "--media-parent", dest="media_parent", type=Path)
    p.add_argument(
        "--resume", type=Path, help="read/continue only an unchanged successful frozen run"
    )
    p.add_argument("--python", type=Path, help="existing locked Python 3.12; never modified")
    p.add_argument("--ffmpeg", type=Path)
    p.add_argument("--ffprobe", type=Path)
    p.add_argument(
        "--prepare-ffmpeg",
        action="store_true",
        help="permit isolated pinned native Windows FFmpeg acquisition",
    )
    p.add_argument(
        "--preflight-only",
        action="store_true",
        help="inventory/audio/backend probes; no waveform render",
    )
    p.add_argument(
        "--cpu-smoke",
        action="store_true",
        help="six real production frames; synthetic source if omitted",
    )
    p.add_argument(
        "--reference-only",
        action="store_true",
        help="explicit installed CPU full reference after shorts",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="explicit stock full render AFTER successful short screen",
    )
    p.add_argument(
        "--no-production32",
        action="store_true",
        help="omit stock 32s pool2 route; shorts are not pool proof",
    )
    p.add_argument(
        "--cuda",
        action="store_true",
        help="explicit optional Torch worker; no automatic installation",
    )
    p.add_argument(
        "--install-cuda",
        action="store_true",
        help="with --cuda, permit private hash-locked Torch 2.9.1/cu128 download",
    )
    p.add_argument(
        "--cuda-python", type=Path, help="existing isolated Python 3.12 + pinned Torch environment"
    )
    p.add_argument("--device", default="RTX 3090")
    p.add_argument("--expect-device-regex", default=r"RTX\s*3090")
    p.add_argument(
        "--timeout", type=float, default=900.0, help="per-worker seconds; includes descendants"
    )
    p.add_argument("--max-growth-gib", type=float, default=8.0)
    p.add_argument("--reserve-gib", type=float, default=2.0)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--_environment" in argv:
        print(json.dumps(environment_details(ROOT, optional="--_optional" in argv)))
        return 0
    if argv[:1] == ["--_worker"]:
        request = load(Path(argv[1]))
        try:
            from ewp_waveform.application.portable_experiments_worker import dispatch

            value = dispatch(request)
        except Exception as exc:
            traceback.print_exc()
            save(
                Path(request["result_path"]),
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
            )
            return 1
        save(Path(request["result_path"]), value)
        return 0
    p = parser()
    args = p.parse_args(argv)
    if not args.resume and not args.audio and not args.cpu_smoke:
        p.error("--audio PATH required except with --cpu-smoke or --resume")
    if args.cpu_smoke and (args.full or args.reference_only):
        p.error("--cpu-smoke cannot authorize a full render")
    if (args.cuda_python or args.install_cuda) and not args.cuda:
        p.error("--cuda-python/--install-cuda require explicit --cuda")
    if args.ffmpeg and args.prepare_ffmpeg:
        p.error("--prepare-ffmpeg cannot be combined with explicit --ffmpeg/--ffprobe")
    if args.cuda_python and args.install_cuda:
        p.error("--install-cuda creates its own environment; do not combine with --cuda-python")
    for name in ("timeout", "max_growth_gib", "reserve_gib"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            p.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.resume and any(
        option in {token.split("=", 1)[0] for token in argv}
        for option in (
            "--audio",
            "--python",
            "--ffmpeg",
            "--ffprobe",
            "--prepare-ffmpeg",
            "--cpu-smoke",
            "--preflight-only",
            "--cuda",
            "--cuda-python",
            "--install-cuda",
            "--full",
            "--reference-only",
            "--no-production32",
            "--timeout",
            "--max-growth-gib",
            "--reserve-gib",
            "--device",
            "--expect-device-regex",
            "--media-parent",
            "--media-root",
        )
    ):
        p.error("--resume has no setup/execution overrides; use a new namespace")
    token = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]  # noqa: UP017
    run = (
        args.resume.expanduser().resolve()
        if args.resume
        else args.output_root.expanduser().resolve() / ("run-" + token)
    )
    config = None
    results: dict[str, Any] = {}
    status, error, code = "FAILED", None, 1
    fresh_names: set[str] | None = None
    report_root = run
    namespace_admitted = False
    try:
        outside_git([run])
        namespace_admitted = True
        if args.resume:
            # Refusals are reported outside the frozen run, not written into it.
            if not (run / "config-seal.json").is_file():
                raise ValueError("resume requires the exact sealed known run directory")
            report_root = run.parent / ("resume-verification-" + token)
            report_root.mkdir()
            with lock(run):
                config = verify_config(run, report_root)
                results = completed_steps(run)
                existing = set(results)
                # Check the retained graph BEFORE running any unattempted actions.
                results = execute(config, results)
            fresh_names = set(results) - existing
            status, code = "RESUMED_WITH_NEW_WORK" if fresh_names else "VERIFIED_REUSED", 0
        else:
            run.mkdir(mode=0o700, parents=True, exist_ok=False)
            media_parent = (args.media_parent or run.parent).expanduser().resolve()
            media = media_parent / ("media-" + token)
            outside_git([media])
            if media.is_relative_to(run) or run.is_relative_to(media):
                raise ValueError("run metadata and media namespaces must be disjoint")
            media.mkdir(mode=0o700, parents=True, exist_ok=False)
            original = original_inventory(run, media)
            config = freeze(args, run, media, original)
            with lock(run):
                check_budget(run, media, config["limits"])
                results = execute(config, {})
            optional_failures = bool(config.get("cuda_error")) or any(
                v.get("status") == "FAILED" for v in results.values()
            )
            status, code = (
                (
                    "COMPLETE_WITH_OPTIONAL_FAILURES"
                    if optional_failures
                    else "PREFLIGHT_COMPLETE"
                    if config["preflight_only"]
                    else "COMPLETE"
                ),
                0,
            )
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, KeyboardInterrupt):
            status, code = "INTERRUPTED_NO_REPLAY", 130
        # Keep all already completed optional records visible even on required failure.
        if (run / "events.jsonl").is_file():
            for line in (run / "events.jsonl").read_text().splitlines():
                try:
                    row = json.loads(line)
                    if "value" in row:
                        results[row["name"]] = {
                            **row["value"],
                            "evidence_status": "SALVAGED_UNVERIFIED",
                        }
                except (ValueError, TypeError, KeyError):
                    continue
            fresh_names = set()
        if (
            not namespace_admitted
            or not report_root.exists()
            or (args.resume and report_root == run)
        ):
            parent = args.output_root.expanduser().resolve()
            try:
                outside_git([parent])
            except ValueError:
                parent = Path.home() / ".local/state/ewp-portable-experiments"
                outside_git([parent])
            report_root = parent / ("refused-" + token)
            report_root.mkdir(parents=True, exist_ok=False)
    try:
        path = report(
            report_root,
            status,
            error,
            config,
            results,
            reused=bool(args.resume),
            fresh_names=fresh_names,
        )
    except Exception as report_error:
        path = report_root / ("emergency-report-" + uuid.uuid4().hex + ".md")
        path.write_text(
            f"# Portable experiments: {status}\n\nOriginal error: {error}\n\n"
            f"Detailed report unavailable: {type(report_error).__name__}: {report_error}\n"
            "Visual / NLE PENDING; promotion NOT_APPROVED.\n",
            encoding="utf-8",
        )
        code = 1
    print(f"Run: {run}\nStatus: {status}\nMain report: {path}")
    return code
