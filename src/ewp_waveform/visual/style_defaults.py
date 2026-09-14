"""Named geometry packs below VisualField. Not analysis, not private project data."""

from __future__ import annotations

from ewp_waveform.visual.bars import BarStyle

BAR_GEOMETRIES = frozenset({"mirrored_bars", "classic_ticks"})

# Thin open bars, optional alternate colors, full-width center stroke.
MIRRORED_LINE_DEFAULT = BarStyle(
    width=5.0,
    gap=7.0,
    align="period",
    alternate=True,
    color_b="#6E7BA7",
    center_line_width=2.0,
)

# Sparse thin ticks. Glow should be low; see default_glow_level().
CLASSIC_TICKS_DEFAULT = BarStyle(
    width=2.0,
    gap=12.0,
    align="period",
    alternate=False,
    center_line_width=0.0,
)

PALE_CYAN = "#C7E6EC"
WHITE = "#FFFFFF"
BLUE = "#6E7BA7"


def default_bar_style(field_geometry: str) -> BarStyle:
    if field_geometry == "classic_ticks":
        return CLASSIC_TICKS_DEFAULT
    return MIRRORED_LINE_DEFAULT


def default_glow_level(field_geometry: str) -> str | None:
    """Suggested glow when the caller does not override. None = keep the preset."""
    if field_geometry == "classic_ticks":
        return "low"
    return None
