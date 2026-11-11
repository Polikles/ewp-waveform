"""Content-level appearance protection, not merely alpha-capable metadata."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from ewp_waveform.application import render as pipeline
from ewp_waveform.application.service import render
from ewp_waveform.identity import sha256_file
from tests.integration.test_render import _job_status
from tests.integration.test_ribbon_controls import _preset
from tests.integration.test_ribbon_fixed_profile_render import (
    _output,
    _png_rgba,
    _source,
)
from tests.render_oracles import assert_prores_contract, decoded_prores_frames

type Pixels = NDArray[np.uint8]


def _assert_silence(frame: Pixels, *, codec_tolerance: int = 0) -> None:
    alpha = frame[..., 3]
    assert not alpha[:80].any() and not alpha[81:].any(), "broad silence band"
    expected = np.zeros(160, dtype=np.uint8)
    expected[3:157] = 112
    expected[4:156] = 140
    assert np.max(np.abs(alpha[80].astype(int) - expected.astype(int))) <= codec_tolerance, (
        "wrong horizon coverage"
    )


def _assert_reflection(frame: Pixels) -> None:
    alpha = frame[..., 3]
    upper = alpha[79:0:-1]
    lower = alpha[81:]
    # Restrict the oracle to the opaque upper core, away from the shared seam.
    core = upper == 255
    core[:3] = False
    assert np.count_nonzero(core) > 10, "fixture must excite an actual body"
    assert np.all(np.abs(lower[core].astype(int) - 255 * 0.45) <= 2), "opaque lower body"


@pytest.mark.parametrize("mode", ["dark-background", "light-background"])
def test_real_pool_preserves_finished_reflection_horizon_and_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source = tmp_path / "s0e00-Appearance.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    # Only this test lowers admission; the production 1800-frame threshold stays unchanged.
    monkeypatch.setattr(pipeline, "_FIELD_POOL_MIN_FRAMES", 1)
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)),
        performance_name="balanced",
        formats=["png", "prores4444"],
        detail_level="balanced",
        glow_level="high",
        amplitude=0.82,
        stroke_width=1.0,
        reflection_opacity=0.45,
        center_line=True,
        center_line_extent=0.96,
        center_line_opacity=0.55,
        visual_noise=0.35,
        idle_activity=0.0,
        noise_rate=0.8,
        noise_seed=1729,
        background_mode=mode,
        color_mode="auto",
    )
    canonical: list[Pixels] = []
    decoded: list[Pixels] = []
    contexts = []
    for workers in (1, 2):
        monkeypatch.setattr(pipeline, "_job_workers", lambda performance, n=workers: n)
        payload = render(source, output_dir=tmp_path / f"jobs{workers}", **common)[0]
        assert _job_status(payload) == "SUCCEEDED"
        analysis = payload["analysis"]
        assert isinstance(analysis, dict) and analysis["encode_workers"] == workers
        contexts.append((payload["normalization"], analysis["fmin_hz"], analysis["fmax_hz"]))
        mov = _output(payload, "mov")
        assert_prores_contract(mov, width=160, height=160, fps=10, frame_count=8)
        png = np.frombuffer(_png_rgba(_output(payload, "png")), np.uint8).reshape(8, 160, 160, 4)
        rgba = np.frombuffer(
            b"".join(decoded_prores_frames(mov, width=160, height=160)), np.uint8
        ).reshape(8, 160, 160, 4)
        canonical.append(png)
        decoded.append(rgba)
        _assert_silence(png[0])
        _assert_silence(rgba[0], codec_tolerance=1)
        _assert_reflection(png[4])
        _assert_reflection(rgba[4])
        assert np.any(png[..., 3] == 0), "background alpha alone is insufficient"
        rgb = (199, 230, 236) if mode == "dark-background" else (47, 71, 79)
        assert np.all(png[png[..., 3] > 0, :3] == rgb), "canonical color is straight alpha"
        assert np.max(np.abs(png[..., 3].astype(int) - rgba[..., 3].astype(int))) <= 1
    # Same audio interval/span/normalization, including the pool boundary at frame4.
    assert contexts[0] == contexts[1]
    np.testing.assert_array_equal(canonical[0], canonical[1])
    np.testing.assert_array_equal(decoded[0], decoded[1])
    assert (sha256_file(source), source.stat().st_mtime_ns) == before


@pytest.mark.parametrize("defect", ["missing", "extent", "opacity", "broad-band"])
def test_silence_oracle_rejects_wrong_appearance_with_valid_background_alpha(defect: str) -> None:
    frame = np.zeros((160, 160, 4), dtype=np.uint8)
    frame[80, 3:157, 3] = 112
    frame[80, 4:156, 3] = 140
    _assert_silence(frame)
    if defect == "missing":
        frame[..., 3] = 0
    elif defect == "extent":
        frame[80, :, 3] = 140
    elif defect == "opacity":
        frame[80, 4:156, 3] = 255
    else:
        frame[72:89, 4:156, 3] = 140
    assert frame[0, 0, 3] == 0
    with pytest.raises(AssertionError):
        _assert_silence(frame)


def test_reflection_oracle_rejects_opaque_lower_with_valid_background_alpha() -> None:
    frame = np.zeros((160, 160, 4), dtype=np.uint8)
    frame[65:77, 20:140, 3] = 255
    frame[84:96, 20:140, 3] = 115
    _assert_reflection(frame)
    frame[84:96, 20:140, 3] = 255
    assert frame[0, 0, 3] == 0
    with pytest.raises(AssertionError, match="opaque lower"):
        _assert_reflection(frame)
