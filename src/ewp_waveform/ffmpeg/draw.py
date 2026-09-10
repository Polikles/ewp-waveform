"""Draw RGBA frames for scrolling envelope bars (mirrored-line family)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ewp_waveform.analysis.envelope import sample_bin
from ewp_waveform.analysis.interp import pchip_eval_many, pchip_slopes

# 12x covers the 1/3-pixel phase cycle at 1400/5s/60fps (~4.67 px/frame).
SCROLL_SUPERSAMPLE = 12
# Pre-perf-pass ribbon raster. Pass ribbon_supersample=this to restore 12x.
RIBBON_SUPERSAMPLE_BASELINE = 12
# Fixed-axis X does not move. 2x keeps area-downsampled AA; 1x stairs the contour.
RIBBON_SUPERSAMPLE = 2


def parse_rgb(color: str) -> tuple[int, int, int]:
    raw = color.removeprefix("#")
    if len(raw) != 6:
        msg = f"expected #RRGGBB color, got {color!r}"
        raise ValueError(msg)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def bar_metrics(style: str, stroke_width: float) -> tuple[int, int]:
    stroke = max(1, round(stroke_width or 1.0))
    if style == "segmented":
        return max(stroke, 4), max(stroke, 4)
    if style == "filled":
        return 1, 0
    if style == "classic":
        return max(1, stroke // 2), 2
    # mirrored line: dense touching bars, no 1 px gap (that gap strobes).
    return stroke, 0


def glow_vertical_margin(sigma: float) -> int:
    """Inner gutter when drawing without overscan."""
    if sigma <= 0:
        return 1
    return max(2, round(sigma * 2) + 1)


def glow_overscan(sigma: float) -> int:
    """Extra rows/cols so gblur can expand without clipping peaks."""
    if sigma <= 0:
        return 0
    return max(8, round(sigma * 3) + 2)


def _mirrored_metrics(
    *,
    height: int,
    amplitude: float,
    glow_sigma: float,
    vertical_margin: int,
    content_height: int | None,
) -> tuple[int, int, int, float]:
    """Return center y, peak half-height, margin, and vertical cap."""
    center = height // 2
    inner = content_height or height
    if glow_sigma > 0:
        max_half = peak_half_height(inner, glow_sigma, amplitude)
        margin = glow_overscan(glow_sigma)
    else:
        margin = max(0, vertical_margin)
        usable = min(inner // 2, inner - inner // 2 - 1) - margin
        max_half = max(1, round(max(1, usable) * min(max(amplitude, 0.0), 1.0)))
    cap = max(1.0, float(min(center - margin, height - center - 1 - margin)))
    return center, max_half, margin, cap


def _draw_center_line(
    frame: bytearray,
    *,
    width: int,
    height: int,
    center: int,
    r: int,
    g: int,
    b: int,
) -> None:
    y = min(height - 1, max(0, center))
    row = y * width * 4
    for px in range(width):
        off = row + px * 4
        if frame[off + 3] == 0:
            frame[off] = r
            frame[off + 1] = g
            frame[off + 2] = b
            frame[off + 3] = 140


def peak_half_height(content_height: int, glow_sigma: float, amplitude: float = 1.0) -> int:
    """Bar half-height that leaves gblur room inside the output frame.

    Derived from canvas height and glow sigma, not a fixed pixel count.
    ``amplitude`` is the fill of that glow-safe region (1.0 = use all of it).
    """
    spread = glow_overscan(glow_sigma) if glow_sigma > 0 else 2
    usable = content_height // 2 - spread
    return max(1, round(max(1, usable) * min(max(amplitude, 0.0), 1.0)))


def _put_span(
    frame: bytearray,
    *,
    width: int,
    height: int,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    r: int,
    g: int,
    b: int,
) -> None:
    """Fill [x0, x1) x [y0, y1) with coverage-based alpha on partial columns and rows."""
    px0 = max(0, math.floor(x0))
    px1 = min(width, math.ceil(x1))
    py0 = max(0, math.floor(y0))
    py1 = min(height, math.ceil(y1))
    for px in range(px0, px1):
        xcov = min(float(px) + 1.0, x1) - max(float(px), x0)
        if xcov <= 0.0:
            continue
        xcov = min(1.0, xcov)
        for py in range(py0, py1):
            ycov = min(float(py) + 1.0, y1) - max(float(py), y0)
            if ycov <= 0.0:
                continue
            cov = xcov * min(1.0, ycov)
            alpha = 255 if cov >= 1.0 - 1e-6 else max(1, min(255, round(255.0 * cov)))
            off = (py * width + px) * 4
            if alpha >= 255 or frame[off + 3] < alpha:
                frame[off] = r
                frame[off + 1] = g
                frame[off + 2] = b
                frame[off + 3] = alpha if alpha >= 255 else max(frame[off + 3], alpha)


def draw_envelope_frame(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    color: str,
    amplitude: float,
    stroke_width: float,
    style: str,
    center_line: bool,
    scroll_phase: float = 0.0,
    vertical_margin: int = 1,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
    envelope_oversample: int = 1,
) -> bytes:
    """Mirrored columns. ``scroll_phase`` is the left edge in output pixels (timestamp-derived).

    Envelope columns may be denser than output pixels (``envelope_oversample``).
    Magnitude lerps only between adjacent dense bins. ``supersample`` is raster
    pixels per output column.
    """
    ss = max(1, int(supersample))
    r, g, b = parse_rgb(color)
    out_w = width * ss
    frame = bytearray(out_w * height * 4)
    center, max_half, _margin, cap = _mirrored_metrics(
        height=height,
        amplitude=amplitude,
        glow_sigma=glow_sigma,
        vertical_margin=vertical_margin,
        content_height=content_height,
    )
    stroke, gap = bar_metrics(style, stroke_width)
    stroke_ss = stroke * ss
    gap_ss = gap * ss
    period_ss = stroke_ss + gap_ss
    env_ss = max(1, int(envelope_oversample))
    phase_env_floor = math.floor(scroll_phase * env_ss)
    phase_ss = scroll_phase * ss
    if columns:
        # Gapless styles: one ss-pixel column each, interpolated envelope.
        # Gapped styles keep discrete bars, still with fractional bin sampling.
        if gap_ss == 0 or period_ss <= 1:
            xs: list[float] = [float(x) for x in range(out_w)]
            strip_w = 1.0
        else:
            rem = phase_ss % period_ss
            first = 0.0 if rem == 0.0 else period_ss - rem
            xs = []
            x = first - period_ss
            while x < out_w:
                if x + stroke_ss > 0:
                    xs.append(x)
                x += period_ss
            strip_w = float(stroke_ss)
        for x in xs:
            world_px = scroll_phase + x / ss
            mag = sample_bin(columns, world_px * env_ss - phase_env_floor)
            half = min(float(max_half), float(max_half) * mag)
            if half <= 0.0:
                continue
            half = min(half, cap)
            y0 = float(center) - half
            y1 = float(center) + half + 1.0
            _put_span(
                frame,
                width=out_w,
                height=height,
                x0=x,
                x1=x + strip_w,
                y0=y0,
                y1=y1,
                r=r,
                g=g,
                b=b,
            )
    if center_line:
        _draw_center_line(frame, width=out_w, height=height, center=center, r=r, g=g, b=b)
    return bytes(frame)


def draw_spectrum_frame(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    color: str,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
    vertical_margin: int = 1,
) -> bytes:
    """Mirrored filled contour from per-X amplitudes (PCHIP, no peak overshoot).

    Knots are one amplitude per output pixel. Rasterization is a filled region
    under the reconstructed upper contour, mirrored through the center line.
    """
    ss = max(1, int(supersample))
    r, g, b = parse_rgb(color)
    out_w = width * ss
    center, max_half, _margin, cap = _mirrored_metrics(
        height=height,
        amplitude=amplitude,
        glow_sigma=glow_sigma,
        vertical_margin=vertical_margin,
        content_height=content_height,
    )
    pixels = np.zeros((height, out_w, 4), dtype=np.uint8)
    if columns and out_w > 0 and height > 0:
        knots = [min(max(float(value), 0.0), 1.0) for value in columns]
        slopes = pchip_slopes(knots)
        xs = np.arange(out_w, dtype=np.float64) / float(ss)
        mags = pchip_eval_many(knots, slopes, xs, unit=True)
        halfs = np.minimum(float(max_half) * mags, cap)
        y0 = np.where(halfs > 0.0, float(center) - halfs, 0.0)
        y1 = np.where(halfs > 0.0, float(center) + halfs + 1.0, 0.0)
        yy = np.arange(height, dtype=np.float64)[:, np.newaxis]
        cov = np.clip(np.minimum(yy + 1.0, y1) - np.maximum(yy, y0), 0.0, 1.0)
        alpha = np.rint(255.0 * cov).astype(np.int16)
        np.clip(alpha, 0, 255, out=alpha)
        full = cov >= (1.0 - 1e-6)
        partial = (cov > 0.0) & ~full
        alpha[full] = 255
        alpha[partial] = np.maximum(alpha[partial], 1)
        mask = alpha > 0
        pixels[..., 0][mask] = r
        pixels[..., 1][mask] = g
        pixels[..., 2][mask] = b
        pixels[..., 3] = alpha.astype(np.uint8, copy=False)
    frame = bytearray(pixels.tobytes())
    if center_line:
        _draw_center_line(frame, width=out_w, height=height, center=center, r=r, g=g, b=b)
    return bytes(frame)
