"""Frozen pre-scratch contour arithmetic: exact alpha and straight-RGBA oracles."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from ewp_waveform.analysis.interp import pchip_eval_many, pchip_slopes
from ewp_waveform.ffmpeg.draw import (
    _coverage_to_alpha,
    _mirrored_metrics,
    draw_spectrum_alpha,
    draw_spectrum_frame,
    mirrored_contour_alpha,
)


def _reference_alpha(cov: NDArray[np.float64]) -> NDArray[np.uint8]:
    # Arithmetic from dffa2735; do not replace with the optimized helper.
    alpha = np.rint(255.0 * cov).astype(np.int16)
    np.clip(alpha, 0, 255, out=alpha)
    full = cov >= (1.0 - 1e-6)
    partial = (cov > 0.0) & ~full
    alpha[full] = 255
    alpha[partial] = np.maximum(alpha[partial], 1)
    return alpha.astype(np.uint8, copy=False)


def _reference_contour(
    columns: list[float], width: int, height: int, ss: int, taps: int, center_line: bool
) -> NDArray[np.uint8]:
    # Frozen complete coverage expression, sharing only unchanged PCHIP/metrics.
    out_w = width if taps > 1 and ss == 1 else width * ss
    center, max_half, _margin, cap = _mirrored_metrics(
        height=height, amplitude=0.82, glow_sigma=16.0, vertical_margin=1, content_height=280
    )
    alpha = np.zeros((max(height, 0), max(out_w, 0)), dtype=np.uint8)
    if not columns or out_w < 1 or height < 1:
        return alpha
    knots = [min(max(float(value), 0.0), 1.0) for value in columns]
    slopes = pchip_slopes(knots)
    yy = np.arange(height, dtype=np.float64)[:, np.newaxis]
    if taps > 1 and ss == 1:
        offsets = np.arange(taps, dtype=np.float64) / float(taps)
        xs = np.arange(out_w, dtype=np.float64)[:, np.newaxis] + offsets[np.newaxis, :]
        mags = pchip_eval_many(knots, slopes, xs.ravel(), unit=True).reshape(out_w, taps)
        halfs = np.minimum(float(max_half) * mags, cap)[np.newaxis, :, :]
        y0 = np.where(halfs > 0.0, float(center) - halfs, 0.0)
        y1 = np.where(halfs > 0.0, float(center) + halfs + 1.0, 0.0)
        yy3 = yy[:, :, np.newaxis]
        cov = np.clip(np.minimum(yy3 + 1.0, y1) - np.maximum(yy3, y0), 0.0, 1.0).mean(axis=2)
    else:
        xs = np.arange(out_w, dtype=np.float64) / float(ss)
        mags = pchip_eval_many(knots, slopes, xs, unit=True)
        halfs = np.minimum(float(max_half) * mags, cap)
        y0 = np.where(halfs > 0.0, float(center) - halfs, 0.0)
        y1 = np.where(halfs > 0.0, float(center) + halfs + 1.0, 0.0)
        cov = np.clip(np.minimum(yy + 1.0, y1) - np.maximum(yy, y0), 0.0, 1.0)
    alpha = _reference_alpha(cov)
    if center_line:
        y = min(height - 1, max(0, center))
        empty = alpha[y] == 0
        alpha[y, empty] = 140
    return alpha


@pytest.mark.parametrize("width,height", [(0, 0), (1, 1), (17, 23), (65, 32), (1500, 380)])
@pytest.mark.parametrize("ss,taps", [(1, 1), (2, 1), (4, 1), (1, 4), (2, 4)])
@pytest.mark.parametrize("center_line", [False, True])
@pytest.mark.parametrize("shape", ["empty", "silence", "detail"])
def test_contour_exact_frozen_arithmetic(
    width: int, height: int, ss: int, taps: int, center_line: bool, shape: str
) -> None:
    columns = [] if shape == "empty" else [0.0] * width
    if shape == "detail":
        pattern = [-0.1, 0.0, 1e-10, 0.03, 0.81, 1.0, 1.5, 0.33, 0.0]
        columns = [pattern[index % len(pattern)] for index in range(width)]
    before = columns.copy()
    expected = _reference_contour(columns, width, height, ss, taps, center_line)
    kwargs: dict[str, Any] = dict(
        width=width,
        height=height,
        amplitude=0.82,
        center_line=center_line,
        content_height=280,
        supersample=ss,
        glow_sigma=16.0,
        aa_taps=taps,
    )
    actual = mirrored_contour_alpha(columns, **kwargs)
    np.testing.assert_array_equal(actual, expected)
    assert draw_spectrum_alpha(columns, **kwargs) == expected.tobytes()
    rgba = np.zeros((*expected.shape, 4), dtype=np.uint8)
    rgba[expected > 0, :3] = (199, 230, 236)
    rgba[..., 3] = expected
    assert draw_spectrum_frame(columns, color="#C7E6EC", **kwargs) == rgba.tobytes()
    assert columns == before
    # Public results own their data; a later frame cannot overwrite the first.
    saved = actual.tobytes()
    mirrored_contour_alpha([1.0], **kwargs)
    assert actual.tobytes() == saved


def test_alpha_rounding_full_partial_and_minimum_code_exact() -> None:
    cutoff = 1.0 - 1e-6
    values = np.array(
        [
            -0.1,
            -0.0,
            0.0,
            np.nextafter(0.0, 1.0),
            0.5 / 255.0,
            1.5 / 255.0,
            2.5 / 255.0,
            np.nextafter(cutoff, 0.0),
            cutoff,
            np.nextafter(cutoff, 1.0),
            1.0,
            1.1,
        ],
        dtype=np.float64,
    )
    np.testing.assert_array_equal(_coverage_to_alpha(values.copy()), _reference_alpha(values))
