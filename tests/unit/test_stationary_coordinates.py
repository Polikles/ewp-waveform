"""Fixed-axis coordinate vectorization preserves scalar division order exactly."""

from __future__ import annotations

import numpy as np
import pytest

from ewp_waveform.analysis import spectrum
from ewp_waveform.analysis.interp import pchip_eval_many, pchip_slopes


@pytest.mark.parametrize("width", [0, 1, 2, 3, 31, 127, 1400, 1500, 3000])
@pytest.mark.parametrize("n", [0, 1, 2, 21, 64, 129])
def test_stationary_scalar_oracle(width: int, n: int) -> None:
    rng = np.random.default_rng(1729 + n)
    bands = rng.uniform(-0.2, 1.5, n).tolist()
    before = bands.copy()
    if width < 1:
        expected = []
    elif n == 0:
        expected = [0.0] * width
    elif n == 1:
        expected = [max(0.0, bands[0])] * width
    else:
        knots = [max(0.0, float(v)) for v in bands]
        denom = max(width - 1, 1)
        xs = [spectrum.remap_band_index(x / denom, n_bands=n, pivot=None) for x in range(width)]
        expected = pchip_eval_many(knots, pchip_slopes(knots), xs, unit=False).tolist()
    assert spectrum.upsample_bands(bands, width) == expected
    assert bands == before


@pytest.mark.parametrize("pivot", [None, 0.0, 0.23, 1.0, 17.5, 128.0])
def test_complete_coordinate_bytes_and_dynamic_pivot(
    pivot: float | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = pchip_eval_many

    def checked(values, slopes, xs, *, unit=True):  # type: ignore[no-untyped-def]
        expected = [
            spectrum.remap_band_index(x / 1499, n_bands=129, pivot=pivot) for x in range(1500)
        ]
        assert (
            np.asarray(xs, dtype=np.float64).tobytes()
            == np.asarray(expected, dtype=np.float64).tobytes()
        )
        return real(values, slopes, xs, unit=unit)

    monkeypatch.setattr(spectrum, "pchip_eval_many", checked)
    spectrum.upsample_bands([0.0, 0.2, 1.0] * 43, 1500, pivot=pivot)
