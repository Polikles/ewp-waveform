"""Shape-preserving interpolation helpers (PCHIP)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray


def _pchip_end_slope(slope: float, delta: float) -> float:
    if delta == 0.0:
        return 0.0
    if (slope > 0.0) != (delta > 0.0):
        return 0.0
    limit = 3.0 * delta
    if abs(slope) > abs(limit):
        return limit
    return slope


def pchip_slopes(values: Sequence[float]) -> list[float]:
    """Fritsch-Carlson PCHIP slopes on unit-spaced knots. No overshoot of local peaks."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    delta = [values[i + 1] - values[i] for i in range(n - 1)]
    slopes = [0.0] * n
    slopes[0] = delta[0]
    slopes[-1] = delta[-1]
    for i in range(1, n - 1):
        left = delta[i - 1]
        right = delta[i]
        if left == 0.0 or right == 0.0 or (left > 0.0) != (right > 0.0):
            slopes[i] = 0.0
        else:
            slopes[i] = 2.0 / (1.0 / left + 1.0 / right)
    slopes[0] = _pchip_end_slope(slopes[0], delta[0])
    slopes[-1] = _pchip_end_slope(slopes[-1], delta[-1])
    return slopes


def pchip_eval(
    values: Sequence[float],
    slopes: Sequence[float],
    x: float,
    *,
    unit: bool = True,
) -> float:
    """Hermite cubic on unit-spaced knots. Clamped to the local knot pair and >= 0.

    ``unit`` also clamps to 1.0 for raster amplitudes already in 0..1.
    """
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        y = max(values[0], 0.0)
        return min(y, 1.0) if unit else y
    if x <= 0.0:
        y = max(values[0], 0.0)
        return min(y, 1.0) if unit else y
    last = float(n - 1)
    if x >= last:
        y = max(values[-1], 0.0)
        return min(y, 1.0) if unit else y
    i = min(n - 2, math.floor(x))
    t = x - i
    y0 = values[i]
    y1 = values[i + 1]
    d0 = slopes[i]
    d1 = slopes[i + 1]
    t2 = t * t
    t3 = t2 * t
    y = (
        y0 * (2.0 * t3 - 3.0 * t2 + 1.0)
        + d0 * (t3 - 2.0 * t2 + t)
        + y1 * (-2.0 * t3 + 3.0 * t2)
        + d1 * (t3 - t2)
    )
    lo = min(y0, y1)
    hi = max(y0, y1)
    y = min(max(y, lo, 0.0), hi)
    if unit:
        y = min(y, 1.0)
    return y


def pchip_eval_many(
    values: Sequence[float],
    slopes: Sequence[float],
    xs: Sequence[float] | NDArray[np.float64],
    *,
    unit: bool = True,
) -> NDArray[np.float64]:
    """Vectorized ``pchip_eval`` over many x coordinates."""
    knots = np.asarray(values, dtype=np.float64)
    deriv = np.asarray(slopes, dtype=np.float64)
    positions = np.asarray(xs, dtype=np.float64)
    n = int(knots.shape[0])
    out = np.zeros(positions.shape, dtype=np.float64)
    if n == 0:
        return out
    if n == 1:
        y = max(float(knots[0]), 0.0)
        out.fill(min(y, 1.0) if unit else y)
        return out
    last = float(n - 1)
    y_first = max(float(knots[0]), 0.0)
    y_last = max(float(knots[-1]), 0.0)
    if unit:
        y_first = min(y_first, 1.0)
        y_last = min(y_last, 1.0)
    out[positions <= 0.0] = y_first
    out[positions >= last] = y_last
    mid = (positions > 0.0) & (positions < last)
    if not np.any(mid):
        return out
    xm = positions[mid]
    index = np.minimum(n - 2, np.floor(xm).astype(np.int64))
    t = xm - index.astype(np.float64)
    y0 = knots[index]
    y1 = knots[index + 1]
    d0 = deriv[index]
    d1 = deriv[index + 1]
    t2 = t * t
    t3 = t2 * t
    y = (
        y0 * (2.0 * t3 - 3.0 * t2 + 1.0)
        + d0 * (t3 - 2.0 * t2 + t)
        + y1 * (-2.0 * t3 + 3.0 * t2)
        + d1 * (t3 - t2)
    )
    lo = np.minimum(y0, y1)
    hi = np.maximum(y0, y1)
    y = np.minimum(np.maximum(np.maximum(y, lo), 0.0), hi)
    if unit:
        y = np.minimum(y, 1.0)
    out[mid] = y
    return out
