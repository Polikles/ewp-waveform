"""Explicit, isolated optional CUDA setup. Never mutates an existing environment.

The official PyTorch previous-version recipe supplies torch 2.9.1 / cu128.
Resolution emits a platform-specific hash-locked closure before installation;
subsequent resume verifies that lock and installed metadata, never re-resolves.
No driver, toolkit, system package, or shared project dependency is installed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_process import run_command
from ewp_waveform.application.portable_experiments_state import check_budget, identity, save

TORCH_REQUIREMENT = "torch==2.9.1"
TORCH_BACKEND = "cu128"
TORCH_RECIPE = "https://pytorch.org/get-started/previous-versions/"


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
    if os.name != "nt" and not __import__("sys").platform.startswith("linux"):
        raise ValueError("pinned CUDA installer supports native Windows and Linux/WSL only")
    before = check_budget(run, media, limits)
    minimum = 4 * 1024**3
    if limits["growth_bytes"] < minimum or before["free_bytes"] < minimum + limits["reserve_bytes"]:
        raise ValueError("CUDA install admission needs >=4GiB growth allowance plus disk reserve")
    setup, target = run / "cuda-setup", run / "cuda-env"
    setup.mkdir(exist_ok=False)
    requirements = setup / "requirements.in"
    requirements.write_text(
        "\n".join(
            [
                TORCH_REQUIREMENT,
                *(
                    f"{name}=={version}"
                    for name, version in sorted(environment["locked_runtime"].items())
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    frozen = setup / "requirements-locked.txt"
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
            "compile",
            str(requirements),
            "--python",
            str(python),
            "--torch-backend",
            TORCH_BACKEND,
            "--generate-hashes",
            "--emit-index-annotation",
            "--emit-index-url",
            "--only-binary",
            ":all:",
            "--output-file",
            str(frozen),
        ],
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
        "lock": identity(frozen),
        "python": str(selected),
        "commands": observations,
        "scope": "new private worker environment only; no system/driver changes",
    }
    save(setup / "receipt.json", receipt)
    return selected, {**receipt, "receipt": identity(setup / "receipt.json")}
