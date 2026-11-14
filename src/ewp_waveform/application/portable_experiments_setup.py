"""Explicit isolated CUDA setup from committed platform/hash-locked closures.

PyTorch2.9.1/cu128 is the selected compatibility control, not floating latest.
Verified environments are shared across campaigns; attempts remain append-only.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_dependencies import (
    SETUP_ESTIMATES,
    Probe,
    admit_setup,
    discover_environment,
    installation_monitors,
    missing_uv,
    new_attempt,
    register_environment,
    require_process_safe,
    reuse_environment,
    setup_environment,
)
from ewp_waveform.application.portable_experiments_process import run_command
from ewp_waveform.application.portable_experiments_state import check_budget, identity, save

TORCH_REQUIREMENT = "torch==2.9.1"
TORCH_BACKEND = "cu128"
TORCH_RECIPE = "https://pytorch.org/get-started/previous-versions/"


def cuda_lock(root: Path) -> Path:
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise ValueError("pinned CUDA environment supports Linux/Windows x86-64 only")
    if os.name == "nt":
        name = "windows"
    elif sys.platform.startswith("linux"):
        name = "linux"
    else:
        raise ValueError("pinned CUDA environment supports Linux/WSL and native Windows only")
    return root / "requirements" / f"torch-cu128-{name}-x64-py312.txt"


def install_cuda(
    python: Path,
    environment: dict[str, Any],
    run: Path,
    media: Path,
    limits: dict[str, Any],
    child_environment: dict[str, str],
    *,
    managed_root: Path | None = None,
    probe: Probe | None = None,
    rerun: list[str] | None = None,
    uv_path: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Reuse verified bytes before any installer; never repair an old attempt."""
    if probe is None:
        from ewp_waveform.application.portable_experiments import probe_python

        probe = probe_python
    source_root = Path(__file__).resolve().parents[3]
    store = managed_root or run / "managed-dependencies"
    reused = reuse_environment(
        store, source_root, TORCH_BACKEND, run, probe
    ) or discover_environment(store, source_root, TORCH_BACKEND, run, probe)
    if reused:
        selected, _, receipt = reused
        save(run / "cuda-reuse.json", receipt)
        return selected, receipt
    uv = uv_path or shutil.which("uv")
    if not uv:
        raise ValueError(missing_uv(rerun or ["scripts/run_experiments.py", *sys.argv[1:]]))
    committed_lock = cuda_lock(source_root)
    if not committed_lock.is_file():
        raise ValueError("committed CUDA platform lock missing; no runtime re-resolution")
    admission = admit_setup(run, media, limits, SETUP_ESTIMATES[TORCH_BACKEND])
    attempt = new_attempt(store, source_root, TORCH_BACKEND)
    setup, target = run / "cuda-setup", attempt / "env"
    setup.mkdir()
    save(setup / "admission.json", admission)
    requirements = source_root / "requirements-torch-experiment.txt"
    frozen = setup / "requirements-locked.txt"
    frozen.write_bytes(committed_lock.read_bytes())
    selected = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {**setup_environment(store, child_environment), "UV_PYTHON_DOWNLOADS": "never"}
    commands = [
        [uv, "venv", "--python", str(python), str(target)],
        [
            uv,
            "pip",
            "sync",
            str(frozen),
            "--python",
            str(selected),
            "--torch-backend",
            TORCH_BACKEND,
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--strict",
        ],
    ]
    observations = []
    monitor, final_monitor = installation_monitors(run, media, limits, setup)
    for number, argv in enumerate(commands):
        result = run_command(
            argv,
            setup / f"command-{number}",
            timeout=1800,
            env=env,
            monitor=monitor,
            final_monitor=final_monitor,
        )
        observations.append(result)
        require_process_safe(result)
        if result["returncode"] != 0 or result["error"]:
            raise ValueError(
                "isolated CUDA setup failed; attempt retained, no replay/shared install:\n"
                + str(result["error"])
                + "\n"
                + result["stderr"]
            )
    # A successful installer exit is not verification. Register only after the
    # worker authenticates the Python/runtime/Torch versions and RECORD payloads.
    verified = probe(selected, run / "cuda-installed-verification", optional=True)
    final_monitor()
    registered = register_environment(store, source_root, TORCH_BACKEND, selected, verified)
    receipt = {
        "status": "SUCCEEDED",
        "uv": identity(Path(uv)),
        "torch_requirement": TORCH_REQUIREMENT,
        "torch_backend": TORCH_BACKEND,
        "upstream_recipe": TORCH_RECIPE,
        "requirements": identity(requirements),
        "committed_lock": identity(committed_lock),
        "lock": identity(frozen),
        "application_runtime_expected": environment["locked_runtime"],
        "python": str(selected),
        "commands": observations,
        "registered": registered,
        "scope": "private managed worker; no system/driver changes; no resolution",
    }
    save(setup / "receipt.json", receipt)
    check_budget(run, media, limits)
    return selected, {**receipt, "receipt": identity(setup / "receipt.json")}
