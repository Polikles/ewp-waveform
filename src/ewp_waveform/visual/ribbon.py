"""Filled-ribbon geometry from a VisualField. No FFT or frequency knowledge."""

from __future__ import annotations

from ewp_waveform.analysis.spectrum import upsample_bands
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE, draw_spectrum_frame
from ewp_waveform.visual.models import VisualField


def field_to_columns(field: VisualField, width: int) -> list[float]:
    """Interpolate stationary visual slots onto the output X axis."""
    return upsample_bands(field.amplitude, width)


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
