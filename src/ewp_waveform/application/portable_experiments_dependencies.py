"""Stdlib-only dependency admission and append-only verified environment registry.

Registry entries are pointers, not copies. A fresh payload probe is required for
all reuse. Failed setup directories and old campaigns are never repaired/deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from itertools import islice
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_state import (
    ResourceLimitError,
    check_budget,
    identity,
    load,
    outside_git,
    save,
    sha,
    tree_usage,
    verify,
)

GIB = 1024**3
# Conservative planning headroom, not measured target requirements or quotas.
# CUDA includes wheel download, extracted cache, environment (copy fallback),
# temporary unpacking and interpreter. Platform closures have different sizes.
SETUP_ESTIMATES = {"runtime": 2 * GIB, "cu128": (10 if os.name == "nt" else 16) * GIB}
Probe = Callable[..., dict[str, Any]]


def require_process_safe(result: dict[str, Any]) -> None:
    from ewp_waveform.application.portable_experiments_process import (
        MonitorFailureError,
        ProcessOwnershipError,
        ResourceAdmissionError,
        StorageObservationError,
    )

    if not result.get("shutdown_verified", False):
        raise ProcessOwnershipError(
            "bootstrap process-tree shutdown UNVERIFIED; no further dispatch"
        )
    if result.get("resource_refused"):
        raise ResourceAdmissionError(
            "bootstrap global resource refusal: "
            + str(result.get("resource_errors", result.get("error")))
            + "; storage reconciliation: "
            + str(result.get("storage_observation_errors", []))
        )
    if result.get("storage_observation_failed"):
        raise StorageObservationError(
            "bootstrap global storage observation failed: "
            + str(result.get("storage_observation_errors", result.get("error")))
        )
    if result.get("monitor_failed"):
        raise MonitorFailureError(
            "bootstrap global monitor failed: "
            + str(result.get("monitor_errors", result.get("error")))
        )


def command_text(argv: list[str], *, windows: bool) -> str:
    if windows:
        return " ".join("'" + token.replace("'", "''") + "'" for token in argv)
    return shlex.join(argv)


def missing_uv(rerun: list[str], *, windows: bool | None = None) -> str:
    windows = os.name == "nt" if windows is None else windows
    install = (
        "winget install --id astral-sh.uv --exact"
        if windows
        else "curl -LsSf https://astral.sh/uv/install.sh | sh"
    )
    invocation = (["py", "-3"] if windows else [sys.executable]) + rerun
    return (
        "uv was not found on the original PATH. The bootstrap Python "
        f"{platform.python_version()} only runs this stdlib driver; workers require the "
        "frozen Python 3.12 runtime. uv acquires that interpreter and installs locked "
        "dependencies in isolated managed storage, never into global Python/STT.\n"
        f"Install uv explicitly ({'PowerShell' if windows else 'Linux/WSL shell'}):\n"
        f"{install}\n"
        "Close and open a NEW terminal so its PATH includes uv; return to this checkout.\n"
        "Verify: uv --version\nExact rerun (new campaign; preserve the failed attempt):\n"
        + ("& " if windows else "")
        + command_text(invocation, windows=windows)
        + "\nAlternatively use --python PATH to an existing locked Python 3.12 environment. "
        "--setup-only explicitly prepares isolated dependencies without audio or renders. "
        "To install uv privately without changing PATH/global Python, add --setup-uv "
        "to that setup command (pinned uv 0.12.6 in a new bootstrap venv)."
    )


def linux_package_command(package: str) -> str:
    """Choose the package manager from the observed release, not a guessed WSL version."""
    release = Path("/etc/os-release")
    fields = (
        dict(
            line.split("=", 1)
            for line in release.read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )
        if release.is_file()
        else {}
    )
    family = (fields.get("ID", "") + " " + fields.get("ID_LIKE", "")).replace('"', "").split()
    if any(name in family for name in ("debian", "ubuntu")):
        return f"sudo apt-get update && sudo apt-get install -y {package}"
    if any(name in family for name in ("fedora", "rhel", "centos")):
        return "sudo dnf install -y " + ("ffmpeg-free" if package == "ffmpeg" else package)
    if "arch" in family:
        return f"sudo pacman -S --needed {package}"
    raise ValueError(
        "unsupported Linux package-manager platform; detected os-release "
        + str(fields.get("ID", "unavailable"))
        + "; use --prepare-ffmpeg on native Windows, or supply existing --ffmpeg/--ffprobe paths"
    )


def rerun_text(rerun: list[str], *, windows: bool) -> str:
    invocation = (["py", "-3"] if windows else [sys.executable]) + rerun
    return ("& " if windows else "") + command_text(invocation, windows=windows)


def tool_advice(rerun: list[str], *, windows: bool | None = None) -> str:
    windows = os.name == "nt" if windows is None else windows
    if windows:
        command = rerun if "--prepare-ffmpeg" in rerun else [*rerun, "--prepare-ffmpeg"]
        return (
            "FFmpeg/ffprobe are missing or incompatible; both are required for audio probing, "
            "CPU controls and output validation. Explicitly prepare the pinned isolated "
            "Windows pair using the same runner (no system tool replacement).\n"
            "No new terminal is needed. Exact installation and continuation command:\n"
            + rerun_text(command, windows=True)
        )
    return (
        "FFmpeg/ffprobe are missing or incompatible; both are required for audio probing, "
        "CPU controls and output validation. Install the distro package:\n"
        + linux_package_command("ffmpeg")
        + "\nNo new terminal is needed. Exact command afterward:\n"
        + rerun_text(rerun, windows=False)
    )


def missing_git(rerun: list[str], *, windows: bool | None = None) -> str:
    windows = os.name == "nt" if windows is None else windows
    command = "winget install --id Git.Git -e" if windows else linux_package_command("git")
    return (
        "Git is missing or incompatible; it is required to authenticate the checkout "
        "revision and detect uncommitted source before expensive preparation.\n"
        + command
        + (
            "\nOpen a new terminal and return to the checkout."
            if windows
            else "\nNo new terminal is needed."
        )
        + "\nExact command afterward:\n"
        + rerun_text(rerun, windows=windows)
    )


def request_key(root: Path, backend: str) -> dict[str, Any]:
    locks = {"uv.lock": sha(root / "uv.lock"), "pyproject.toml": sha(root / "pyproject.toml")}
    if backend == "cu128":
        from ewp_waveform.application.portable_experiments_setup import cuda_lock

        selected = cuda_lock(root)
        locks[selected.name] = sha(selected)
    return {
        "schema_version": 1,
        "locks": locks,
        "python_requirement": "3.12",
        "implementation": "cpython",
        "platform": sys.platform,
        "machine": platform.machine().lower(),
        "backend": backend,
    }


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def register_environment(
    store: Path, root: Path, backend: str, python: Path, environment: dict[str, Any]
) -> dict[str, Any]:
    outside_git([store])
    request = request_key(root, backend)
    key = {
        "request": request,
        "interpreter": environment["binary"],
        "version": environment["version"],
    }
    registry = store / "verified" / digest(request)
    registry.mkdir(parents=True, exist_ok=True)
    receipt = {
        "key": key,
        "key_sha256": digest(key),
        "python": str(python.absolute()),
        "environment": environment,
        "scope": "verified dependency bytes only; no CUDA/device or rendering qualification",
    }
    path = registry / (digest(key) + "-" + uuid.uuid4().hex + ".json")
    save(path, receipt)
    return {**receipt, "receipt": identity(path)}


def reuse_environment(
    store: Path, root: Path, backend: str, evidence: Path, probe: Probe
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    request = request_key(root, backend)
    registry = store / "verified" / digest(request)
    paths = bounded_paths(registry.glob("*.json"))
    if not paths:
        reuse_diagnostic(
            evidence,
            backend,
            status="EXACT_KEY_MISS",
            request=request,
            registry=str(registry),
            reason="no receipt under current recipe/lock/platform/backend key",
        )
    for index, path in enumerate(sorted(paths)):
        receipt = load(path)
        if receipt["key"]["request"] != request or digest(receipt["key"]) != receipt["key_sha256"]:
            reuse_diagnostic(
                evidence,
                backend,
                status="REFUSED",
                receipt=str(path),
                reason="current-key receipt changed",
            )
            raise ValueError(f"managed dependency receipt changed: {path}")
        python = Path(receipt["python"])
        try:
            environment = probe(
                python, evidence / f"reuse-{backend}-{index}", optional=backend == "cu128"
            )
        except ValueError as exc:
            reuse_diagnostic(
                evidence,
                backend,
                status="CURRENT_KEY_PROBE_REFUSED",
                python=str(python),
                error=str(exc),
                error_type=type(exc).__name__,
                action="retained unchanged; no repair/reinstall",
            )
            raise
        if environment != receipt["environment"]:
            reuse_diagnostic(
                evidence,
                backend,
                status="REFUSED",
                python=str(python),
                reason="current-key environment changed; no repair/reinstall",
            )
            raise ValueError(f"managed environment changed; no repair/reinstall: {python}")
        reuse_diagnostic(
            evidence, backend, status="SELECTED_EXACT_KEY", python=str(python), receipt=str(path)
        )
        return python, environment, {**receipt, "receipt": identity(path), "reused": True}
    return None


def reuse_diagnostic(evidence: Path, backend: str, **event: Any) -> None:
    """Append reasons and probe locations; never modify an old run or receipt."""
    evidence.mkdir(parents=True, exist_ok=True)
    with (evidence / f"{backend}-reuse-selection.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def bounded_paths(paths: Iterable[Path], *, bound: int = 4096) -> list[Path]:
    found = list(islice(paths, bound + 1))
    if len(found) > bound:
        raise ValueError(
            "retained dependency search bound exceeded; select explicit --python/--cuda-python"
        )
    return found


def interpreter_probe(python: Path, evidence: Path) -> dict[str, Any]:
    """Native, isolated stdlib identity, before trusting cross-recipe packages."""
    from ewp_waveform.application.portable_experiments_process import run_command

    code = (
        "import json,platform,struct,sys; "
        "print(json.dumps(dict(implementation=sys.implementation.name, "
        "version=list(sys.version_info[:2]), platform=sys.platform, "
        "machine=platform.machine().lower(), bits=struct.calcsize('P')*8)))"
    )
    result = run_command([str(python), "-I", "-B", "-c", code], evidence, timeout=20)
    require_process_safe(result)
    if result["returncode"] != 0 or result["error"]:
        raise ValueError(f"retained interpreter unavailable: {result['error']}\n{result['stderr']}")
    value = json.loads((evidence / "stdout.txt").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("retained interpreter identity unavailable: expected object")
    aliases = {"amd64": "x86_64", "arm64": "aarch64"}
    expected = {
        "implementation": "cpython",
        "version": [3, 12],
        "platform": sys.platform,
        "machine": aliases.get(platform.machine().lower(), platform.machine().lower()),
        "bits": 64,
    }
    observed = {**value, "machine": aliases.get(value.get("machine", ""), value.get("machine", ""))}
    if observed != expected:
        raise ValueError(f"retained interpreter identity mismatch: {observed}; required {expected}")
    return value


def discover_environment(
    store: Path, root: Path, backend: str, evidence: Path, probe: Probe
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """Freshly verify at most eight retained candidates, including other recipes.

    Old keys/receipts only locate candidates and explain key differences. They
    never authenticate compatibility or authorize mutation of retained bytes.
    Enumeration also has a hard bound; truncation never silently triggers install.
    """
    from ewp_waveform.application.portable_experiments_process import (
        ResourceAdmissionError,
        StorageObservationError,
    )

    request = request_key(root, backend)
    current = digest(request)
    name = "cuda-env" if backend == "cu128" else "python-env"
    relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    candidates: dict[str, dict[str, Any]] = {}

    def add(python: Path, origin: str, *, cross_recipe: bool, **details: Any) -> None:
        if python.is_file():
            token = str(python.absolute())  # Do not resolve venv symlinks to base Python.
            item = {"python": python, "origin": origin, "cross_recipe": cross_recipe, **details}
            if token not in candidates or cross_recipe:
                candidates[token] = item

    try:
        for python in bounded_paths(evidence.parent.glob(f"run-*/{name}/{relative}")):
            add(python, "legacy run environment", cross_recipe=False)
        for python in bounded_paths((store / "attempts").glob(f"*/*/env/{relative}")):
            old_key = python.parents[3].name
            add(python, "managed attempt", cross_recipe=old_key != current, old_request_key=old_key)
        for path in bounded_paths((store / "verified").glob("*/*.json")):
            if path.parent.name == current:
                continue  # Exact-key mutation checks belong to reuse_environment.
            try:
                old = load(path)
                python = Path(old["python"])
                if not python.is_absolute():
                    raise ValueError("old registry pointer is not absolute")
                registry_key = old.get("key")
                old_request = registry_key.get("request") if isinstance(registry_key, dict) else {}
                if not isinstance(old_request, dict):
                    old_request = {}
                differences = {
                    key: {"old": old_request.get(key), "current": value}
                    for key, value in request.items()
                    if old_request.get(key) != value
                }
                add(
                    python,
                    "prior registry pointer (untrusted)",
                    cross_recipe=True,
                    old_receipt=str(path),
                    request_differences=differences,
                )
            except (ValueError, KeyError, TypeError) as exc:
                reuse_diagnostic(
                    evidence, backend, status="INVALID_POINTER", path=str(path), error=str(exc)
                )
    except (ValueError, OSError) as exc:
        reuse_diagnostic(evidence, backend, status="SEARCH_REFUSED", error=str(exc))
        raise
    ordered = sorted(
        candidates.values(),
        key=lambda item: item["python"].parents[1].stat().st_mtime_ns,
        reverse=True,
    )
    reuse_diagnostic(
        evidence,
        backend,
        status="SEARCH",
        request=request,
        request_key=current,
        candidates=len(ordered),
        probe_bound=8,
    )
    for index, item in enumerate(ordered[:8]):
        python = item["python"]
        details = {**item, "python": str(python)}
        folder = evidence / f"discovered-{backend}-{index}"
        try:
            if item["cross_recipe"]:
                interpreter_probe(python, folder.with_name(folder.name + "-interpreter"))
            environment = probe(python, folder, optional=backend == "cu128")
        except (ResourceAdmissionError, StorageObservationError):
            raise  # Global failure is never optional or a candidate miss.
        except ValueError as exc:
            reuse_diagnostic(
                evidence,
                backend,
                status="INVALIDATED",
                **details,
                error=str(exc),
                probe_evidence=str(folder),
                action="retained unchanged; no repair",
            )
            continue
        receipt = register_environment(store, root, backend, python, environment)
        reuse_diagnostic(
            evidence,
            backend,
            status="SELECTED",
            **details,
            probe_evidence=str(folder),
            new_receipt=receipt["receipt"],
        )
        return (
            python,
            environment,
            {**receipt, "discovered": True, "reused": True, "selection": details},
        )
    reuse_diagnostic(
        evidence,
        backend,
        status="NO_VALID_ENVIRONMENT",
        probed=min(8, len(ordered)),
        unprobed=max(0, len(ordered) - 8),
        action="fresh isolated install required if authorized",
    )
    return None


def prepared_environment(
    store: Path, root: Path, backend: str, evidence: Path, probe: Probe
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    return reuse_environment(store, root, backend, evidence, probe) or discover_environment(
        store, root, backend, evidence, probe
    )


def prepared_ffmpeg_root(
    output_root: Path, managed_root: Path, problems: list[dict[str, Any]]
) -> Path:
    """Reverify legacy run-local tools in place; no copies or old receipt edits."""
    from ewp_waveform.ffmpeg.portable_tools import read_lock, verify_install

    lock = read_lock()
    if (managed_root / lock["archive_root"]).exists():
        return managed_root  # Worker rechecks it; never repair a changed managed payload.
    candidates = list(output_root.glob("run-*/ffmpeg-tools/" + lock["archive_root"]))
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True)[:8]
    for directory in candidates:
        try:
            verify_install(directory, lock)
        except (ValueError, OSError) as exc:
            problems.append(
                {"role": "retained pinned FFmpeg", "path": str(directory), "error": str(exc)}
            )
            continue
        return directory.parent
    return managed_root


def setup_limits(store: Path, max_gib: float, reserve_gib: float) -> dict[str, Any]:
    outside_git([store])
    store.mkdir(parents=True, exist_ok=True)
    usage = tree_usage([store])
    return {
        "growth_bytes": max_gib * GIB,
        "reserve_bytes": reserve_gib * GIB,
        "memory_floor_bytes": 128 * 1024**2,
        "accounting_roots": [str(store)],
        "baseline_bytes": usage["budget_bytes"],
        "budget_scope": (
            "new managed installation/cache/temp allocation; independent of render budget"
        ),
    }


def admit_setup(run: Path, media: Path, limits: dict[str, Any], estimate: int) -> dict[str, Any]:
    before = check_budget(run, media, limits)
    remaining = limits["growth_bytes"] - before["growth_bytes"]
    payload_roots = [Path(p) for p in limits.get("accounting_roots", [run, media])]
    free_by_root = before.get("filesystem_free_bytes", {})
    payload_free = (
        min(free_by_root[str(p)] for p in payload_roots) if free_by_root else before["free_bytes"]
    )
    if remaining < estimate or payload_free < estimate + limits["reserve_bytes"]:
        raise ResourceLimitError(
            "dependency capacity admission refused BEFORE download: "
            f"planning_bytes={estimate}, setup_remaining_bytes={remaining}, "
            f"payload_free_bytes={payload_free}, reserve_bytes={limits['reserve_bytes']}. "
            "Use verified --python/--cuda-python, or explicitly increase --setup-max-growth-gib "
            "after checking the target filesystem. Render --max-growth-gib is separate."
        )
    return {
        **before,
        "planning_bytes": estimate,
        "planning_roots": list(map(str, payload_roots)),
        "planning_free_bytes": payload_free,
        "planning_scope": (
            "conservative payload-filesystem estimate, not quota; all reserves separately checked"
        ),
    }


def new_attempt(store: Path, root: Path, backend: str) -> Path:
    attempt = store / "attempts" / digest(request_key(root, backend)) / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    return attempt


def existing_uv(store: Path) -> str | None:
    for path in sorted((store / "uv-bootstrap").glob("*/receipt.json")):
        receipt = load(path)
        if receipt["version"] == "0.12.6":
            verify(receipt["binary"])
            return str(receipt["binary"]["path"])
    return None


def installation_monitors(
    run: Path, media: Path, limits: dict[str, Any], evidence: Path
) -> tuple[Callable[[], dict[str, Any]], Callable[[], dict[str, Any]]]:
    """Installation-only live tolerance; persist every sample and strict final check."""
    evidence.mkdir(parents=True, exist_ok=True)
    samples = evidence / "storage-samples.jsonl"

    def observe(*, live: bool) -> dict[str, Any]:
        policy = {**limits, "allow_transient_disappearance": live}
        event: dict[str, Any] = {
            "phase": "LIVE_INSTALL" if live else "FINAL_STRICT",
            "allow_transient_disappearance": live,
            "monotonic": time.monotonic(),
        }
        failure: Exception | None = None
        try:
            observation = check_budget(run, media, policy)
            event["observation"] = observation
        except Exception as exc:
            failure = exc
            event.update(error=str(exc), error_type=type(exc).__name__)
            incomplete = getattr(exc, "storage_observations", None)
            if incomplete:
                event["incomplete_samples"] = incomplete
            raise
        finally:
            try:
                with samples.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, sort_keys=True) + "\n")
            except OSError as retention_error:
                if failure is not None:
                    raise failure from retention_error
                raise
        return observation

    return lambda: observe(live=True), lambda: observe(live=False)


def retained_managed_python(
    uv: str, store: Path, evidence: Path, inherited: dict[str, str]
) -> Path | None:
    """Ask uv offline for an already retained managed CPython, never a new release.

    Selecting an explicit verified interpreter prevents uv's default managed-version
    preference from acquiring a newer patch when only dependency installation is needed.
    """
    from ewp_waveform.application.portable_experiments_process import run_command

    if not (store / "python").is_dir():
        reuse_diagnostic(
            evidence,
            "runtime",
            status="NO_RETAINED_INTERPRETER",
            reason="managed Python directory absent",
        )
        return None
    folder = evidence / "retained-python-find"
    result = run_command(
        [
            uv,
            "python",
            "find",
            "3.12",
            "--managed-python",
            "--no-python-downloads",
            "--offline",
            "--no-project",
            "--no-config",
        ],
        folder,
        timeout=30,
        env={**setup_environment(store, inherited), "UV_PYTHON_DOWNLOADS": "never"},
    )
    require_process_safe(result)
    if result["returncode"] != 0 or result["error"]:
        reuse_diagnostic(
            evidence,
            "runtime",
            status="NO_RETAINED_INTERPRETER",
            result=result,
            reason="offline uv search did not find a usable retained managed CPython",
        )
        return None
    selected = Path((folder / "stdout.txt").read_text(encoding="utf-8").strip())
    if not selected.is_file() or not selected.resolve().is_relative_to(
        (store / "python").resolve()
    ):
        raise ValueError(
            f"managed Python search escaped retained store; no acquisition: {selected}"
        )
    try:
        interpreter_probe(selected, evidence / "retained-python-identity")
    except ValueError as exc:
        from ewp_waveform.application.portable_experiments_process import (
            ResourceAdmissionError,
            StorageObservationError,
        )

        if isinstance(exc, (ResourceAdmissionError, StorageObservationError)):
            raise
        reuse_diagnostic(evidence, "runtime", status="RETAINED_INTERPRETER_REFUSED", error=str(exc))
        raise ValueError("retained managed interpreter invalid; no repair/reacquisition") from exc
    reuse_diagnostic(
        evidence,
        "runtime",
        status="RETAINED_INTERPRETER_SELECTED",
        python=str(selected),
        binary=identity(selected),
        action="install dependencies only; Python downloads disabled",
    )
    return selected


def bootstrap_uv(
    store: Path, run: Path, media: Path, limits: dict[str, Any], inherited: dict[str, str]
) -> str:
    """Explicit PATH-neutral uv installation; no global pip or shell installer."""
    from ewp_waveform.application.portable_experiments_process import run_command

    receipts = store / "uv-bootstrap"
    existing = existing_uv(store)
    if existing:
        return existing
    admit_setup(run, media, limits, 256 * 1024**2)
    attempt = receipts / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    env = attempt / "env"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    uv = env / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
    commands = [
        [sys.executable, "-m", "venv", str(env)],
        [
            str(python),
            "-m",
            "pip",
            "--isolated",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            "--only-binary=:all:",
            "--no-deps",
            "--no-cache-dir",
            "uv==0.12.6",
        ],
        [str(uv), "--version"],
    ]
    monitor, final_monitor = installation_monitors(run, media, limits, run / "uv-bootstrap")
    for index, argv in enumerate(commands):
        result = run_command(
            argv,
            run / "uv-bootstrap" / f"command-{index}",
            timeout=300,
            env=setup_environment(store, inherited),
            monitor=monitor,
            final_monitor=final_monitor,
        )
        require_process_safe(result)
        if result["returncode"] != 0 or result["error"]:
            raise ValueError(
                f"isolated uv bootstrap failed; attempt retained: {result['error']}\n"
                + result["stderr"]
            )
    final_monitor()
    save(attempt / "receipt.json", {"version": "0.12.6", "binary": identity(uv)})
    check_budget(run, media, limits)
    return str(uv)


def setup_environment(store: Path, inherited: dict[str, str]) -> dict[str, str]:
    temporary = store / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    return {
        **inherited,
        "UV_CACHE_DIR": str(store / "cache"),
        "UV_PYTHON_INSTALL_DIR": str(store / "python"),
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
    }
