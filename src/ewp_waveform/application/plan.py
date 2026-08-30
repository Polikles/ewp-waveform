"""Dry-run job plans: destinations, signatures, SKIP vs PROCESS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ewp_waveform.application.render import planned_destinations, publish_path
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.domain.models import PlannedJob, SourceMedia


@dataclass(frozen=True)
class JobPlan:
    job: PlannedJob
    media: SourceMedia | None
    source_sha256: str | None
    render_signature: str | None
    mov_path: Path | None
    png_path: Path | None
    action: str


def classify_action(
    *,
    mov_path: Path | None,
    png_path: Path | None,
    force: bool,
) -> tuple[str, Path | None, Path | None]:
    """Return PROCESS/SKIP and the dests that would be used (versioned if force)."""
    mov = mov_path
    png = png_path
    skip_mov = False
    skip_png = False
    if mov is not None:
        mov, skip_mov = publish_path(mov, force=force)
    if png is not None:
        png, skip_png = publish_path(png, force=force)
    want_mov = mov_path is not None
    want_png = png_path is not None
    if force:
        return "PROCESS", mov, png
    if (want_mov or want_png) and (not want_mov or skip_mov) and (not want_png or skip_png):
        return "SKIP", mov, png
    return "PROCESS", mov, png


def plan_destinations_for_job(
    job: PlannedJob,
    preset: VisualPreset,
    *,
    source_sha256: str,
    output_dir: Path,
    formats: list[str],
    force: bool,
) -> JobPlan:
    sig, mov, png = planned_destinations(
        job,
        preset,
        source_sha256=source_sha256,
        output_dir=output_dir,
        formats=formats,
    )
    action, mov_out, png_out = classify_action(mov_path=mov, png_path=png, force=force)
    return JobPlan(
        job=job,
        media=None,
        source_sha256=source_sha256,
        render_signature=sig,
        mov_path=mov_out,
        png_path=png_out,
        action=action,
    )
