"""Resolve repository / install data directories."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the repo root in a src/ checkout (`…/ewp-waveform`)."""
    return Path(__file__).resolve().parents[2]


def builtin_presets_dir() -> Path:
    return project_root() / "presets"


def builtin_performance_dir() -> Path:
    return project_root() / "performance"
