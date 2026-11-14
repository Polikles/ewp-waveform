"""Exact interval boundary-only floating coverage against a dense oracle."""

from __future__ import annotations

import numpy as np
import pytest

from ewp_waveform.ffmpeg import draw


def dense(y0: np.ndarray, y1: np.ndarray, height: int) -> np.ndarray:
    yy = np.arange(height, dtype=np.float64)[:, None]
    cov = np.clip(np.minimum(yy + 1.0, y1) - np.maximum(yy, y0), 0, 1)
    alpha = np.rint(255 * cov).astype(np.int16)
    np.clip(alpha, 0, 255, out=alpha)
    full = cov >= 1.0 - 1e-6
    partial = (cov > 0.0) & ~full
    alpha[full] = 255
    alpha[partial] = np.maximum(alpha[partial], 1)
    result: np.ndarray = alpha.astype(np.uint8)
    return result


@pytest.mark.parametrize("height", [1, 2, 3, 17, 380])
def test_random_arbitrary_intervals_and_ownership(height: int) -> None:
    rng = np.random.default_rng(1729)
    for _ in range(25):
        y0 = rng.uniform(-height, height * 2, 87)
        y1 = rng.uniform(-height, height * 2, 87)
        y0[::11] = y1[::11]
        start, stop = draw._contour_row_support(y0, y1, height)
        expected = dense(y0, y1, height)
        actual = draw._interval_contour_alpha(y0, y1, height, start, stop)
        np.testing.assert_array_equal(actual, expected)
        assert actual.flags.owndata and actual.flags.c_contiguous
        actual[:] = 0
        assert not np.shares_memory(actual, y0)


def test_every_quantization_halfway_and_near_full() -> None:
    values = np.concatenate(
        [np.arange(255) / 255 + 0.5 / 255, [0, np.nextafter(0.0, 1.0), 1.0 - 1e-6, 1.0]]
    )
    values = np.concatenate([values, np.nextafter(values, 0), np.nextafter(values, 1)])
    for y0, y1 in [
        (np.zeros(values.size), values),
        (2 - values, np.full(values.size, 3.0)),
        (np.full(values.size, 1.0), 1 + values),
    ]:
        start, stop = draw._contour_row_support(y0, y1, 5)
        np.testing.assert_array_equal(
            draw._interval_contour_alpha(y0, y1, 5, start, stop), dense(y0, y1, 5)
        )


def test_finite_huge_offcanvas_and_zero_spans() -> None:
    y0 = np.array([-1e300, 1e300, -1e300, 0.0, 5.0, 2.25])
    y1 = np.array([1e300, 1e300, -1e300, 0.0, 4.0, 2.75])
    start, stop = draw._contour_row_support(y0, y1, 7)
    np.testing.assert_array_equal(
        draw._interval_contour_alpha(y0, y1, 7, start, stop), dense(y0, y1, 7)
    )
