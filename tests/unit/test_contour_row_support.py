"""Exact row-support optimization against an independent frozen full-grid oracle."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from ewp_waveform.analysis.interp import pchip_eval_many, pchip_slopes
from ewp_waveform.config.models import CanvasSection, VisualPreset, WaveformSection
from ewp_waveform.ffmpeg import draw
from ewp_waveform.visual import segmented
from ewp_waveform.visual.plan import AAMode, RenderPath, resolve_render_plan
from ewp_waveform.visual.raster import raster_field_columns
from ewp_waveform.visual.style_defaults import default_bar_style


def _frozen_full_grid(
    columns: list[Any],
    *,
    width: int,
    height: int,
    amplitude: float,
    center_line: bool,
    content_height: int | None = None,
    supersample: int = 1,
    glow_sigma: float = 0.0,
    vertical_margin: int = 1,
    aa_taps: int = 1,
) -> NDArray[np.uint8]:
    # Frozen dffa2735 full-grid expressions: never call row/coverage/alpha helpers.
    # PCHIP and metrics are unchanged dependencies, not the subject of this oracle.
    ss = max(1, int(supersample))
    taps = max(1, int(aa_taps))
    out_w = width if taps > 1 and ss == 1 else width * ss
    center, max_half, _margin, cap = draw._mirrored_metrics(
        height=height,
        amplitude=amplitude,
        glow_sigma=glow_sigma,
        vertical_margin=vertical_margin,
        content_height=content_height,
    )
    if not columns or out_w < 1 or height < 1:
        return np.zeros((max(height, 0), max(out_w, 0)), dtype=np.uint8)
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
    alpha = np.rint(255.0 * cov).astype(np.int16)
    np.clip(alpha, 0, 255, out=alpha)
    full = cov >= (1.0 - 1e-6)
    partial = (cov > 0.0) & ~full
    alpha[full] = 255
    alpha[partial] = np.maximum(alpha[partial], 1)
    result: NDArray[np.uint8] = alpha.astype(np.uint8, copy=False)
    if center_line:
        y = min(height - 1, max(0, center))
        empty = result[y] == 0
        result[y, empty] = 140
    return result


def _assert_exact(columns: list[Any], kwargs: dict[str, Any]) -> None:
    with np.errstate(all="ignore"):
        expected = _frozen_full_grid(columns, **kwargs)
        actual = draw.mirrored_contour_alpha(columns, **kwargs)
        np.testing.assert_array_equal(actual, expected)
        assert actual.dtype == np.uint8
        assert actual.flags.owndata and actual.flags.c_contiguous
        assert draw.draw_spectrum_alpha(columns, **kwargs) == expected.tobytes()
        rgba = np.zeros((*expected.shape, 4), dtype=np.uint8)
        rgba[expected > 0, :3] = (199, 230, 236)
        rgba[..., 3] = expected
        assert draw.draw_spectrum_frame(columns, color="#C7E6EC", **kwargs) == rgba.tobytes()
        saved = actual.tobytes()
        other = draw.mirrored_contour_alpha([1.0], **kwargs)
        other.fill(13)
        assert actual.tobytes() == saved


@pytest.mark.parametrize("ss,taps", [(1, 1), (2, 1), (3, 1), (1, 2), (1, 3), (1, 7), (2, 5)])
@pytest.mark.parametrize("seed", [17, 93, 211])
def test_random_contours_match_frozen_full_grid(seed: int, ss: int, taps: int) -> None:
    rng = np.random.default_rng(seed)
    for case in range(16):
        columns = rng.uniform(-0.2, 1.2, size=int(rng.integers(1, 24))).tolist()
        columns[::3] = [0.0] * len(columns[::3])
        before = columns.copy()
        kwargs: dict[str, Any] = dict(
            width=int(rng.integers(1, 24)),
            height=int(rng.integers(1, 67)),
            amplitude=float(rng.choice([0.0, 0.02, 0.82, 1.0, 1.4])),
            center_line=bool(case % 2),
            content_height=rng.choice([None, 1, 9, 28]),
            supersample=ss,
            aa_taps=taps,
            glow_sigma=float(rng.choice([0.0, 0.5, 4.0, 16.0])),
            vertical_margin=int(rng.integers(-2, 6)),
        )
        _assert_exact(columns, kwargs)
        assert columns == before


@pytest.mark.parametrize("ss,taps", [(1, 1), (2, 1), (1, 5)])
@pytest.mark.parametrize("center_line", [False, True])
@pytest.mark.parametrize(
    "columns",
    [
        [],
        [0.0],
        [1e-300, 0.0, 1e-100],
        [1.0, 0.0, 0.5],
        [float("nan")],
        [0.0, float("nan"), 0.3, 1.0],
        [float("-inf"), 0.5, float("inf")],
        [Decimal("0.125"), Fraction(1, 3), np.float32(0.8)],
    ],
)
def test_empty_tiny_nonfinite_and_exotic_columns(
    columns: list[Any], ss: int, taps: int, center_line: bool
) -> None:
    for height in [-1, 0, 1, 2, 3, 8]:
        _assert_exact(
            columns,
            dict(
                width=7,
                height=height,
                amplitude=0.82,
                center_line=center_line,
                content_height=280,
                supersample=ss,
                aa_taps=taps,
                glow_sigma=16.0,
            ),
        )


@pytest.mark.parametrize("amplitude", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("glow_sigma", [0.0, 16.0])
def test_nonfinite_amplitude_matches_success_or_exception(
    amplitude: float, glow_sigma: float
) -> None:
    kwargs: dict[str, Any] = dict(
        width=7, height=17, amplitude=amplitude, center_line=True, glow_sigma=glow_sigma
    )
    try:
        _frozen_full_grid([0.0, 1.0], **kwargs)
    except Exception as error:
        with pytest.raises(type(error), match=str(error)):
            draw.mirrored_contour_alpha([0.0, 1.0], **kwargs)
    else:
        _assert_exact([0.0, 1.0], kwargs)


@pytest.mark.parametrize("height", [True, np.int64(11)])
def test_exotic_height_uses_full_grid(height: int, monkeypatch: pytest.MonkeyPatch) -> None:
    real = draw._contour_coverage
    seen: list[int] = []

    def coverage(yy: np.ndarray, y0: np.ndarray, y1: np.ndarray) -> np.ndarray:
        seen.append(yy.shape[0])
        return real(yy, y0, y1)

    monkeypatch.setattr(draw, "_contour_coverage", coverage)
    kwargs: dict[str, Any] = dict(width=3, height=height, amplitude=0.1, center_line=True)
    _assert_exact([0.0, 0.1], kwargs)
    assert seen and all(rows == height for rows in seen)


def test_support_ignores_empty_reversed_and_offcanvas_intervals() -> None:
    y0 = np.array([0.0, -100.0, 19.25, 18.0, 1e300, -1e300])
    y1 = np.array([0.0, -101.0, 22.0, 20.125, 1e300, -1e300])
    assert draw._contour_row_support(y0, y1, 40) == (18, 22)
    assert draw._contour_row_support(np.array([50.0]), np.array([70.0]), 40) == (40, 40)
    assert draw._contour_row_support(np.array([-9.0]), np.array([-3.0]), 40) == (0, 0)
    for value in [float("nan"), float("inf"), float("-inf")]:
        assert draw._contour_row_support(np.array([value]), np.array([23.0]), 40) == (0, 40)
        assert draw._contour_row_support(np.array([19.0]), np.array([value]), 40) == (0, 40)


def test_support_excludes_only_provably_zero_rows() -> None:
    rng = np.random.default_rng(11262)
    height = 37
    yy = np.arange(height, dtype=np.float64)[:, None]
    for _ in range(100):
        y0 = rng.uniform(-20, 60, 9)
        y1 = rng.uniform(-20, 60, 9)
        start, stop = draw._contour_row_support(y0, y1, height)
        cov = np.clip(np.minimum(yy + 1.0, y1) - np.maximum(yy, y0), 0.0, 1.0)
        assert not cov[:start].any()
        assert not cov[stop:].any()


@pytest.mark.parametrize("ss,taps", [(2, 1), (1, 5)])
def test_padded_geometry_converts_only_149_active_rows(
    ss: int, taps: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Production vertical geometry, tiny width; no media/performance workload.
    real_coverage = draw._contour_coverage
    real_alpha = draw._coverage_to_alpha
    observed: list[tuple[int, int]] = []
    converted: list[int] = []

    def coverage(yy: np.ndarray, y0: np.ndarray, y1: np.ndarray) -> np.ndarray:
        observed.append((int(yy[0].flat[0]), int(yy[-1].flat[0])))
        return real_coverage(yy, y0, y1)

    def alpha(cov: np.ndarray) -> np.ndarray:
        converted.append(cov.shape[0])
        return real_alpha(cov)

    monkeypatch.setattr(draw, "_contour_coverage", coverage)
    monkeypatch.setattr(draw, "_coverage_to_alpha", alpha)
    _assert_exact(
        [0.0, 1.0, 0.0],
        dict(
            width=7,
            height=380,
            content_height=280,
            amplitude=0.82,
            glow_sigma=16.0,
            center_line=True,
            supersample=ss,
            aa_taps=taps,
        ),
    )
    assert observed and all(rows == (116, 264) for rows in observed)
    assert converted and all(rows == 149 for rows in converted)


@pytest.mark.parametrize("center_line", [False, True])
def test_silence_skips_all_float_coverage_and_conversion(
    center_line: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("silence must not rasterize or convert known-zero rows")

    monkeypatch.setattr(draw, "_contour_coverage", forbidden)
    monkeypatch.setattr(draw, "_coverage_to_alpha", forbidden)
    kwargs: dict[str, Any] = dict(width=9, height=31, amplitude=1.0, center_line=center_line)
    expected = _frozen_full_grid([0.0], **kwargs)
    actual = draw.mirrored_contour_alpha([0.0], **kwargs)
    np.testing.assert_array_equal(actual, expected)
    assert actual.flags.owndata


@pytest.mark.parametrize("aa_mode", ["physical_ss", "coverage_taps"])
@pytest.mark.parametrize("path", ["mask_fast", "rgba_2d"])
def test_all_styles_and_aa_paths_against_frozen_contour(
    aa_mode: AAMode, path: RenderPath, monkeypatch: pytest.MonkeyPatch
) -> None:
    preset = VisualPreset(
        schema_version=1,
        name="row-support-exact",
        canvas=CanvasSection(width=32, height=64, fps=60),
        waveform=WaveformSection(
            style="mirrored", domain="frequency", color="#C7E6EC", amplitude=0.82
        ),
        effects={"glow": {"enabled": False}, "particles": {"enabled": False}},
    )
    columns = [0.0, 0.01, 0.9, 0.2, 1.0, 0.0, 0.7] + [0.0] * 25
    for geometry in ["classic_ticks", "mirrored_bars", "ribbon", "segmented_impulse"]:
        style = default_bar_style(geometry)
        plan = resolve_render_plan(
            preset,
            layout="field_center_out",
            field_geometry=geometry,
            ribbon_supersample=3,
            alternate_bars=style.alternate,
            aa_mode=aa_mode,
            force_path=path,
        )
        kwargs: dict[str, Any] = dict(
            plan=plan,
            width=32,
            height=64,
            content_height=28,
            glow_sigma=1.0,
            amplitude=0.82,
            center_line=True,
            color="#C7E6EC",
            bar_style=style,
        )
        actual = raster_field_columns(columns, **kwargs)
        with monkeypatch.context() as frozen:
            frozen.setattr(draw, "mirrored_contour_alpha", _frozen_full_grid)
            frozen.setattr(segmented, "mirrored_contour_alpha", _frozen_full_grid)
            expected = raster_field_columns(columns, **kwargs)
        assert actual == expected, (geometry, aa_mode, path)
