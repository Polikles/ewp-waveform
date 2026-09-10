"""Filled-ribbon geometry from a VisualField. No FFT or frequency knowledge."""

from __future__ import annotations

from collections.abc import Sequence

from ewp_waveform.analysis.spectrum import upsample_bands
from ewp_waveform.ffmpeg.draw import (
    RIBBON_SUPERSAMPLE,
    draw_spectrum_alpha,
    draw_spectrum_frame,
)
from ewp_waveform.visual.models import VisualField
from ewp_waveform.visual.plan import RenderPlan


def field_to_columns(field: VisualField, width: int) -> list[float]:
    """Interpolate stationary visual slots onto the output X axis."""
    return upsample_bands(field.amplitude, width)


def raster_ribbon_columns(
    columns: Sequence[float],
    *,
    plan: RenderPlan,
    width: int,
    height: int,
    color: str,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    glow_sigma: float = 0.0,
) -> bytes:
    """Raster one ribbon frame using the selected representation."""
    if plan.path == "mask_fast":
        return draw_spectrum_alpha(
            columns,
            width=width,
            height=height,
            amplitude=amplitude,
            center_line=center_line,
            content_height=content_height,
            supersample=plan.supersample,
            glow_sigma=glow_sigma,
            aa_taps=plan.aa_taps,
        )
    return draw_spectrum_frame(
        columns,
        width=width,
        height=height,
        color=color,
        amplitude=amplitude,
        center_line=center_line,
        content_height=content_height,
        supersample=plan.supersample,
        glow_sigma=glow_sigma,
        aa_taps=plan.aa_taps,
    )


def render_ribbon_frame(
    field: VisualField,
    *,
    width: int,
    height: int,
    color: str,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = RIBBON_SUPERSAMPLE,
    glow_sigma: float = 0.0,
) -> bytes:
    """Mirrored filled contour. Vertical symmetry is a draw style, not a field copy."""
    columns = field_to_columns(field, width)
    return draw_spectrum_frame(
        columns,
        width=width,
        height=height,
        color=color,
        amplitude=amplitude,
        center_line=center_line,
        content_height=content_height,
        supersample=supersample,
        glow_sigma=glow_sigma,
    )
