"""Fixed-axis mirrored bars from a VisualField. No FFT, no scroll phase."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ewp_waveform.ffmpeg.draw import (
    _coverage_to_alpha,
    _mirrored_metrics,
    parse_rgb,
)


@dataclass(frozen=True)
class BarStyle:
    """Stationary bar metrics in output pixels. Independent of analysis."""

    width: float = 5.0
    gap: float = 3.0


def bar_spans(width: int, style: BarStyle) -> tuple[tuple[float, float], ...]:
    """Left/right edges of each bar, centered on the field midline. No scroll."""
    bar_w = max(1.0, float(style.width))
    gap = max(0.0, float(style.gap))
    period = bar_w + gap
    if width < 1 or period <= 0.0:
        return ()
    origin = (float(width) / 2.0) - (bar_w / 2.0)
    x0 = origin
    while x0 + bar_w > 0.0:
        x0 -= period
    x0 += period
    spans: list[tuple[float, float]] = []
    while x0 < float(width):
        spans.append((x0, x0 + bar_w))
        x0 += period
    return tuple(spans)


def _sample_column(columns: Sequence[float], x: float) -> float:
    n = len(columns)
    if n < 1:
        return 0.0
    if x <= 0.0:
        return max(0.0, float(columns[0]))
    last = float(n - 1)
    if x >= last:
        return max(0.0, float(columns[-1]))
    index = int(x)
    frac = x - float(index)
    left = max(0.0, float(columns[index]))
    right = max(0.0, float(columns[index + 1]))
    return left * (1.0 - frac) + right * frac


def mirrored_bar_alpha(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
    vertical_margin: int = 1,
) -> np.ndarray:
    """Coverage for stationary mirrored bars. Shape is (height, width * ss)."""
    ss = max(1, int(supersample))
    out_w = width * ss
    center, max_half, _margin, cap = _mirrored_metrics(
        height=height,
        amplitude=amplitude,
        glow_sigma=glow_sigma,
        vertical_margin=vertical_margin,
        content_height=content_height,
    )
    alpha = np.zeros((max(height, 0), max(out_w, 0)), dtype=np.uint8)
    if not columns or out_w < 1 or height < 1:
        return alpha
    yy = np.arange(height, dtype=np.float64)
    for x0, x1 in bar_spans(width, style):
        mag = min(1.0, _sample_column(columns, 0.5 * (x0 + x1)))
        half = min(float(max_half) * mag, cap)
        if half <= 0.0:
            continue
        sx0 = x0 * ss
        sx1 = x1 * ss
        y0 = float(center) - half
        y1 = float(center) + half + 1.0
        px0 = max(0, math.floor(sx0))
        px1 = min(out_w, math.ceil(sx1))
        py0 = max(0, math.floor(y0))
        py1 = min(height, math.ceil(y1))
        if px1 <= px0 or py1 <= py0:
            continue
        xs = np.arange(px0, px1, dtype=np.float64)
        ys = yy[py0:py1]
        xcov = np.clip(np.minimum(xs + 1.0, sx1) - np.maximum(xs, sx0), 0.0, 1.0)
        ycov = np.clip(np.minimum(ys + 1.0, y1) - np.maximum(ys, y0), 0.0, 1.0)
        cov = ycov[:, np.newaxis] * xcov[np.newaxis, :]
        patch = _coverage_to_alpha(cov)
        dest = alpha[py0:py1, px0:px1]
        np.maximum(dest, patch, out=dest)
    if center_line:
        y = min(height - 1, max(0, center))
        empty = alpha[y] == 0
        alpha[y, empty] = 140
    return alpha


def draw_mirrored_bars_alpha(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
) -> bytes:
    return bytes(
        mirrored_bar_alpha(
            columns,
            width=width,
            height=height,
            style=style,
            amplitude=amplitude,
            center_line=center_line,
            content_height=content_height,
            supersample=supersample,
            glow_sigma=glow_sigma,
        ).tobytes()
    )


def draw_mirrored_bars_rgba(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle,
    color: str,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
) -> bytes:
    r, g, b = parse_rgb(color)
    alpha = mirrored_bar_alpha(
        columns,
        width=width,
        height=height,
        style=style,
        amplitude=amplitude,
        center_line=center_line,
        content_height=content_height,
        supersample=supersample,
        glow_sigma=glow_sigma,
    )
    out_h, out_w = alpha.shape
    pixels = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    mask = alpha > 0
    pixels[..., 0][mask] = r
    pixels[..., 1][mask] = g
    pixels[..., 2][mask] = b
    pixels[..., 3] = alpha
    return bytes(pixels.tobytes())
