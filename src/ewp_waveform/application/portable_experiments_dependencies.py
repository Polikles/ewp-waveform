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
import uuid
from collections.abc import Callable
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
        ProcessOwnershipError,
        ResourceAdmissionError,
    )

    if not result.get("shutdown_verified", False):
        raise ProcessOwnershipError(
            "bootstrap process-tree shutdown UNVERIFIED; no further dispatch"
        )
    if result.get("resource_refused"):
        raise ResourceAdmissionError(
            "bootstrap global resource refusal: "
            + str(result.get("resource_errors", result.get("error")))
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
    for index, path in enumerate(sorted(registry.glob("*.json"))):
        receipt = load(path)
        if receipt["key"]["request"] != request or digest(receipt["key"]) != receipt["key_sha256"]:
            raise ValueError(f"managed dependency receipt changed: {path}")
        python = Path(receipt["python"])
        environment = probe(
            python, evidence / f"reuse-{backend}-{index}", optional=backend == "cu128"
        )
        if environment != receipt["environment"]:
            raise ValueError(f"managed environment changed; no repair/reinstall: {python}")
        return python, environment, {**receipt, "receipt": identity(path), "reused": True}
    return None


def discover_environment(
    store: Path, root: Path, backend: str, evidence: Path, probe: Probe
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """Recover prepared bytes from failed legacy runs, without replaying a run.

    Search the eight newest legacy candidates; each probe is separately bounded.
    An explicitly selected interpreter remains available for other placements.
    """
    name = "cuda-env" if backend == "cu128" else "python-env"
    relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    candidates = sorted(evidence.parent.glob(f"run-*/{name}/{relative}"), reverse=True)[:8]
    for index, python in enumerate(candidates):
        if not python.is_file():
            continue
        try:
            environment = probe(
                python, evidence / f"discovered-{backend}-{index}", optional=backend == "cu128"
            )
        except ValueError as exc:
            from ewp_waveform.application.portable_experiments_process import ResourceAdmissionError

            if isinstance(exc, ResourceAdmissionError):
                raise
            continue  # Failed probe logs are retained; never sync/repair this env.
        receipt = register_environment(store, root, backend, python, environment)
        return python, environment, {**receipt, "discovered": True, "reused": True}
    return None


def prepared_environment(
    store: Path, root: Path, backend: str, evidence: Path, probe: Probe
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    return reuse_environment(store, root, backend, evidence, probe) or discover_environment(
        store, root, backend, evidence, probe
    )


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
    if remaining < estimate or before["free_bytes"] < estimate + limits["reserve_bytes"]:
        raise ResourceLimitError(
            "dependency capacity admission refused BEFORE download: "
            f"planning_bytes={estimate}, setup_remaining_bytes={remaining}, "
            f"free_bytes={before['free_bytes']}, reserve_bytes={limits['reserve_bytes']}. "
            "Use verified --python/--cuda-python, or explicitly increase --setup-max-growth-gib "
            "after checking the target filesystem. Render --max-growth-gib is separate."
        )
    return {
        **before,
        "planning_bytes": estimate,
        "planning_scope": "conservative estimate, not quota",
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
    for index, argv in enumerate(commands):
        result = run_command(
            argv,
            run / "uv-bootstrap" / f"command-{index}",
            timeout=300,
            env=setup_environment(store, inherited),
            monitor=lambda: check_budget(run, media, limits),
        )
        require_process_safe(result)
        if result["returncode"] != 0 or result["error"]:
            raise ValueError(
                f"isolated uv bootstrap failed; attempt retained: {result['error']}\n"
                + result["stderr"]
            )
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
