from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from ewp_waveform.application import render as render_module
from ewp_waveform.application.service import AppError, plan_jobs, render
from ewp_waveform.cli import app
from ewp_waveform.identity import sha256_file
from ewp_waveform.paths import builtin_presets_dir
from tests.integration.test_render import NO_CHUNKS, _job_status, _write
from tests.integration.test_ribbon_fixed_profile_render import (
    _output,
    _png_rgba,
    _recipe,
    _signature,
    _source,
)
from tests.render_oracles import assert_png_sequences_equal


def _preset(tmp_path: Path) -> Path:
    text = (builtin_presets_dir() / "iuris-ribbon-refined.toml").read_text()
    text = (
        text.replace("width = 1400", "width = 160")
        .replace("height = 280", "height = 160")
        .replace("fps = 60", "fps = 10")
    )
    return _write(tmp_path / "refined.toml", text)


def test_public_overrides_plan_render_identity_reuse_and_source_immutability(
    tmp_path: Path,
) -> None:
    source = tmp_path / "s0e00-Controls.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)),
        performance_name=str(_write(tmp_path / "single.toml", NO_CHUNKS)),
        formats=["png"],
        output_dir=tmp_path / "out",
        start=0.2,
        duration=0.4,
    )
    options: dict[str, Any] = dict(
        detail_level="detailed",
        waveform_color="steel_blue",
        glow_level="none",
        amplitude=0.4,
        stroke_width=5,
    )
    _, effective, _, plans, _ = plan_jobs(source, **common, **options)
    assert not (tmp_path / "out").exists()
    assert effective.waveform.color == "#3D5D73"
    assert effective.waveform.amplitude == 0.4 and effective.waveform.stroke_width == 5
    assert effective.signal["detail_level"] == "detailed"
    payload = render(source, **common, **options)[0]
    assert _job_status(payload) == "SUCCEEDED"
    assert plans[0].render_signature == _signature(payload)
    assert _recipe(payload)["detail_level"] == "detailed"
    resolved = payload["resolved_visual_config"]
    assert isinstance(resolved, dict)
    assert resolved["color"] == "#3D5D73"
    assert resolved["effective_preset"]["waveform"]["amplitude"] == 0.4
    assert resolved["effective_preset"]["waveform"]["stroke_width"] == 5
    assert resolved["glow"]["level"] == "none"
    assert resolved["effective_preset"] == effective.model_dump(mode="json")
    again = render(source, **common, **options)[0]
    assert _job_status(again) == "SKIPPED" and _signature(again) == _signature(payload)
    changed = plan_jobs(source, **common, **{**options, "stroke_width": 6})[3][0]
    assert changed.render_signature != _signature(payload) and changed.action == "PROCESS"
    assert (sha256_file(source), source.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "options",
    [
        {"detail_level": "ultra"},
        {"glow_level": "huge"},
        {"waveform_color": "yellow"},
        {"amplitude": 2},
        {"stroke_width": 0},
    ],
)
def test_invalid_service_values_fail_before_output_creation(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    source = tmp_path / "s0e00-Invalid.wav"
    _source(source)
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)), output_dir=tmp_path / "out", **options
    )
    for operation in (plan_jobs, render):
        with pytest.raises(AppError):
            operation(source, **common)
        assert not (tmp_path / "out").exists()


def test_control_effects_change_actual_pixels_without_changing_unrelated_settings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "s0e00-Effects.wav"
    _source(source)
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)),
        performance_name=str(_write(tmp_path / "single.toml", NO_CHUNKS)),
        formats=["png"],
        start=0.2,
        duration=0.3,
    )
    cells: list[tuple[str, dict[str, Any]]] = [
        ("base", {}),
        ("smooth", {"detail_level": "smooth"}),
        ("detailed", {"detail_level": "detailed"}),
        ("color", {"waveform_color": "soft_yellow"}),
        ("glow", {"glow_level": "none"}),
        ("height", {"amplitude": 0.25}),
        ("thickness", {"stroke_width": 10}),
    ]
    pixels: dict[str, np.ndarray] = {}
    signatures = set()
    for name, options in cells:
        payload = render(source, **common, **options, output_dir=tmp_path / name)[0]
        assert _job_status(payload) == "SUCCEEDED"
        pixels[name] = np.frombuffer(_png_rgba(_output(payload, "png")), dtype=np.uint8).reshape(
            3, 160, 160, 4
        )
        signatures.add(_signature(payload))
    assert len(signatures) == len(cells)
    for name, _ in cells[1:]:
        assert not np.array_equal(pixels["base"], pixels[name]), name
    for name in ("base", "smooth", "detailed"):
        alpha = pixels[name][..., 3]
        assert np.any(alpha == 0) and np.any(alpha > 0) and np.any((alpha > 0) & (alpha < 255))
    # Color affects RGB, not the alpha contour; height reduces strong-content area.
    assert np.array_equal(pixels["base"][..., 3], pixels["color"][..., 3])
    assert np.count_nonzero(pixels["height"][..., 3] > 128) < np.count_nonzero(
        pixels["base"][..., 3] > 128
    )


def test_refined_mask_rgba_and_worker_partition_exactness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "s0e00-Paths.wav"
    _source(source)
    single = _write(tmp_path / "single.toml", NO_CHUNKS)
    pooled = _write(tmp_path / "pool.toml", NO_CHUNKS.replace("jobs = 1", "jobs = 2"))
    common: dict[str, Any] = dict(
        preset_name=str(_preset(tmp_path)),
        formats=["png"],
        start=0.2,
        duration=0.4,
        detail_level="detailed",
        waveform_color="periwinkle_blue",
        stroke_width=7,
    )
    mask = render(
        source,
        **common,
        performance_name=str(single),
        output_dir=tmp_path / "mask",
        render_path="mask_fast",
    )[0]
    rgba = render(
        source,
        **common,
        performance_name=str(single),
        output_dir=tmp_path / "rgba",
        render_path="rgba_2d",
    )[0]
    monkeypatch.setattr(render_module, "_FIELD_POOL_MIN_FRAMES", 1)
    pool = render(source, **common, performance_name=str(pooled), output_dir=tmp_path / "pool")[0]
    assert _job_status(mask) == _job_status(rgba) == _job_status(pool) == "SUCCEEDED"
    assert _signature(mask) == _signature(rgba) == _signature(pool)
    assert_png_sequences_equal(_output(mask, "png"), _output(rgba, "png"))
    assert_png_sequences_equal(_output(mask, "png"), _output(pool, "png"), boundary_frames={2})


def test_cli_invalid_is_clear_config_error(tmp_path: Path) -> None:
    source = tmp_path / "s0e00-CLI.wav"
    _source(source)
    result = CliRunner().invoke(
        app,
        [
            "preview",
            str(source),
            "--preset",
            str(_preset(tmp_path)),
            "--detail-level",
            "ultra",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0 and "detail_level" in result.output
    assert not (tmp_path / "out").exists()
