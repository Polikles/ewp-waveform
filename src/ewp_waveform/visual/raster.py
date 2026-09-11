"""VisualField column raster dispatch. Geometry stays out of the application layer."""

from __future__ import annotations

from collections.abc import Sequence

from ewp_waveform.visual.bars import (
    BarStyle,
    draw_mirrored_bars_alpha,
    draw_mirrored_bars_rgba,
)
from ewp_waveform.visual.plan import RenderPlan
from ewp_waveform.visual.ribbon import raster_ribbon_columns


def raster_field_columns(
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
    bar_style: BarStyle | None = None,
) -> bytes:
    if plan.geometry == "mirrored_bars":
        style = bar_style or BarStyle()
        if plan.path == "mask_fast":
            return draw_mirrored_bars_alpha(
                columns,
                width=width,
                height=height,
                style=style,
                amplitude=amplitude,
                center_line=center_line,
                content_height=content_height,
                supersample=plan.supersample,
                glow_sigma=glow_sigma,
            )
        return draw_mirrored_bars_rgba(
            columns,
            width=width,
            height=height,
            style=style,
            color=color,
            amplitude=amplitude,
            center_line=center_line,
            content_height=content_height,
            supersample=plan.supersample,
            glow_sigma=glow_sigma,
        )
    return raster_ribbon_columns(
        columns,
        plan=plan,
        width=width,
        height=height,
        color=color,
        amplitude=amplitude,
        center_line=center_line,
        content_height=content_height,
        glow_sigma=glow_sigma,
    )
