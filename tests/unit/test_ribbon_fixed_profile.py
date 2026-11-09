from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import list_presets, load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.mapping import CenterOutMapping


def test_ribbon_profile_is_explicit_and_separates_visual_choices() -> None:
    assert "iuris-ribbon-fixed" in {name for name, _ in list_presets()}
    preset = load_preset("iuris-ribbon-fixed")
    assert preset.waveform.style == "filled"
    assert preset.waveform.domain == "frequency"
    assert preset.waveform.color == "#C7E6EC"
    assert preset.effects["glow"] == {"enabled": True, "level": "high", "color": "#C7E6EC"}
    appearance = resolve_fixed_axis_appearance(preset)
    assert appearance.layout == "field_center_out"
    assert appearance.n_bands == 64
    assert appearance.tilt_db == 3.0
    assert appearance.compress == 0.75
    assert appearance.spatial_filter == "gaussian"
    assert appearance.spatial_sigma > 0.0
    assert appearance.bars is not None and not appearance.bars.alternate
    plan = appearance.field_plan
    assert plan is not None
    assert (plan.path, plan.pix_fmt, plan.geometry) == ("mask_fast", "gray", "ribbon")
    assert plan.supersample == 2
    assert appearance.identity()["profile"] == "filled-ribbon-v1"


def test_existing_preset_and_legacy_recipe_are_unchanged() -> None:
    default = load_preset("iuris-default")
    assert (default.waveform.style, default.waveform.domain) == ("mirrored", "time")
    spectrum = load_preset("iuris-spectrum")
    assert "fixed_axis_profile" not in spectrum.signal
    assert resolve_fixed_axis_appearance(spectrum).identity() == {
        "version": 1,
        "visual_geometry": "spectrum",
        "layout": "linear",
        "n_bands": None,
        "spatial_sigma": 7.0,
        "spatial_filter": "box",
        "tilt_db_per_octave": 0.0,
        "compress": 1.0,
        "contour": False,
        "recenter": False,
        "edge_taper": 0.0,
        "slot_sigma": 0.0,
        "supersample": 2,
    }
    legacy = resolve_fixed_axis_appearance(spectrum, spectrum_layout="field_center_out")
    assert legacy.bars is not None and legacy.bars.alternate
    assert legacy.field_plan is not None and legacy.field_plan.path == "rgba_2d"
    assert "profile" not in legacy.identity()


@pytest.mark.parametrize("value", [None, "", "filled-ribon-v1", 1, True, {}])
def test_unknown_profile_does_not_fall_back(value: object) -> None:
    data = load_preset("iuris-ribbon-fixed").model_dump()
    data["signal"]["fixed_axis_profile"] = value
    with pytest.raises(ValidationError, match="Unsupported signal"):
        VisualPreset.model_validate(data)


@pytest.mark.parametrize(("key", "value"), [("domain", "time"), ("style", "mirrored")])
def test_profile_rejects_incompatible_preset(key: str, value: str) -> None:
    data = load_preset("iuris-ribbon-fixed").model_dump()
    data["waveform"][key] = value
    with pytest.raises(ValidationError, match="requires waveform"):
        VisualPreset.model_validate(data)


@pytest.mark.parametrize(
    "options",
    [
        {"visual_geometry": "temporal_rms"},
        {"field_geometry": "mirrored_bars"},
        {"spectrum_layout": "center_out"},
        {"bar_alternate": True},
    ],
)
def test_profile_rejects_other_geometry_requests(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="filled-ribbon-v1"):
        resolve_fixed_axis_appearance(load_preset("iuris-ribbon-fixed"), **options)


def test_mutated_profile_is_revalidated_at_resolution() -> None:
    preset = load_preset("iuris-ribbon-fixed")
    preset.waveform.domain = "time"
    with pytest.raises(ValueError, match="requires waveform"):
        resolve_fixed_axis_appearance(preset)


def test_profile_recipe_and_representation_identity_boundaries() -> None:
    preset = load_preset("iuris-ribbon-fixed")
    base = resolve_fixed_axis_appearance(preset)
    rgba = resolve_fixed_axis_appearance(preset, render_path="rgba_2d")
    assert rgba.field_plan is not None and rgba.field_plan.path == "rgba_2d"
    assert base.identity() == rgba.identity()
    taps = resolve_fixed_axis_appearance(preset, render_aa="coverage_taps")
    assert taps.identity() != base.identity()
    explicit = resolve_fixed_axis_appearance(
        preset,
        spectrum_layout="field_center_out",
        spectrum_n_bands=64,
        spectrum_spatial_filter="gaussian",
        spectrum_tilt_db_per_octave=3.0,
        spectrum_compress=0.75,
        bar_alternate=False,
    )
    assert explicit.identity() == base.identity()
    legacy = preset.model_copy(deep=True)
    del legacy.signal["fixed_axis_profile"]
    for current in (preset, legacy):
        recipe = resolve_fixed_axis_appearance(current).identity()
        signature = render_signature(
            source_sha256="ribbon-fixture", preset=current, fps=60.0, fixed_axis_recipe=recipe
        )
        if current is preset:
            profile_signature = signature
        else:
            assert signature != profile_signature


def test_stationary_center_out_activity_has_one_midpoint_and_no_scroll() -> None:
    mapping = CenterOutMapping(n_slots=65, n_bands=64)
    weights = mapping.side_mix
    bands = [0.03] * 64
    bands[7] = 0.9
    active = mapping.apply(AnalysisFrame.from_bands(bands))
    louder = mapping.apply(AnalysisFrame.from_bands([2.0 * value for value in bands]))
    quiet = mapping.apply(AnalysisFrame.from_bands([0.0] * 64))
    assert mapping.side_mix is weights
    assert active.amplitude.index(max(active.amplitude)) == 32
    assert louder.amplitude.index(max(louder.amplitude)) == 32
    assert louder.amplitude == pytest.approx([2.0 * value for value in active.amplitude])
    assert all(value == 0.0 for value in quiet.amplitude)
    assert active.amplitude != tuple(reversed(active.amplitude))
