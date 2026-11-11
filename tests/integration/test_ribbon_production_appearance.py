"""Content-level appearance protection, not merely alpha-capable metadata."""
from __future__ import annotations

from collections.abc import Sequence
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


def _assert_body_and_halo(frame: Pixels, body: NDArray[np.float64]) -> None:
    alpha = frame[..., 3]
    upper_core = body[:80] == 255
    assert upper_core.any() and np.all(alpha[:80][upper_core] == 255)
    # An actual high-glow halo must survive outside the pre-finishing body mask.
    halo = (body == 0) & (alpha > 2)
    halo[77:84] = False  # Exclude the independent horizon/shared seam.
    assert np.count_nonzero(halo) > 10, "missing intended halo"
    assert np.all(alpha[halo] < 255), "halo became opaque fill"
    upper, lower = alpha[79:0:-1], alpha[81:]
    paired = (body[79:0:-1] == 0) & (body[81:] == 0) & (upper > 8)
    paired[:3] = False
    assert np.count_nonzero(paired) > 10
    assert np.max(np.abs(lower[paired].astype(float) - upper[paired] * 0.45)) <= 3


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
    raw_masks: list[bytes] = []
    raster = pipeline.raster_field_columns

    def capture(columns: Sequence[float], **kwargs: Any) -> bytes:
        mask = raster(columns, **kwargs)
        raw_masks.append(mask)
        return mask

    monkeypatch.setattr(pipeline, "raster_field_columns", capture)
    body: NDArray[np.float64] | None = None
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
        if workers == 1:
            assert len(raw_masks) == 8 and not any(raw_masks[0])
            pad = pipeline.glow_overscan(16)
            padded = 160 + 2 * pad
            raw = np.frombuffer(raw_masks[4], np.uint8).reshape(padded, padded, 2)
            body = raw.mean(axis=2)[pad : pad + 160, pad : pad + 160]
        assert body is not None
        _assert_body_and_halo(png[4], body)
        _assert_body_and_halo(rgba[4], body)
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



def test_silent_thick_saved_stroke_line_off_has_no_hidden_core_in_either_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "s0e00-Silent.wav"
    _source(source, silent=True)
    saved = _preset(tmp_path)
    saved.write_text(
        saved.read_text()
        .replace("stroke_width = 1.0", "stroke_width = 12.0")
        .replace("center_line = true", "center_line = false")
    )
    preset = str(saved)
    monkeypatch.setattr(pipeline, "_FIELD_POOL_MIN_FRAMES", 1)
    pixels = []
    for workers in (1, 2):
        monkeypatch.setattr(pipeline, "_job_workers", lambda performance, n=workers: n)
        payload = render(
            source,
            preset_name=preset,
            performance_name="balanced",
            formats=["png", "prores4444"],
            glow_level="high",
            visual_noise=0.35,
            idle_activity=0,
            output_dir=tmp_path / f"jobs{workers}",
        )[0]
        assert _job_status(payload) == "SUCCEEDED"
        png = np.frombuffer(_png_rgba(_output(payload, "png")), np.uint8)
        rgba = b"".join(decoded_prores_frames(_output(payload, "mov"), width=160, height=160))
        assert not png.any() and not any(rgba)
        pixels.append(rgba)
    assert pixels[0] == pixels[1]
