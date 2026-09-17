"""Segmented impulse geometry clipped by the shared smooth VisualField contour."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ewp_waveform.ffmpeg.draw import (
    _coverage_to_alpha,
    mirrored_contour_alpha,
    parse_rgb,
)
from ewp_waveform.visual.bars import BarStyle, bar_spans

SEGMENT_HEIGHT = 3.0
SEGMENT_GAP = 3.0

SEGMENTED_IMPULSE_DEFAULT = BarStyle(
    width=4.0,
    gap=4.0,
    align="period",
    alternate=False,
    center_line_width=0.0,
)


def _span_coverage(length: int, spans: Sequence[tuple[float, float]]) -> np.ndarray:
    coverage = np.zeros(max(0, length), dtype=np.float64)
    for left, right in spans:
        start = max(0, int(np.floor(left)))
        end = min(length, int(np.ceil(right)))
        if end <= start:
            continue
        pixels = np.arange(start, end, dtype=np.float64)
        patch = np.clip(
            np.minimum(pixels + 1.0, right) - np.maximum(pixels, left),
            0.0,
            1.0,
        )
        np.maximum(coverage[start:end], patch, out=coverage[start:end])
    return coverage


def _centered_spans(length: int, size: float, gap: float) -> tuple[tuple[float, float], ...]:
    cell = max(1.0, float(size))
    period = cell + max(0.0, float(gap))
    origin = float(length // 2) + 0.5 - cell / 2.0
    start = origin
    while start + cell > 0.0:
        start -= period
    start += period
    spans: list[tuple[float, float]] = []
    while start < float(length):
        spans.append((start, start + cell))
        start += period
    return tuple(spans)


def segmented_impulse_alpha(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle = SEGMENTED_IMPULSE_DEFAULT,
    amplitude: float,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
) -> np.ndarray:
    """Cell grid whose outer envelope is the shared centered smooth contour."""
    ss = max(1, int(supersample))
    base = mirrored_contour_alpha(
        columns,
        width=width,
        height=height,
        amplitude=amplitude,
        center_line=False,
        content_height=content_height,
        supersample=ss,
        glow_sigma=glow_sigma,
    )
    x_spans = tuple((left * ss, right * ss) for left, right in bar_spans(width, style))
    x_coverage = _span_coverage(width * ss, x_spans)
    y_coverage = _span_coverage(
        height,
        _centered_spans(height, SEGMENT_HEIGHT, SEGMENT_GAP),
    )
    grid = _coverage_to_alpha(y_coverage[:, np.newaxis] * x_coverage[np.newaxis, :])
    result = base.copy()
    np.minimum(base, grid, out=result)
    return result


def draw_segmented_impulse_alpha(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle = SEGMENTED_IMPULSE_DEFAULT,
    amplitude: float,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
) -> bytes:
    return bytes(
        segmented_impulse_alpha(
            columns,
            width=width,
            height=height,
            style=style,
            amplitude=amplitude,
            content_height=content_height,
            supersample=supersample,
            glow_sigma=glow_sigma,
        ).tobytes()
    )


def draw_segmented_impulse_rgba(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    style: BarStyle = SEGMENTED_IMPULSE_DEFAULT,
    color: str,
    amplitude: float,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
) -> bytes:
    alpha = segmented_impulse_alpha(
        columns,
        width=width,
        height=height,
        style=style,
        amplitude=amplitude,
        content_height=content_height,
        supersample=supersample,
        glow_sigma=glow_sigma,
    )
    red, green, blue = parse_rgb(color)
    pixels = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    mask = alpha > 0
    pixels[..., 0][mask] = red
    pixels[..., 1][mask] = green
    pixels[..., 2][mask] = blue
    pixels[..., 3] = alpha
    return bytes(pixels.tobytes())
