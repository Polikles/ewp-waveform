from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ewp_waveform.ffmpeg.experiments import frame_metrics


@pytest.mark.parametrize("kind", ["transparent", "opaque", "all-codes", "random"])
def test_equal_byte_metrics_keep_scalar_denominators_without_composites(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    width, height = 32, 16
    values = np.random.default_rng(1729).integers(0, 256, (height, width, 4), dtype=np.uint8)
    if kind in ("transparent", "opaque"):
        values[..., 3] = 0 if kind == "transparent" else 255
    if kind == "all-codes":
        values[..., 3] = np.arange(width * height, dtype=np.uint16).reshape(height, width) % 256
    alpha = list(values[..., 3].flat)
    expected = {
        "union_count": sum(a > 0 for a in alpha),
        "alpha_error": 0,
        "rgb_error": 0,
        "edge_error": 0,
        "edge_n": sum(0 < a < 255 for a in alpha),
        "halo_error": 0,
        "halo_n": sum(0 < a < 32 for a in alpha),
        "081018": 0,
        "F0F0F0": 0,
        "checkerboard": 0,
    }

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("equal streams must not allocate a redundant checker/composite")

    monkeypatch.setattr(np, "indices", forbidden)
    assert frame_metrics(values.tobytes(), values.tobytes(), width, height) == expected
