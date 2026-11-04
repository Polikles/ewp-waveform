from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application.render import render_job
from ewp_waveform.application.results import result_payload_errors
from ewp_waveform.application.service import plan_jobs, render
from ewp_waveform.config.load import load_preset
from ewp_waveform.ffmpeg.encode import EncodeError
from ewp_waveform.identity import render_signature, sha256_file
from tests.integration.test_render import (
    TINY_SPECTRUM,
    _first_output,
    _job_status,
    _tone_wav,
    _write,
)
from tests.render_oracles import assert_png_sequences_equal, png_frames


def _signature(payload: dict[str, object]) -> str:
    job = payload["job"]
    assert isinstance(job, dict)
    signature = job["render_signature"]
    assert isinstance(signature, str)
    return signature


def _recipe(payload: dict[str, object]) -> dict[str, Any]:
    config = payload["resolved_visual_config"]
    assert isinstance(config, dict)
    recipe = config["fixed_axis_recipe"]
    assert isinstance(recipe, dict)
    return recipe


@pytest.mark.parametrize(
    "appearance",
    [
        {"spectrum_contour": True},
        {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
    ],
    ids=["contour", "field-bars"],
)
def test_changed_appearance_does_not_skip_prior_output(
    tmp_path: Path, appearance: dict[str, Any]
) -> None:
    src = tmp_path / "s0e00-Identity.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    before = sha256_file(src)
    preset = _write(tmp_path / "spectrum.toml", TINY_SPECTRUM)
    common: dict[str, Any] = {
        "formats": ["png"],
        "preset_name": str(preset),
        "output_dir": tmp_path / "out",
    }
    original = render(src, **common)[0]
    original_frames = [p.read_bytes() for p in png_frames(_first_output(original))]
    changed = render(src, **common, **appearance)[0]
    assert _job_status(original) == "SUCCEEDED"
    assert _job_status(changed) == "SUCCEEDED", "changed appearance reused the old look"
    assert _signature(original) != _signature(changed)
    assert _first_output(original) != _first_output(changed)
    assert original_frames == [p.read_bytes() for p in png_frames(_first_output(original))]
    assert original_frames != [p.read_bytes() for p in png_frames(_first_output(changed))]
    repeated = render(src, **common, **appearance)[0]
    assert _job_status(repeated) == "SKIPPED"
    assert _signature(changed) == _signature(repeated)
    assert _recipe(changed) == _recipe(repeated)
    fresh = render(src, **{**common, "output_dir": tmp_path / "fresh"}, **appearance)[0]
    assert _job_status(fresh) == "SUCCEEDED"
    assert_png_sequences_equal(_first_output(changed), _first_output(fresh))
    for payload in (original, changed, repeated, fresh):
        assert result_payload_errors(payload) == []
    assert sha256_file(src) == before


def test_old_frequency_destination_is_not_reused(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Migration.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    preset_path = _write(tmp_path / "spectrum.toml", TINY_SPECTRUM)
    preset = load_preset(str(preset_path))
    common: dict[str, Any] = {
        "formats": ["png"],
        "preset_name": str(preset_path),
        "output_dir": tmp_path / "out",
    }
    _, _, _, plans, _ = plan_jobs(src, **common)
    current = render(src, **common)[0]
    assert plans[0].render_signature == _signature(current)
    old_signature = render_signature(source_sha256=sha256_file(src), preset=preset, fps=10.0)
    assert old_signature != _signature(current)
    current_path = _first_output(current)
    old_path = current_path.with_name(
        current_path.name.replace(_signature(current)[:12], old_signature[:12])
    )
    current_path.rename(old_path)
    repeated = render(src, **common)[0]
    assert _job_status(repeated) == "SUCCEEDED"
    assert old_path.is_dir()
    assert_png_sequences_equal(old_path, _first_output(repeated))


@pytest.mark.parametrize("glow", ["none", "low"])
def test_physical_representation_paths_preserve_identity_and_output(
    tmp_path: Path, glow: str
) -> None:
    src = tmp_path / "s0e00-Paths.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    preset = _write(tmp_path / "spectrum.toml", TINY_SPECTRUM)
    common: dict[str, Any] = {
        "formats": ["png"],
        "preset_name": str(preset),
        "spectrum_layout": "field_center_out",
        "bar_alternate": False,
        "render_aa": "physical_ss",
        "glow_level": glow,
    }
    mask = render(src, **common, output_dir=tmp_path / "mask", render_path="mask_fast")[0]
    rgba = render(src, **common, output_dir=tmp_path / "rgba", render_path="rgba_2d")[0]
    assert _job_status(mask) == _job_status(rgba) == "SUCCEEDED"
    assert _signature(mask) == _signature(rgba)
    assert _recipe(mask) == _recipe(rgba)
    assert_png_sequences_equal(_first_output(mask), _first_output(rgba))


def test_failure_result_keeps_hashed_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "s0e00-Failure.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    preset_path = _write(tmp_path / "spectrum.toml", TINY_SPECTRUM)
    _, preset, performance, plans, _ = plan_jobs(src, preset_name=str(preset_path), formats=["png"])
    plan = plans[0]
    assert plan.media is not None

    def fail(*args: Any, **kwargs: Any) -> None:
        raise EncodeError("bounded injected encoder failure")

    monkeypatch.setattr("ewp_waveform.application.render.encode_rgba_stream", fail)
    failed = render_job(
        plan.job,
        plan.media,
        preset,
        performance,
        output_dir=tmp_path / "failed",
        formats=["png"],
        force=False,
    )
    assert _job_status(failed) == "FAILED"
    assert _signature(failed) == plan.render_signature
    assert _recipe(failed)["version"] == 1
    assert result_payload_errors(failed) == []
