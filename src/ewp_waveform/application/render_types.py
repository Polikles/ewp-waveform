"""Internal raw render transport; resolution and lifecycle stay in application.render."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.models import PlannedJob, SourceMedia


@dataclass(frozen=True)
class RenderOptions:
    """Legacy keyword values, deliberately unvalidated and only shallowly frozen."""

    output_dir: Path
    formats: list[str]
    force: bool
    start: float | None = None
    duration: float | None = None
    keep_temp: bool = False
    fail_after_chunk: int | None = None
    progress: Callable[[str], None] | None = None
    spectrum_contour: bool = False
    spectrum_spatial_scale: float = 1.0
    spectrum_spatial_filter: str = "box"
    spectrum_n_bands: int | None = None
    spectrum_tilt_db_per_octave: float = 0.0
    spectrum_compress: float = 1.0
    spectrum_recenter: bool = False
    spectrum_edge_taper: float = 0.0
    visual_geometry: str = "spectrum"
    spectrum_layout: str = "linear"
    spectrum_slot_sigma: float = 0.0
    ribbon_supersample: int | None = None
    render_path: str | None = None
    render_aa: str | None = None
    field_geometry: str = "ribbon"
    bar_width: float | None = None
    bar_gap: float | None = None
    bar_count: int | None = None
    bar_fill: float | None = None
    bar_align: str | None = None
    bar_alternate: bool | None = None
    bar_color_b: str | None = None
    bar_center_line_width: float | None = None
    waveform_color: str | None = None
    glow_level: str | None = None
    classic_alternate_opacity: float | None = None
    phases: PhaseTimes | None = None


@dataclass(frozen=True)
class RenderContext:
    """Existing references only; do not pre-resolve workdirs, appearance or destinations."""

    job: PlannedJob
    media: SourceMedia
    preset: VisualPreset
    performance: PerformanceProfile


@dataclass(frozen=True)
class RendererOutcome:
    """Carry the original result dictionary without copying or serialization."""

    payload: dict[str, Any]
