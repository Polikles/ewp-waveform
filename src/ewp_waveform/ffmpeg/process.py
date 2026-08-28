"""Subprocess helpers. Never uses shell=True."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
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


def run_argv_stdin(argv: list[str], chunks: Iterable[bytes]) -> subprocess.CompletedProcess[bytes]:
    """Feed binary chunks to stdin."""
    if not argv:
        msg = "empty argv"
        raise ValueError(msg)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.stdin is None:
        msg = "failed to open ffmpeg stdin"
        raise RuntimeError(msg)
    try:
        for chunk in chunks:
            proc.stdin.write(chunk)
    except BrokenPipeError:
        pass
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
