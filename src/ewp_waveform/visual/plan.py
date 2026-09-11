"""Render-plan selection below VisualField. Not a public preset setting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ewp_waveform.config.models import VisualPreset
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE

MASK_GEOMETRIES = frozenset({"ribbon", "mirrored_bars"})

RenderPath = Literal["mask_fast", "rgba_2d"]
AAMode = Literal["physical_ss", "coverage_taps"]
PixFmt = Literal["gray", "rgba"]


@dataclass(frozen=True)
class RenderCapabilities:
    """What the requested style + effects actually need."""

    per_pixel_color: bool
    gradient: bool
    independent_segment_color: bool
    particles: bool
    glow: bool
    mask_renderable_geometry: bool


@dataclass(frozen=True)
class RenderPlan:
    """Cheapest faithful representation for this style + effects."""

    path: RenderPath
    pix_fmt: PixFmt
    bytes_per_pixel: int
    supersample: int
    aa_mode: AAMode
    aa_taps: int
    colorize: bool
    geometry: str
    fallback_from: str | None = None

    @property
    def input_width(self) -> int:
        return self.supersample

    def bytes_per_frame(self, width: int, height: int, overscan: int) -> int:
        in_w = (width + 2 * overscan) * max(1, self.supersample)
        in_h = height + 2 * overscan
        return in_w * in_h * self.bytes_per_pixel


def inspect_capabilities(
    preset: VisualPreset,
    *,
    layout: str = "linear",
    field_geometry: str = "ribbon",
) -> RenderCapabilities:
    particles = preset.effects.get("particles")
    particles_on = isinstance(particles, dict) and bool(particles.get("enabled"))
    glow = preset.effects.get("glow")
    glow_on = (
        isinstance(glow, dict)
        and bool(glow.get("enabled"))
        and str(glow.get("level") or "none") != "none"
    )
    palette_gradient = "gradient" in {str(k).lower() for k in preset.palette}
    mask_ok = (
        str(preset.waveform.domain) == "frequency"
        and layout == "field_center_out"
        and field_geometry in MASK_GEOMETRIES
    )
    return RenderCapabilities(
        per_pixel_color=False,
        gradient=palette_gradient,
        independent_segment_color=False,
        particles=particles_on,
        glow=glow_on,
        mask_renderable_geometry=mask_ok,
    )


def resolve_render_plan(
    preset: VisualPreset,
    *,
    layout: str = "linear",
    field_geometry: str = "ribbon",
    ribbon_supersample: int | None = None,
    force_path: RenderPath | None = None,
    aa_mode: AAMode | None = None,
) -> RenderPlan:
    """Select MASK_FAST or RGBA_2D from required capabilities, not style name alone."""
    geometry = field_geometry if field_geometry in MASK_GEOMETRIES else str(preset.waveform.style)
    caps = inspect_capabilities(preset, layout=layout, field_geometry=field_geometry)
    ss = max(1, int(ribbon_supersample) if ribbon_supersample is not None else RIBBON_SUPERSAMPLE)
    needs_rgba = (
        caps.per_pixel_color or caps.gradient or caps.independent_segment_color or caps.particles
    )
    if force_path == "rgba_2d" or needs_rgba or not caps.mask_renderable_geometry:
        return RenderPlan(
            path="rgba_2d",
            pix_fmt="rgba",
            bytes_per_pixel=4,
            supersample=ss,
            aa_mode="physical_ss",
            aa_taps=1,
            colorize=False,
            geometry=geometry,
            fallback_from="mask_fast" if caps.mask_renderable_geometry else None,
        )
    mode: AAMode = aa_mode if aa_mode is not None else "physical_ss"
    if mode == "coverage_taps":
        return RenderPlan(
            path="mask_fast",
            pix_fmt="gray",
            bytes_per_pixel=1,
            supersample=1,
            aa_mode="coverage_taps",
            aa_taps=max(2, ss),
            colorize=True,
            geometry=geometry,
        )
    return RenderPlan(
        path="mask_fast",
        pix_fmt="gray",
        bytes_per_pixel=1,
        supersample=ss,
        aa_mode="physical_ss",
        aa_taps=1,
        colorize=True,
        geometry=geometry,
    )
