"""Explicit isolated CUDA setup from committed platform/hash-locked closures.

PyTorch2.9.1/cu128 is the selected shared compatibility control, not latest2.15.
No resolution occurs on startup; missing artifacts fail without floating upgrades.
No existing STT/project environment, driver, toolkit or system package is changed.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

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
) -> tuple[Path, dict[str, Any]]:
    """Download only after --cuda --install-cuda; retain every failed attempt."""
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("--install-cuda requires uv on the original PATH")
    source_root = Path(__file__).resolve().parents[3]
    committed_lock = cuda_lock(source_root)
    if not committed_lock.is_file():
        raise ValueError("committed CUDA platform lock missing; no runtime re-resolution")
    before = check_budget(run, media, limits)
    minimum = 4 * 1024**3
    if limits["growth_bytes"] < minimum or before["free_bytes"] < minimum + limits["reserve_bytes"]:
        raise ValueError("CUDA install admission needs >=4GiB growth allowance plus disk reserve")
    setup, target = run / "cuda-setup", run / "cuda-env"
    setup.mkdir(exist_ok=False)
    requirements = source_root / "requirements-torch-experiment.txt"
    frozen = setup / "requirements-locked.txt"
    frozen.write_bytes(committed_lock.read_bytes())
    selected = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {
        **child_environment,
        "UV_CACHE_DIR": str(run / "cuda-cache"),
        "UV_PYTHON_DOWNLOADS": "never",
    }
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
    for number, argv in enumerate(commands):
        result = run_command(
            argv,
            setup / f"command-{number}",
            timeout=1800,
            env=env,
            monitor=lambda: check_budget(run, media, limits),
        )
        observations.append(result)
        if result["returncode"] != 0 or result["error"]:
            raise ValueError(
                "isolated CUDA setup failed; no replay/shared install:\n"
                + str(result["error"])
                + "\n"
                + result["stderr"]
            )
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
        "scope": "new private worker environment only; no system/driver changes; no resolution",
    }
    save(setup / "receipt.json", receipt)
    return selected, {**receipt, "receipt": identity(setup / "receipt.json")}
