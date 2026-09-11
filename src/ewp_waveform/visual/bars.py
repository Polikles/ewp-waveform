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
    """Stationary bar metrics. Independent of analysis.

    ``align``:
    - ``period`` — walk ``width``/``gap`` from the field midline;
    - ``count`` — ``count`` equal-spaced bars across the frame;
    - ``slots`` — one bar per VisualField slot, centers on slot knots.
    """

    width: float = 5.0
    gap: float = 7.0
    count: int | None = None
    fill: float = 0.62
    align: str = "period"
    n_slots: int = 65
    alternate: bool = True
    color_b: str = "#6E7BA7"
    center_line_width: float = 2.0


# T1 thin + G2 open gap + C1 alternate + L2 center line.
MIRRORED_LINE_DEFAULT = BarStyle()


def bar_spans(width: int, style: BarStyle) -> tuple[tuple[float, float], ...]:
    """Left/right edges of each bar. Stationary; no scroll phase."""
    if width < 1:
        return ()
    align = style.align
    if align == "slots":
        n = max(1, int(style.count) if style.count is not None else int(style.n_slots))
        fill = min(max(float(style.fill), 0.05), 0.95)
        bar_w = max(1.0, (float(width) / float(n)) * fill)
        last = max(n - 1, 1)
        slot_spans: list[tuple[float, float]] = []
        for i in range(n):
            center = (float(i) / float(last)) * float(width - 1)
            slot_spans.append((center - bar_w / 2.0, center + bar_w / 2.0))
        return tuple(slot_spans)
    if align == "count" or style.count is not None:
        n = max(1, int(style.count) if style.count is not None else 1)
        fill = min(max(float(style.fill), 0.05), 0.95)
        period = float(width) / float(n)
        bar_w = max(1.0, period * fill)
        count_spans: list[tuple[float, float]] = []
        for i in range(n):
            center = (float(i) + 0.5) * period
            count_spans.append((center - bar_w / 2.0, center + bar_w / 2.0))
        return tuple(count_spans)
    bar_w = max(1.0, float(style.width))
    gap = max(0.0, float(style.gap))
    period = bar_w + gap
    if period <= 0.0:
        return ()
    origin = (float(width) / 2.0) - (bar_w / 2.0)
    x0 = origin
    while x0 + bar_w > 0.0:
        x0 -= period
    x0 += period
    period_spans: list[tuple[float, float]] = []
    while x0 < float(width):
        period_spans.append((x0, x0 + bar_w))
        x0 += period
    return tuple(period_spans)


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


def _stamp_rect(
    alpha: np.ndarray,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    yy: np.ndarray,
) -> tuple[int, int, int, int, np.ndarray] | None:
    height, out_w = alpha.shape
    px0 = max(0, math.floor(x0))
    px1 = min(out_w, math.ceil(x1))
    py0 = max(0, math.floor(y0))
    py1 = min(height, math.ceil(y1))
    if px1 <= px0 or py1 <= py0:
        return None
    xs = np.arange(px0, px1, dtype=np.float64)
    ys = yy[py0:py1]
    xcov = np.clip(np.minimum(xs + 1.0, x1) - np.maximum(xs, x0), 0.0, 1.0)
    ycov = np.clip(np.minimum(ys + 1.0, y1) - np.maximum(ys, y0), 0.0, 1.0)
    patch = _coverage_to_alpha(ycov[:, np.newaxis] * xcov[np.newaxis, :])
    dest = alpha[py0:py1, px0:px1]
    np.maximum(dest, patch, out=dest)
    return px0, px1, py0, py1, patch


def _paint_center_line(
    alpha: np.ndarray,
    *,
    center: int,
    line_width: float,
    ss: int,
    yy: np.ndarray,
) -> None:
    if line_width <= 0.0:
        return
    half = max(0.5, float(line_width) * float(ss) / 2.0)
    y0 = float(center) + 0.5 - half
    y1 = float(center) + 0.5 + half
    _stamp_rect(alpha, x0=0.0, x1=float(alpha.shape[1]), y0=y0, y1=y1, yy=yy)


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
        _stamp_rect(
            alpha,
            x0=x0 * ss,
            x1=x1 * ss,
            y0=float(center) - half,
            y1=float(center) + half + 1.0,
            yy=yy,
        )
    line_w = float(style.center_line_width)
    if line_w > 0.0:
        _paint_center_line(alpha, center=center, line_width=line_w, ss=ss, yy=yy)
    elif center_line:
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
    r_a, g_a, b_a = parse_rgb(color)
    r_b, g_b, b_b = parse_rgb(style.color_b)
    ss = max(1, int(supersample))
    out_w = width * ss
    center, max_half, _margin, cap = _mirrored_metrics(
        height=height,
        amplitude=amplitude,
        glow_sigma=glow_sigma,
        vertical_margin=1,
        content_height=content_height,
    )
    pixels = np.zeros((max(height, 0), max(out_w, 0), 4), dtype=np.uint8)
    if not columns or out_w < 1 or height < 1:
        return bytes(pixels.tobytes())
    yy = np.arange(height, dtype=np.float64)
    alpha = pixels[..., 3]
    for index, (x0, x1) in enumerate(bar_spans(width, style)):
        mag = min(1.0, _sample_column(columns, 0.5 * (x0 + x1)))
        half = min(float(max_half) * mag, cap)
        if half <= 0.0:
            continue
        stamped = _stamp_rect(
            alpha,
            x0=x0 * ss,
            x1=x1 * ss,
            y0=float(center) - half,
            y1=float(center) + half + 1.0,
            yy=yy,
        )
        if stamped is None:
            continue
        px0, px1, py0, py1, patch = stamped
        use_b = style.alternate and index % 2 == 1
        r, g, b = (r_b, g_b, b_b) if use_b else (r_a, g_a, b_a)
        mask = patch > 0
        sl = pixels[py0:py1, px0:px1]
        sl[..., 0][mask] = r
        sl[..., 1][mask] = g
        sl[..., 2][mask] = b
    line_w = float(style.center_line_width)
    if line_w > 0.0:
        line = np.zeros_like(alpha)
        _paint_center_line(line, center=center, line_width=line_w, ss=ss, yy=yy)
        mask = line > 0
        np.maximum(alpha, line, out=alpha)
        pixels[..., 0][mask] = r_a
        pixels[..., 1][mask] = g_a
        pixels[..., 2][mask] = b_a
    elif center_line:
        y = min(height - 1, max(0, center))
        empty = alpha[y] == 0
        alpha[y, empty] = 140
        pixels[y, empty, 0] = r_a
        pixels[y, empty, 1] = g_a
        pixels[y, empty, 2] = b_a
    return bytes(pixels.tobytes())
