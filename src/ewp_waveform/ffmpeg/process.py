"""Subprocess helpers. Never uses shell=True."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ToolNotFoundError(RuntimeError):
    pass


def require_tool(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        msg = f"Required tool not on PATH: {name}"
        raise ToolNotFoundError(msg)
    return Path(found)


def run_argv(argv: list[str]) -> subprocess.CompletedProcess[str]:
    if not argv:
        msg = "empty argv"
        raise ValueError(msg)
    return subprocess.run(argv, check=False, capture_output=True, text=True)
