"""Maintained single-command experiment application for Linux/WSL and Windows.

Only this module's stdlib bootstrap runs in the invoking interpreter. Every
production/backend action is a separately supervised Python 3.12 worker. Optional
backend failures are retained independently and never prevent CPU/CUDA dispatch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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

from ewp_waveform.application.portable_experiments_process import (
    ProcessOwnershipError,
    ResourceAdmissionError,
    run_command,
)
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
    tree_bytes,
    verify,
)

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "scripts/run_experiments.py"
DEFAULT_SHA256 = "e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b"
DEFAULT_BYTES = 37985180


def child_env() -> dict[str, str]:
    # Shell bookkeeping is deliberately not forwarded. All remaining inherited
    # values are authenticated as one digest, never serialized as credentials.
    env = {key: value for key, value in os.environ.items() if key not in {"_", "SHLVL"}}
    return {**env, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}


def effective_environment() -> dict[str, Any]:
    """Credential-safe identity of the entire effective inherited child mapping."""
    env = child_env()
    return {
        "sha256": hashlib.sha256(
            json.dumps(env, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "variable_names": sorted(env),
        "scope": (
            "all effective inherited values; no values retained; "
            "before fixed per-step PATH/cache staging"
        ),
        "dropped_shell_bookkeeping": ["_", "SHLVL"],
        "fixed_overrides": {"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
    }


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


TIMING_ENV_PREFIXES = (
    "OMP_",
    "OPENBLAS_",
    "MKL_",
    "NUMEXPR_",
    "BLIS_",
    "VECLIB_",
    "CUDA_",
    "CUBLAS_",
    "CUDNN_",
    "PYTORCH_",
    "TORCH_",
    "TORCHINDUCTOR_",
    "VK_",
    "MESA_",
    "NVIDIA_",
    "KMP_",
    "GOMP_",
    "MALLOC_",
)


def original_inventory(run: Path, media: Path) -> dict[str, Any]:
    """Persist original environment BEFORE any interpreter/PATH or uv selection."""
    original_path = os.environ.get("PATH", "")
    value: dict[str, Any] = {
        "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),  # noqa: UP017
        "original_path": original_path,
        "effective_child_environment": effective_environment(),
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
                "EWP_ANALYSIS_CACHE",
                "VIRTUAL_ENV",
                "CONDA_PREFIX",
                "LD_LIBRARY_PATH",
                "LD_PRELOAD",
                "DYLD_LIBRARY_PATH",
                "DYLD_INSERT_LIBRARIES",
                "PYTHONHOME",
                "PYTHONUSERBASE",
                "PYTHONNOUSERSITE",
                "GLIBC_TUNABLES",
                "GALLIUM_DRIVER",
                "LP_NUM_THREADS",
                "CUDA_VISIBLE_DEVICES",
                "VK_ICD_FILENAMES",
                "VK_DRIVER_FILES",
                "OMP_NUM_THREADS",
                "OMP_DYNAMIC",
                "OMP_PROC_BIND",
                "OMP_PLACES",
                "OMP_SCHEDULE",
                "OMP_WAIT_POLICY",
                "KMP_AFFINITY",
                "KMP_BLOCKTIME",
                "GOMP_CPU_AFFINITY",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "MKL_DYNAMIC",
                "MKL_CBWR",
                "NUMEXPR_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "BLIS_NUM_THREADS",
                "CUDA_DEVICE_ORDER",
                "CUDA_LAUNCH_BLOCKING",
                "CUDA_MODULE_LOADING",
                "CUDA_CACHE_DISABLE",
                "CUDA_CACHE_MAXSIZE",
                "CUBLAS_WORKSPACE_CONFIG",
                "NVIDIA_TF32_OVERRIDE",
                "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE",
                "PYTORCH_CUDA_ALLOC_CONF",
                "PYTORCH_ALLOC_CONF",
                "PYTORCH_NO_CUDA_MEMORY_CACHING",
                "TORCH_CUDNN_V8_API_LRU_CACHE_LIMIT",
                "TORCH_CUDNN_V8_API_DISABLED",
                "CUDNN_CONV_WSCAP_DBG",
                "NUMBER_OF_PROCESSORS",
                "WSL_DISTRO_NAME",
            )
        },
    }
    value["original_environment"].update(
        {key: val for key, val in os.environ.items() if key.startswith(TIMING_ENV_PREFIXES)}
    )
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
                **bootstrap_command(
                    [executable, *arguments], run / ("original-" + name), timeout=20
                ),
            }
            if executable
            else {"status": "NOT_FOUND"}
        )
    save(run / "original-observations.json", observations)
    return value


def bootstrap_command(argv: list[str], root: Path, **kwargs: Any) -> dict[str, Any]:
    from ewp_waveform.application.portable_experiments_dependencies import require_process_safe

    observed = run_command(argv, root, **kwargs)
    require_process_safe(observed)
    return observed


def python_candidates() -> list[Path]:
    return [ROOT / ".venv/Scripts/python.exe", ROOT / ".venv/bin/python"]


def probe_python(python: Path, folder: Path, *, optional: bool = False) -> dict[str, Any]:
    observed = bootstrap_command(
        [str(python), str(DRIVER), "--_environment", *(["--_optional"] if optional else [])],
        folder,
        env=child_env(),
        cwd=ROOT,
        timeout=300 if optional else 60,
    )
    if observed["returncode"] != 0 or observed["error"]:
        raise ValueError(
            f"Python environment unavailable: {observed['error']}\n{observed['stderr']}"
        )
    # Full environment provenance may exceed the bounded stdout excerpt.
    return json.loads((folder / "stdout.txt").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def select_python(
    explicit: Path | None,
    run: Path,
    *,
    media: Path | None = None,
    limits: dict[str, Any] | None = None,
    managed_root: Path | None = None,
    rerun: list[str] | None = None,
    uv_path: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    candidates = [explicit.expanduser().absolute()] if explicit else python_candidates()
    for index, candidate in enumerate(candidates):
        if candidate.is_file():
            try:
                return candidate, probe_python(candidate, run / f"python-candidate-{index}")
            except (ResourceAdmissionError, ProcessOwnershipError):
                raise
            except ValueError:
                if explicit:
                    raise
    if explicit:
        raise ValueError(f"explicit --python does not exist; no install attempted: {explicit}")
    from ewp_waveform.application.portable_experiments_dependencies import (
        SETUP_ESTIMATES,
        admit_setup,
        discover_environment,
        missing_uv,
        new_attempt,
        register_environment,
        reuse_environment,
        setup_environment,
    )

    store = managed_root or run / "managed-dependencies"
    reused = reuse_environment(store, ROOT, "runtime", run, probe_python) or discover_environment(
        store, ROOT, "runtime", run, probe_python
    )
    if reused:
        selected, environment, receipt = reused
        save(run / "runtime-reuse.json", receipt)
        return selected, environment
    uv = uv_path or shutil.which("uv")
    if not uv:
        raise ValueError(missing_uv(rerun or [str(DRIVER), *sys.argv[1:]]))
    if media is None or limits is None:
        raise ValueError("automatic Python setup requires explicit run+media admission limits")
    admit_setup(run, media, limits, SETUP_ESTIMATES["runtime"])
    attempt = new_attempt(store, ROOT, "runtime")
    target = attempt / "env"
    observed = bootstrap_command(
        [uv, "sync", "--frozen", "--no-dev", "--python", "3.12", "--project", str(ROOT)],
        run / "uv-sync",
        timeout=900,
        monitor=lambda: check_budget(run, media, limits),
        env={
            **setup_environment(store, child_env()),
            "UV_PROJECT_ENVIRONMENT": str(target),
        },
        cwd=ROOT,
    )
    if observed["returncode"] != 0 or observed["error"]:
        raise ValueError(
            "uv sync --frozen failed; no dependency versions changed\n" + observed["stderr"]
        )
    selected = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    environment = probe_python(selected, run / "selected-python")
    receipt = register_environment(store, ROOT, "runtime", selected, environment)
    save(run / "runtime-setup.json", receipt)
    check_budget(run, media, limits)
    return selected, environment


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
        record = bootstrap_command(argv, root / label)
        record["stdout_file"] = identity(root / label / "stdout.txt")
        observations[label] = record
        if record["returncode"] != 0 or record["error"]:
            raise ValueError(f"tool inventory failed: {argv!r}: {record['stderr']}")
    libraries: list[dict[str, Any]] = []
    if sys.platform.startswith("linux") and shutil.which("ldd"):
        for name, item in pair.items():
            record = bootstrap_command(
                [str(shutil.which("ldd")), item["path"]], root / ("ldd-" + name)
            )
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

    def complete(label: str) -> str:
        record = inventory[label]
        if record.get("stdout_file"):
            verify(record["stdout_file"])
            return Path(record["stdout_file"]["path"]).read_text(encoding="utf-8", errors="replace")
        if record.get("logs"):
            return (Path(record["logs"]) / "stdout.txt").read_text(
                encoding="utf-8", errors="replace"
            )
        return str(record.get("stdout", ""))  # Legacy/synthetic records without capture paths.

    filters, encoders = complete("filters"), complete("encoders")
    return sum(name in filters for name in ("hwupload", "gblur_vulkan")) + sum(
        name in encoders for name in ("prores_ks_vulkan", "ffv1_vulkan")
    )


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
        except (ResourceAdmissionError, ProcessOwnershipError):
            raise
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
            except (ResourceAdmissionError, ProcessOwnershipError):
                raise
            except Exception as exc:
                discovery.append(
                    {"role": "discovered candidate", "path": str(ffmpeg), "error": str(exc)}
                )
    acquisition = None
    selected: dict[str, Any] | None
    if args.prepare_ffmpeg:
        setup = run / "tool-acquisition"
        setup.mkdir()
        from ewp_waveform.application.portable_experiments_dependencies import prepared_ffmpeg_root

        tool_root = prepared_ffmpeg_root(
            args.output_root.expanduser().resolve(),
            args._managed_root
            / "ffmpeg"
            / identity(ROOT / "src/ewp_waveform/ffmpeg/portable_ffmpeg_lock.json")["sha256"],
            discovery,
        )
        request: dict[str, Any] = {
            "operation": "prepare-tools",
            "media": str(tool_root),
            "allow_download": tool_root.is_relative_to(args._managed_root),
            "result_path": str(setup / "value.json"),
        }
        save(setup / "request.json", request)
        from ewp_waveform.application.portable_experiments_dependencies import admit_setup
        from ewp_waveform.ffmpeg.portable_tools import read_lock

        limits = args._setup_limits
        tool_lock = read_lock()
        destination = Path(request["media"]) / tool_lock["archive_root"]
        if not destination.exists():
            admit_setup(
                run, media, limits, tool_lock["max_archive_bytes"] + tool_lock["max_expanded_bytes"]
            )
        check_budget(run, media, limits)
        observed = bootstrap_command(
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


def prerequisite_admission(args: argparse.Namespace) -> None:
    """Cheap required-tool discovery before inventory or dependency acquisition."""
    from ewp_waveform.application.portable_experiments_dependencies import (
        missing_git,
        tool_advice,
    )

    rerun = getattr(args, "_rerun", [str(DRIVER), *sys.argv[1:]])
    if not shutil.which("git") and (ROOT / ".git").exists():
        raise ValueError(missing_git(rerun))
    if args.prepare_ffmpeg and os.name != "nt":
        raise ValueError(
            "--prepare-ffmpeg installs native Windows executables, not Linux/WSL tools. "
            "Remove --prepare-ffmpeg on this platform.\n"
            + tool_advice([token for token in rerun if token != "--prepare-ffmpeg"])
        )
    if not args.prepare_ffmpeg and not args.setup_only:
        ffmpeg = str(args.ffmpeg) if args.ffmpeg else shutil.which("ffmpeg")
        ffprobe = str(args.ffprobe) if args.ffprobe else shutil.which("ffprobe")
        if not ffmpeg or not ffprobe or not all(Path(p).is_file() for p in (ffmpeg, ffprobe)):
            raise ValueError(tool_advice(rerun))


def campaign_limits(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "growth_bytes": args.max_growth_gib * 1024**3,
        "reserve_bytes": args.reserve_gib * 1024**3,
        "memory_floor_bytes": 128 * 1024**2,
        "budget_scope": "campaign run+media retained allocation; excludes managed preparation",
    }


def dependency_policy(args: argparse.Namespace, run: Path, media: Path) -> dict[str, Any]:
    """Print/persist explicit independent setup and render policy before downloads."""
    from ewp_waveform.application.portable_experiments_dependencies import (
        SETUP_ESTIMATES,
        setup_limits,
    )

    store = (args.managed_root or args.output_root / "managed-dependencies").expanduser().resolve()
    outside_git([store])
    if any(store.is_relative_to(p) or p.is_relative_to(store) for p in (run, media)):
        raise ValueError("managed dependency store must be disjoint from run/media namespaces")
    args._managed_root = store
    check_budget(run, media, campaign_limits(args))
    args._setup_limits = {
        **setup_limits(store, args.setup_max_growth_gib, args.reserve_gib),
        "reserve_roots": list(map(str, (store, run, media))),
        "campaign_limits": campaign_limits(args),
    }
    policy = {
        "managed_root": str(store),
        "setup_new_allocation_bytes": args._setup_limits["growth_bytes"],
        "setup_baseline_bytes": args._setup_limits["baseline_bytes"],
        "render_retained_allocation_bytes": args.max_growth_gib * 1024**3,
        "free_reserve_bytes": args.reserve_gib * 1024**3,
        "setup_accounting_roots": args._setup_limits["accounting_roots"],
        "reserve_roots": args._setup_limits["reserve_roots"],
        "campaign_limits": campaign_limits(args),
        "planning_estimates_bytes": SETUP_ESTIMATES,
        "defaults_reason": (
            "24GiB setup allows CUDA wheels+unpack+copy fallback; admission estimates "
            "2GiB runtime, 16GiB Linux/10GiB Windows CUDA. 8GiB render is a short-screen "
            "retention policy, not full-render sizing; 10GiB disk reserve is an operator "
            "safety margin. These are configurable policies, not VM/host capacity claims."
        ),
        "accounting": (
            "global inode dedup; allocated blocks where available; logical fallback labelled"
        ),
        "limits": "sampled admission/monitoring, not kernel quotas; temporary peaks may be missed",
    }
    print(
        "Dependency/render resource policy (before acquisition):\n" + json.dumps(policy, indent=2),
        flush=True,
    )
    save(run / "preparation-policy.json", policy)
    from ewp_waveform.application.portable_experiments_dependencies import existing_uv

    args._uv_path = existing_uv(store)
    if args.setup_uv:
        from ewp_waveform.application.portable_experiments_dependencies import bootstrap_uv

        args._uv_path = bootstrap_uv(store, run, media, args._setup_limits, child_env())
    return policy


def dependency_action(args: argparse.Namespace) -> int:
    """Independent readback/preparation; never continue or rewrite an old campaign."""
    from ewp_waveform.application.portable_experiments_dependencies import register_environment
    from ewp_waveform.application.portable_experiments_state import tree_usage

    if args.inspect_storage is not None:
        roots = [
            p.expanduser().resolve(strict=True)
            for p in (args.inspect_storage or [args.output_root])
        ]
        print(
            json.dumps(
                {
                    "roots": list(map(str, roots)),
                    **tree_usage(roots, max_entries=1_000_000, timeout_seconds=args.timeout),
                },
                indent=2,
            )
        )
        return 0
    token = uuid.uuid4().hex
    run = args.output_root.expanduser().resolve() / ("dependency-check-" + token)
    outside_git([run])
    run.mkdir(parents=True, exist_ok=False)
    try:
        if not args.verify_environment:
            prerequisite_admission(args)
        if args.verify_environment:
            python = args.verify_environment.expanduser().absolute()
            environment = probe_python(python, run / "environment", optional=args.cuda)
            receipt = None
            if args.register_environment:
                store = (
                    (args.managed_root or args.output_root / "managed-dependencies")
                    .expanduser()
                    .resolve()
                )
                receipt = register_environment(
                    store, ROOT, "cu128" if args.cuda else "runtime", python, environment
                )
            save(run / "verified.json", {"environment": environment, "registered": receipt})
            value = {"status": "VERIFIED_DEPENDENCIES_ONLY", "python": str(python)}
        else:
            media = run / "unused-media"
            media.mkdir()
            # Store and output namespace are disjoint; this directory contains no render media.
            dependency_policy(args, run, media)
            python, environment = select_python(
                args.python,
                run,
                media=media,
                limits=args._setup_limits,
                managed_root=args._managed_root,
                rerun=args._rerun,
                uv_path=args._uv_path,
            )
            if args.cuda:
                if args.install_cuda:
                    from ewp_waveform.application.portable_experiments_setup import install_cuda

                    python, _ = install_cuda(
                        python,
                        environment,
                        run,
                        media,
                        args._setup_limits,
                        child_env(),
                        managed_root=args._managed_root,
                        probe=probe_python,
                        rerun=args._rerun,
                        uv_path=args._uv_path,
                    )
                else:
                    from ewp_waveform.application.portable_experiments_dependencies import (
                        prepared_environment,
                    )

                    reused = (
                        None
                        if args.cuda_python
                        else prepared_environment(
                            args._managed_root, ROOT, "cu128", run, probe_python
                        )
                    )
                    python = args.cuda_python or (reused[0] if reused else python)
                    environment = (
                        reused[1]
                        if reused
                        else probe_python(python, run / "cuda-verification", optional=True)
                    )
                    register_environment(args._managed_root, ROOT, "cu128", python, environment)
            if args.prepare_ffmpeg:
                original = original_inventory(run, media)
                choose_tools(args, original, run, media, python)
            value = {"status": "DEPENDENCIES_READY_NO_RENDER", "python": str(python)}
        save(run / "result.json", value)
        print(json.dumps({**value, "report": str(run / "result.json")}, indent=2))
        return 0
    except Exception as exc:
        status = (
            "REFUSED_RESOURCE_LIMIT"
            if isinstance(exc, ResourceAdmissionError)
            else "UNVERIFIED_PROCESS_OWNERSHIP"
            if isinstance(exc, ProcessOwnershipError)
            else "FAILED"
        )
        save(run / "result.json", {"status": status, "error": str(exc)})
        print(f"Dependency check failed: {exc}\nReport: {run / 'result.json'}")
        return 1


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
    installed = selected = tool_acquisition = None
    if not args.prepare_ffmpeg:
        installed, selected, tool_acquisition = choose_tools(
            args, original, run, media, Path(sys.executable)
        )
        if selected is None:
            from ewp_waveform.application.portable_experiments_dependencies import tool_advice

            raise ValueError(tool_advice(getattr(args, "_rerun", [str(DRIVER), *sys.argv[1:]])))
    check_budget(run, media, campaign_limits(args))
    preparation = dependency_policy(args, run, media)
    python, environment = select_python(
        args.python,
        run,
        media=media,
        limits=args._setup_limits,
        managed_root=args._managed_root,
        rerun=getattr(args, "_rerun", None),
        uv_path=args._uv_path,
    )
    if (args.ffmpeg is None) != (args.ffprobe is None):
        raise ValueError("--ffmpeg and --ffprobe must be supplied together")
    if args.prepare_ffmpeg:
        check_budget(run, media, campaign_limits(args))
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
        check_budget(run, media, campaign_limits(args))
        try:
            if args.install_cuda:
                from ewp_waveform.application.portable_experiments_setup import install_cuda

                cuda_python, cuda_setup = install_cuda(
                    python,
                    environment,
                    run,
                    media,
                    args._setup_limits,
                    child_env(),
                    managed_root=args._managed_root,
                    probe=probe_python,
                    rerun=getattr(args, "_rerun", None),
                    uv_path=args._uv_path,
                )
            elif not args.cuda_python:
                from ewp_waveform.application.portable_experiments_dependencies import (
                    prepared_environment,
                )

                reused = prepared_environment(args._managed_root, ROOT, "cu128", run, probe_python)
                if reused:
                    cuda_python, cuda_environment, cuda_setup = reused
                    save(run / "cuda-reuse.json", cuda_setup)
            if cuda_environment is None:
                cuda_environment = probe_python(
                    cuda_python,
                    run / "cuda-environment",
                    optional=True,
                )
        except (ResourceAdmissionError, ProcessOwnershipError):
            raise
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
        "effective_child_environment": original["effective_child_environment"],
        "installed": installed,
        "selected": selected,
        "tool_acquisition": tool_acquisition,
        "smoke": args.cpu_smoke,
        "preflight_only": args.preflight_only,
        "full": args.full or args.reference_only,
        "reference_only": args.reference_only,
        "production32": not args.no_production32,
        "cuda": args.cuda,
        "repeats": args.repeats,
        "repeat_scope": "speech shortlist (or six-frame smoke); sequential AB/BA alternating",
        "cuda_environment": cuda_environment,
        "cuda_error": cuda_error,
        "cuda_python": str(cuda_python),
        "cuda_setup": cuda_setup,
        "preparation_policy": preparation,
        "device": args.device,
        "expected_device": args.expect_device_regex,
        "visual_overrides": template["visual_overrides"],
        "limits": {**campaign_limits(args), "stage_timeout": args.timeout},
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
            if key in config["cuda_setup"]:
                verify(config["cuda_setup"][key])
    if config["run"] != str(run) or config["source"] != source_identity(ROOT):
        raise ValueError("frozen namespace/source changed; use a new namespace")
    if config["original_path"] != os.environ.get("PATH", ""):
        raise ValueError("original PATH changed; use a new namespace")
    for name, value in config["original_environment"].items():
        if os.environ.get(name) != value:
            raise ValueError(f"original environment {name} changed; use a new namespace")
    added_selectors = {
        key
        for key in os.environ
        if key.startswith(TIMING_ENV_PREFIXES) and key not in config["original_environment"]
    }
    if added_selectors:
        raise ValueError(
            f"new computational environment selectors: {sorted(added_selectors)}; "
            "use a new namespace"
        )
    if config.get("effective_child_environment") != effective_environment():
        raise ValueError(
            "effective forwarded child environment changed or snapshot missing; "
            "values are not retained; use a new namespace"
        )
    for item in (config["audio"], config["original"], config["original_observations"]):
        verify(item)
    for pair in (config["installed"], config["selected"]):
        if pair:
            for item in (*pair["tools"].values(), *pair["libraries"]):
                verify(item)
            for record in pair["observations"].values():
                if record.get("stdout_file"):
                    verify(record["stdout_file"])
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
            timeout=min(config["limits"]["stage_timeout"], 120.0)
            if request["operation"] == "qualify-finish"
            else config["limits"]["stage_timeout"],
            monitor=lambda: check_budget(run, media, config["limits"]),
        )
        parse_errors: list[dict[str, str]] = []
        try:
            value: dict[str, Any] = (
                load(root / "value.json")
                if (root / "value.json").is_file()
                else {"status": "FAILED", "error": "worker exited without result"}
            )
        except (ValueError, OSError, UnicodeError) as exc:
            parse_errors.append({"path": str(root / "value.json"), "error": str(exc)})
            value = {"status": "FAILED", "error": "invalid worker result; raw bytes retained"}
        good = (
            not value.get("attempt_failures")
            and observed["returncode"] == 0
            and not observed["error"]
            and observed["shutdown_verified"]
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
        if request.get("pair"):
            value["pair"] = request["pair"]
        value["execution_settings"] = {
            key: request.get(key) for key in ("ffmpeg", "ffprobe", "visual_overrides", "workload")
        }
        value["execution_settings"]["python"] = python or config["python"]
        value["command"] = observed
        value["cold_process_wall_seconds"] = observed["wall_seconds"]
        stage_media = Path(request["media"])
        command_logs = [root / "commands.jsonl"]
        if stage_media.exists():
            command_logs.extend(stage_media.rglob("commands.jsonl"))
        command_value = value.get("commands", [])
        commands: list[dict[str, Any]] = []
        if not isinstance(command_value, list):
            parse_errors.append(
                {"path": str(root / "value.json"), "error": "commands must be a list of objects"}
            )
        else:
            for index, record in enumerate(command_value):
                if isinstance(record, dict):
                    commands.append(record)
                else:
                    parse_errors.append(
                        {
                            "path": str(root / "value.json"),
                            "error": f"commands[{index}] must be an object",
                        }
                    )
        for command_log in command_logs:
            if not command_log.is_file():
                continue
            try:
                with command_log.open(encoding="utf-8") as stream:
                    for number, line in enumerate(stream, 1):
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict):
                                raise ValueError("command record must be an object")
                            commands.append(record)
                        except ValueError as exc:
                            parse_errors.append(
                                {"path": str(command_log), "line": str(number), "error": str(exc)}
                            )
            except (OSError, UnicodeError) as exc:
                parse_errors.append({"path": str(command_log), "error": str(exc)})
        value["commands"] = list({json.dumps(c, sort_keys=True): c for c in commands}.values())
        if parse_errors:
            good = False
            value.update(
                status="FAILED",
                diagnostic_parse_errors=parse_errors,
                error=value.get("error") or "invalid diagnostic record; raw evidence retained",
            )
        if not good:
            value["failure_scope"] = (
                "GLOBAL_PROCESS_OWNERSHIP"
                if not observed["shutdown_verified"]
                else "GLOBAL_RESOURCE_ADMISSION"
                if observed.get("resource_refused")
                else "OPTIONAL_SCENARIO"
                if optional
                else "REQUIRED_SCENARIO"
            )
            value["independent_dispatch_allowed"] = bool(
                optional and observed["shutdown_verified"] and not observed.get("resource_refused")
            )
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
            raise ProcessOwnershipError(
                "process-tree ownership shutdown UNVERIFIED; no further dispatch"
            )
        if observed.get("resource_refused"):
            raise ResourceAdmissionError(
                "global resource admission refused; no implicit recovery or further dispatch: "
                + "; ".join(observed.get("resource_errors", []))
            )
        # Evidence/event serialization can itself cross the retained-growth cap.
        try:
            check_budget(run, media, config["limits"])
        except ValueError as exc:
            append_event(
                run,
                {
                    "name": name,
                    "event": "DISPATCH_REFUSED",
                    "value": {
                        "status": "FAILED",
                        "worker_status": value["status"],
                        "failure_scope": "GLOBAL_RESOURCE_ADMISSION",
                        "independent_dispatch_allowed": False,
                        "error": str(exc),
                        "scope_supersedes": "prior terminal before post-evidence admission",
                    },
                },
            )
            raise ResourceAdmissionError(
                "post-evidence global resource refusal; no further dispatch: " + str(exc)
            ) from exc
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


def backend_failure_reason(results: dict[str, Any], name: str) -> str:
    """Explain only the actual failed gate; sibling failures are not prerequisites."""
    backends = results.get("backends", {})
    item = backends.get(name, {}) if isinstance(backends, dict) else {}
    control = backends.get("same_build_control", {}) if isinstance(backends, dict) else {}
    if control and control.get("status") != "PASS":
        return f"same_build_control {control.get('status', 'NOT_RUN')}: " + str(
            control.get("explanation") or "selected FFmpeg/ffprobe identity not qualified"
        )
    details = [f"{name} independently {item.get('status', 'NOT_RUN')}"]
    if item.get("explanation"):
        details.append(str(item["explanation"]))
    for key, case in item.get("cases", {}).items():
        if isinstance(case, dict) and case.get("status") != "PASS":
            details.append(
                f"{key}: {case.get('status', 'NOT_RUN')}: "
                + str(case.get("explanation") or case.get("error") or "qualification gate failed")
            )
    return "; ".join(details)


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
    # Always admit the independent CPU oracle in the selected interpreter. Torch
    # qualification is opt-in and each backend is an isolated bounded subprocess.
    finishing = {
        "numpy": step(
            "finish-qualify-numpy",
            {"operation": "qualify-finish", "backend": "numpy"},
            optional=True,
        )
    }
    if config.get("cuda") and config.get("cuda_environment"):
        finishing["optional-numpy"] = step(
            "finish-qualify-optional-numpy",
            {"operation": "qualify-finish", "backend": "numpy"},
            optional=True,
            python=config["cuda_python"],
        )
        for backend in ("torch-cpu", "transfer-cuda", "cuda"):
            finishing[backend] = step(
                "finish-qualify-" + backend,
                {"operation": "qualify-finish", "backend": backend},
                optional=True,
                python=config["cuda_python"],
            )

    def finish_passed(name: str) -> bool:
        gate = finishing.get(name, {})
        return gate.get("status") == "SUCCEEDED" and gate.get("passed") is True

    def finish_reason(name: str) -> str:
        gate = finishing.get(name, {})
        return (
            f"{name} qualification {gate.get('status', 'NOT_RUN')}; passed={gate.get('passed')}: "
            + str(
                config.get("cuda_error")
                if name not in finishing and config.get("cuda_error")
                else gate.get("error") or gate.get("reason") or "numerical prerequisite not met"
            )
        )

    if config["preflight_only"]:
        return results
    same_build = bool(
        config["installed"]
        and all(
            item["sha256"] == config["installed"]["tools"][name]["sha256"]
            for name, item in selected.items()
        )
    )

    def pair(
        label: str,
        a: dict[str, Any],
        b: dict[str, Any],
        *,
        comparison: str,
        python: str | None = None,
        repetitions: int | None = None,
    ) -> None:
        # New namespace for every observation. Never share a baseline between
        # pairs or report a reused output as an independently repeated sample.
        count = config.get("repeats", 2) if repetitions is None else repetitions
        for ordinal in range(1, count + 1):
            order = "AB" if ordinal % 2 else "BA"
            for side in order:
                request = a if side == "A" else b
                if side == "B" and request.get("operation") == "service":
                    # Compare against a matched control, outside the timer. BA
                    # repeats use the already validated first-pass A master.
                    control = results.get(f"{label}-r{ordinal:02d}-A") or results.get(
                        f"{label}-r01-A", {}
                    )
                    if control.get("status") == "SUCCEEDED" and control.get("output"):
                        request = {**request, "reference": control["output"]}
                    else:
                        skipped(
                            f"{label}-r{ordinal:02d}-{side}",
                            "matched service CPU control unavailable; no candidate render",
                        )
                        continue
                step(
                    f"{label}-r{ordinal:02d}-{side}",
                    {
                        **request,
                        "pair": {
                            "id": label,
                            "repeat": ordinal,
                            "order": order,
                            "side": side,
                            "comparison": comparison,
                        },
                    },
                    optional=True,
                    python=python,
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
        if config.get("reference_only"):
            continue
        # Counterbalance the speech shortlist; also screen each remaining real
        # onset/quiet/tail workload once so appearance/edge cases are not inferred
        # from stock-CPU controls alone. Single observations are labelled n=1.
        if w["id"] != "speech" and not config["smoke"]:
            finish_request = {"operation": "cuda", "workload": w}
            if finish_passed("numpy"):
                pair(
                    w["id"] + "-fir-screen",
                    {**finish_request, "backend": "ffmpeg"},
                    {**finish_request, "backend": "numpy"},
                    comparison="n=1 edge-case algorithm screen; matched original raster",
                    repetitions=1,
                )
            else:
                skipped(w["id"] + "-fir-screen", finish_reason("numpy"))
            for backend in ("torch-cpu", "transfer-cuda", "cuda"):
                if finish_passed("optional-numpy") and finish_passed(backend):
                    pair(
                        w["id"] + "-" + backend + "-screen",
                        {**finish_request, "backend": "numpy"},
                        {**finish_request, "backend": backend},
                        comparison="n=1 edge-case FIR backend screen",
                        python=config["cuda_python"],
                        repetitions=1,
                    )
                else:
                    skipped(
                        w["id"] + "-" + backend + "-screen",
                        finish_reason("optional-numpy")
                        if not finish_passed("optional-numpy")
                        else finish_reason(backend),
                    )
            continue
        if not config["smoke"]:
            for backend, variant in (
                ("transfer", "TRANSFER"),
                ("blur", "BLUR"),
                ("prores", "PRORES-GPU"),
            ):
                label = w["id"] + "-" + backend
                if backend_passed(qualification, backend):
                    control = {
                        **base,
                        "variant": "PRORES-MATCHED" if backend == "prores" else "CPU-CONTROL",
                    }
                    pair(
                        label,
                        control,
                        {**base, "variant": variant},
                        comparison=(
                            "algorithm contrast; recursive CPU vs GPU blur"
                            if backend == "blur"
                            else "matched service backend control"
                        ),
                    )
                else:
                    skipped(
                        label,
                        backend_failure_reason(qualification, backend),
                    )
        codec = {"operation": "codec", "workload": w, "reference": cpu["output"]}
        if backend_passed(qualification, "ffv1") and not config["smoke"]:
            pair(
                w["id"] + "-ffv1",
                {**codec, "gpu": False},
                {**codec, "gpu": True},
                comparison="matched shared-master decode/conversion/FFV1 encoding",
            )
        else:
            # Retain a native lossless MKV even without a GPU encoder. It aliases
            # the existing CPU MOV for NLE comparison after exact RGBA proof.
            step(w["id"] + "-ffv1-cpu", {**codec, "gpu": False}, optional=True)
            skipped(
                w["id"] + "-ffv1-gpu",
                "CPU smoke only; GPU not requested"
                if config["smoke"]
                else backend_failure_reason(qualification, "ffv1"),
            )
        finish = {"operation": "cuda", "workload": w}
        if finish_passed("numpy"):
            pair(
                w["id"] + "-fir-algorithm",
                {**finish, "backend": "ffmpeg"},
                {**finish, "backend": "numpy"},
                comparison="algorithm contrast; matched raster, FFmpeg recursive vs NumPy FIR",
            )
        else:
            skipped(w["id"] + "-fir-algorithm", finish_reason("numpy"))
        for backend in ("torch-cpu", "transfer-cuda", "cuda"):
            if finish_passed("optional-numpy") and finish_passed(backend):
                # Both sides run under the SAME optional interpreter and use the
                # same algorithm, original raster, timer and encoding wrapper.
                pair(
                    w["id"] + "-" + backend,
                    {**finish, "backend": "numpy"},
                    {**finish, "backend": backend},
                    comparison="matched FIR finishing backend control",
                    python=config["cuda_python"],
                )
            else:
                skipped(
                    w["id"] + "-" + backend,
                    finish_reason("optional-numpy")
                    if not finish_passed("optional-numpy")
                    else finish_reason(backend),
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
    # View generation is separate from every timed render. Identical decoded
    # RGBA streams share one useful set even across MOV/MKV container variants.
    views: dict[tuple[Any, ...], dict[str, Any]] = {}
    for name, result in list(results.items()):
        valid = result.get("validation", {})
        if (
            result.get("status") != "SUCCEEDED"
            or not result.get("output")
            or not valid.get("passed")
        ):
            continue
        digest = valid.get("decoded_rgba_sha256")
        key = (
            digest,
            valid.get("frames"),
            json.dumps(valid.get("stream", {}).get("width")),
            json.dumps(valid.get("stream", {}).get("height")),
        )
        view = step(
            name + "-views",
            {
                "operation": "views",
                "source": result["output"],
                "workload": result["workload"],
                "reuse_views": views.get(key) if digest else None,
                "comparison_mov": result.get("comparison_mov"),
            },
            optional=True,
        )
        if digest and view.get("status") == "SUCCEEDED":
            views.setdefault(key, view)
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
    p.add_argument(
        "--repeats",
        type=int,
        default=2,
        help="even pair repetitions (2..10), sequential AB/BA; other baselines run once",
    )
    p.add_argument(
        "--setup-uv",
        action="store_true",
        help="explicit private uv 0.12.6 install using bootstrap venv; "
        "never alters PATH/global Python",
    )
    p.add_argument(
        "--managed-root",
        type=Path,
        help="persistent verified dependency/tool store (default output-root/managed-dependencies)",
    )
    p.add_argument(
        "--setup-only",
        action="store_true",
        help="explicit isolated dependency preparation; no audio or renders",
    )
    p.add_argument(
        "--verify-environment",
        type=Path,
        help="read-only verify an existing interpreter, independently of any failed run",
    )
    p.add_argument(
        "--register-environment",
        action="store_true",
        help="register --verify-environment for future verified reuse",
    )
    p.add_argument(
        "--inspect-storage",
        type=Path,
        nargs="*",
        help="read-only global allocated/logical accounting; no paths means output-root",
    )
    p.add_argument(
        "--setup-max-growth-gib",
        type=float,
        default=24.0,
        help="separate new installation/cache/temp allowance; "
        "conservative CUDA copy/unpack headroom",
    )
    p.add_argument(
        "--max-growth-gib",
        type=float,
        default=8.0,
        help="campaign render/media/evidence allowance, excludes managed preparation",
    )
    p.add_argument("--reserve-gib", type=float, default=10.0)
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
    if not (
        args.resume
        or args.audio
        or args.cpu_smoke
        or args.setup_only
        or args.verify_environment
        or args.inspect_storage is not None
    ):
        p.error("--audio PATH required except with --cpu-smoke or --resume")
    if args.cpu_smoke and (args.full or args.reference_only):
        p.error("--cpu-smoke cannot authorize a full render")
    if (args.cuda_python or args.install_cuda) and not args.cuda:
        p.error("--cuda-python/--install-cuda require explicit --cuda")
    if (args.ffmpeg is None) != (args.ffprobe is None):
        p.error("--ffmpeg and --ffprobe must be supplied together before setup")
    if args.ffmpeg and args.prepare_ffmpeg:
        p.error("--prepare-ffmpeg cannot be combined with explicit --ffmpeg/--ffprobe")
    if args.cuda_python and args.install_cuda:
        p.error("--install-cuda creates its own environment; do not combine with --cuda-python")
    if args.repeats not in range(2, 11, 2):
        p.error("--repeats must be even, between 2 and 10, for balanced AB/BA orders")
    for name in ("timeout", "max_growth_gib", "setup_max_growth_gib", "reserve_gib"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            p.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.resume and any(
        option in {token.split("=", 1)[0] for token in argv}
        for option in (
            "--audio",
            "--managed-root",
            "--setup-uv",
            "--setup-only",
            "--verify-environment",
            "--register-environment",
            "--inspect-storage",
            "--setup-max-growth-gib",
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
            "--repeats",
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
    args._rerun = [str(DRIVER), *argv]
    if (args.verify_environment or args.inspect_storage is not None) and (
        args.setup_uv or args.install_cuda or args.prepare_ffmpeg
    ):
        p.error("verification/storage inspection cannot authorize installation")
    if args.register_environment and not args.verify_environment:
        p.error("--register-environment requires --verify-environment PATH")
    if sum((args.setup_only, bool(args.verify_environment), args.inspect_storage is not None)) > 1:
        p.error("--setup-only, --verify-environment and --inspect-storage are independent actions")
    if args.setup_only or args.verify_environment or args.inspect_storage is not None:
        return dependency_action(args)
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
    existing: set[str] | None = None  # None means dispatch was never admitted.
    report_root = run
    namespace_admitted = False
    try:
        if not args.resume:
            prerequisite_admission(args)
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
                existing = set()
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
        elif isinstance(exc, ProcessOwnershipError):
            status = "REFUSED_PROCESS_OWNERSHIP"
        elif isinstance(exc, ResourceAdmissionError):
            status = "REFUSED_RESOURCE_LIMIT"
        # Keep all already completed optional records visible even on required failure.
        if (run / "events.jsonl").is_file():
            for line in (run / "events.jsonl").read_text().splitlines():
                try:
                    row = json.loads(line)
                    if "value" in row:
                        results[row["name"]] = {
                            **(
                                results.get(row["name"], {})
                                if row["event"] == "DISPATCH_REFUSED"
                                else {}
                            ),
                            **row["value"],
                            "evidence_status": "SALVAGED_UNVERIFIED",
                        }
                except (ValueError, TypeError, KeyError):
                    continue
            fresh_names = set(results) - existing if existing is not None else set()
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
        if config is not None and code == 0:
            try:
                # Resume diagnostics live outside the frozen run. Include their
                # newly retained bytes without writing into that original run.
                budget_run, budget_media = Path(config["run"]), Path(config["media"])
                limits = dict(config["limits"])
                if not report_root.is_relative_to(budget_run) and not report_root.is_relative_to(
                    budget_media
                ):
                    limits["growth_bytes"] -= tree_bytes(report_root)
                check_budget(budget_run, budget_media, limits)
            except ValueError as budget_error:
                preliminary = path
                status, code = "REFUSED_RESOURCE_LIMIT", 1
                error = str(budget_error)
                path = report(
                    report_root,
                    status,
                    error,
                    config,
                    results,
                    reused=bool(args.resume),
                    fresh_names=fresh_names,
                )
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        f"\nSupersedes preliminary pre-budget report: `{preliminary}`. "
                        "All outputs retained; no completion claim.\n"
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
    if error:
        print(f"Startup/execution stopped: {error}", flush=True)
    print(f"Run: {run}\nStatus: {status}\nMain report: {path}")
    return code
