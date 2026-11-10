from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.service import AppError, plan_jobs, render
from ewp_waveform.identity import sha256_file
from tests.integration.test_render import NO_CHUNKS, _job_status, _write
from tests.integration.test_ribbon_controls import _preset
from tests.integration.test_ribbon_fixed_profile_render import (
    _output,
    _png_rgba,
    _recipe,
    _signature,
    _source,
)
from tests.render_oracles import assert_prores_contract, decoded_prores_frames


@pytest.mark.parametrize("mode", ["dark-background", "light-background"])
def test_modes_keep_production_mov_alpha_and_canonical_png(tmp_path: Path, mode: str) -> None:
    source = tmp_path / "s0e00-Alpha.wav"
    _source(source)
    payload = render(
        source,
        preset_name=str(_preset(tmp_path)),
        performance_name=str(_write(tmp_path / "single.toml", NO_CHUNKS)),
        formats=["png", "prores4444"],
        start=0.2,
        duration=0.3,
        background_mode=mode,
        output_dir=tmp_path / "out",
    )[0]
    assert _job_status(payload) == "SUCCEEDED"
    mov = _output(payload, "mov")
    assert_prores_contract(mov, width=160, height=160, fps=10, frame_count=3)
    rgba = np.frombuffer(
        b"".join(decoded_prores_frames(mov, width=160, height=160)), np.uint8
    ).reshape(3, 160, 160, 4)
    png = np.frombuffer(_png_rgba(_output(payload, "png")), np.uint8).reshape(3, 160, 160, 4)
    assert np.any(rgba[..., 3] == 0) and np.any(rgba[..., 3] > 0)
    assert np.max(np.abs(rgba[..., 3].astype(int) - png[..., 3].astype(int))) <= 1


@pytest.mark.parametrize("path", ["mask_fast", "rgba_2d"])
def test_public_modes_color_alpha_metadata_reuse_and_input_immutability(
    tmp_path: Path, path: str
) -> None:
    source = tmp_path / "s0e00-Background.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)),
        performance_name=str(_write(tmp_path / "single.toml", NO_CHUNKS)),
        formats=["png"],
        start=0.2,
        duration=0.3,
        visual_noise=0.35,
        noise_seed=1729,
        stroke_width=2.5,
        reflection_opacity=0.45,
        center_line_extent=0.65,
        center_line_opacity=0.55,
    )
    pixels: dict[str, np.ndarray] = {}
    signatures = set()
    for mode, color, options in [
        ("dark-background", "#C7E6EC", {}),
        ("light-background", "#2F474F", {}),
        (
            "custom",
            "#C7E6EC",
            {"background_mode": "light-background", "waveform_color": "pale_cyan"},
        ),
    ]:
        opts: dict[str, Any] = {"background_mode": mode, **options}
        _, effective, _, plans, _ = plan_jobs(source, **common, **opts, output_dir=tmp_path / mode)
        assert not (tmp_path / mode).exists()
        assert effective.waveform.color == color
        payload = render(source, render_path=path, **common, **opts, output_dir=tmp_path / mode)[0]
        assert _job_status(payload) == "SUCCEEDED"
        assert _signature(payload) == plans[0].render_signature
        signatures.add(_signature(payload))
        recipe = _recipe(payload)
        assert recipe["background_mode"] == opts["background_mode"]
        assert recipe["color_mode"] == ("custom" if mode == "custom" else "auto")
        assert recipe["foreground_color"] == color
        resolved = payload["resolved_visual_config"]
        assert isinstance(resolved, dict)
        assert resolved["effective_preset"] == effective.model_dump(mode="json")
        pixels[mode] = np.frombuffer(_png_rgba(_output(payload, "png")), np.uint8).reshape(
            3, 160, 160, 4
        )
        again = render(source, render_path=path, **common, **opts, output_dir=tmp_path / mode)[0]
        assert _job_status(again) == "SKIPPED" and _signature(again) == _signature(payload)
        assert _recipe(again) == recipe
    assert len(signatures) == 3
    np.testing.assert_array_equal(pixels["dark-background"], pixels["custom"])
    np.testing.assert_array_equal(
        pixels["dark-background"][..., 3], pixels["light-background"][..., 3]
    )
    for mode, rgb in [("dark-background", [199, 230, 236]), ("light-background", [47, 71, 79])]:
        rgba = pixels[mode]
        assert np.any(rgba[..., 3] == 0) and np.any((rgba[..., 3] > 0) & (rgba[..., 3] < 255))
        assert np.all(rgba[rgba[..., 3] > 0, :3] == rgb)
        assert np.all(rgba[rgba[..., 3] == 0, :3] == 0)
    assert (sha256_file(source), source.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "options",
    [
        {"background_mode": "bad"},
        {"color_mode": "bad"},
        {"waveform_color": "pale_cyan", "color_mode": "auto"},
    ],
)
def test_invalid_modes_fail_before_any_output(tmp_path: Path, options: dict[str, Any]) -> None:
    source = tmp_path / "s0e00-Invalid.wav"
    _source(source)
    for op in (plan_jobs, render):
        with pytest.raises(AppError):
            op(source, preset_name=str(_preset(tmp_path)), output_dir=tmp_path / "out", **options)
        assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("name", ["iuris-default", "iuris-moving-mouth", "iuris-ribbon-fixed"])
def test_new_modes_on_unsupported_profiles_fail_in_both_services(tmp_path: Path, name: str) -> None:
    source = tmp_path / "s0e00-Unsupported.wav"
    _source(source)
    for op in (plan_jobs, render):
        with pytest.raises(AppError, match="require"):
            op(
                source,
                preset_name=name,
                background_mode="dark-background",
                output_dir=tmp_path / "out",
            )
        assert not (tmp_path / "out").exists()
