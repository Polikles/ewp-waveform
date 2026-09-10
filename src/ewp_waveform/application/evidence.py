"""Empirical performance fingerprints for later labelled dry-run estimates."""

from __future__ import annotations

import os
import platform
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PerformanceFingerprint:
    """Enough to match a later job to measured evidence. Not a predictor."""

    renderer: str
    render_path: str
    visual_style: str
    geometry: str
    glow: bool
    particles: bool
    width: int
    height: int
    fps: float
    aa_mode: str
    supersample: int
    pix_fmt: str
    codec: str
    jobs: int
    ffmpeg_threads: int
    nproc: int | None
    machine: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_from_plan(
    *,
    plan_path: str,
    geometry: str,
    style: str,
    glow: bool,
    particles: bool,
    width: int,
    height: int,
    fps: float,
    aa_mode: str,
    supersample: int,
    pix_fmt: str,
    codec: str,
    jobs: int,
    ffmpeg_threads: int,
    renderer: str = "ffmpeg",
) -> PerformanceFingerprint:
    nproc_raw = os.cpu_count()
    return PerformanceFingerprint(
        renderer=renderer,
        render_path=plan_path,
        visual_style=style,
        geometry=geometry,
        glow=glow,
        particles=particles,
        width=width,
        height=height,
        fps=fps,
        aa_mode=aa_mode,
        supersample=supersample,
        pix_fmt=pix_fmt,
        codec=codec,
        jobs=jobs,
        ffmpeg_threads=ffmpeg_threads,
        nproc=nproc_raw,
        machine=platform.platform(),
    )
