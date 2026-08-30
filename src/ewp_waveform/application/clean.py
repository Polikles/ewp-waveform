"""Remove abandoned workdirs without touching published outputs (docs/18)."""

from __future__ import annotations

import shutil
from pathlib import Path

from ewp_waveform.application.checkpoint import default_work_root


def list_workdirs(root: Path | None = None) -> list[Path]:
    base = root if root is not None else default_work_root()
    if not base.is_dir():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir() and path.name.startswith("ewp-"))


def clean_workdirs(*, root: Path | None = None, dry_run: bool = False) -> list[Path]:
    found = list_workdirs(root)
    if not dry_run:
        for path in found:
            shutil.rmtree(path, ignore_errors=True)
    return found
