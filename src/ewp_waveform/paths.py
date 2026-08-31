"""Resolve repository / install data directories and operator paths."""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def project_root() -> Path:
    """Return the repo root in a src/ checkout (`…/ewp-waveform`)."""
    return Path(__file__).resolve().parents[2]


def builtin_presets_dir() -> Path:
    return project_root() / "presets"


def builtin_performance_dir() -> Path:
    return project_root() / "performance"


def normalize_user_path(value: str | Path) -> Path:
    """Accept POSIX or Windows paths. On Linux, ``D:\\foo`` becomes ``/mnt/d/foo``."""
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return Path(text)
    match = _WINDOWS_DRIVE.match(text)
    if match is not None:
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(text.replace("\\", "/"))
