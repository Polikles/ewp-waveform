"""Prefix grouping (ADR-0009, FR-GROUP-*)."""

from __future__ import annotations

from pathlib import Path


def split_project_track(stem: str, separator: str = "-") -> tuple[str, str]:
    """Split `<project><sep><track>` on the first separator. Ungrouped names stay valid."""
    if not separator or separator not in stem:
        return stem, stem
    project, track = stem.split(separator, 1)
    if not project or not track:
        return stem, stem
    return project, track


def ids_for_path(path: Path, separator: str = "-") -> tuple[str, str]:
    return split_project_track(path.stem, separator)
