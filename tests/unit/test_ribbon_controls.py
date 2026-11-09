from __future__ import annotations

import json
import tomllib
from copy import deepcopy
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.application.render_fixed import _ribbon_baseline
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.config.ribbon import BRAND_COLORS, DETAIL_SETTINGS, apply_public_appearance
from ewp_waveform.identity import render_signature
from ewp_waveform.paths import builtin_presets_dir, project_root
from ewp_waveform.visual.mapping import CenterOutMapping, RefinedRibbonMapping


def _preset() -> VisualPreset:
    return load_preset("iuris-ribbon-refined")


def test_controls_defaults_and_original_preset_are_distinct() -> None:
    preset = _preset()
    appearance = resolve_fixed_axis_appearance(preset)
    assert appearance.profile == "filled-ribbon-v2"
    assert appearance.detail_level == "balanced"
    assert appearance.baseline_thickness == 1.0
    assert appearance.n_bands == 64
    assert appearance.compress == 1.0
    assert appearance.spatial_sigma == pytest.approx(3.15)
    assert appearance.identity()["mapping_revision"] == 2
    assert preset.signal["smoothing"] == 0.06
    old = load_preset("iuris-ribbon-fixed")
    assert old.signal["fixed_axis_profile"] == "filled-ribbon-v1"
    assert old.signal["smoothing"] == 0.15
    assert old.waveform.stroke_width is None
    assert resolve_fixed_axis_appearance(old).identity()["compress"] == 0.75


@pytest.mark.parametrize("color", list(BRAND_COLORS))
def test_brand_names_resolve_without_mutation(color: str) -> None:
    original = _preset()
    before = original.model_dump()
    resolved = apply_public_appearance(original, waveform_color=color)
    assert resolved.waveform.color == BRAND_COLORS[color]
    assert resolved.effects["glow"]["color"] == BRAND_COLORS[color]  # type: ignore[index]
    assert original.model_dump() == before
    assert BRAND_COLORS["soft_yellow"] == "#F2C558"  # Reference #F2C55B remains unresolved.


@pytest.mark.parametrize(
    "options",
    [
        {"detail_level": "smooth"},
        {"detail_level": "detailed"},
        {"waveform_color": "steel_blue"},
        {"glow_level": "none"},
        {"amplitude": 0.4},
        {"stroke_width": 6.0},
    ],
)
def test_each_control_changes_effective_identity(options: dict[str, Any]) -> None:
    original = _preset()
    modified = apply_public_appearance(original, **options)

    def signature(preset: VisualPreset) -> str:
        return render_signature(
            source_sha256="fixture",
            preset=preset,
            fps=60,
            fixed_axis_recipe=resolve_fixed_axis_appearance(preset).identity(),
        )

    assert signature(modified) != signature(original)
    if "detail_level" not in options:
        assert modified.signal["detail_level"] == original.signal["detail_level"]
    if "amplitude" not in options:
        assert modified.waveform.amplitude == original.waveform.amplitude


@pytest.mark.parametrize(
    "options",
    [
        {"detail_level": "ultra"},
        {"detail_level": ""},
        {"waveform_color": "yellow"},
        {"waveform_color": 1},
        {"waveform_color": []},
        {"waveform_color": "#12345678"},
        {"glow_level": "maximum"},
        {"amplitude": 0},
        {"amplitude": 1.01},
        {"amplitude": float("nan")},
        {"amplitude": float("inf")},
        {"amplitude": True},
        {"amplitude": "0.5"},
        {"stroke_width": 0},
        {"stroke_width": 12.1},
        {"stroke_width": float("nan")},
        {"stroke_width": True},
    ],
)
def test_invalid_public_overrides_fail(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        apply_public_appearance(_preset(), **options)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("signal", "detail_level", "ultra"),
        ("signal", "detail_level", None),
        ("signal", "smoothing", -0.1),
        ("signal", "smoothing", 0.6),
        ("signal", "smoothing", True),
        ("signal", "smoothing", float("nan")),
        ("signal", "detail_levle", "detailed"),
        ("signal", "noise", True),
        ("signal", "scale", "typo"),
        ("waveform", "height", 0.5),
        ("waveform", "amplitude", True),
        ("waveform", "amplitude", 2),
        ("waveform", "stroke_width", 0),
        ("waveform", "domain", "time"),
        ("waveform", "style", "classic"),
        ("waveform", "time_mode", "scroll"),
        ("waveform", "window_seconds", 8),
        ("waveform", "center_line", False),
        ("effects", "unknown_effect", {}),
    ],
)
def test_saved_presets_reject_ignored_and_incompatible_settings(
    section: str, key: str, value: Any
) -> None:
    data = _preset().model_dump()
    data[section][key] = value
    with pytest.raises(ValidationError):
        VisualPreset.model_validate(data)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("glow", "radius", 20),
        ("glow", "intensity", 2),
        ("glow", "level", "ultra"),
        ("glow", "color", "#FFFFFF"),
        ("glow", "enabled", False),
        ("particles", "enabled", True),
    ],
)
def test_unsupported_effect_fields_fail(section: str, key: str, value: Any) -> None:
    data = _preset().model_dump()
    data["effects"][section][key] = value
    with pytest.raises(ValidationError):
        VisualPreset.model_validate(data)


@pytest.mark.parametrize(
    "options",
    [
        {"spectrum_n_bands": 128},
        {"spectrum_compress": 0.5},
        {"spectrum_contour": True},
        {"spectrum_spatial_filter": "gaussian"},
        {"spectrum_spatial_scale": 2},
        {"spectrum_recenter": True},
        {"spectrum_edge_taper": 0.2},
        {"spectrum_slot_sigma": 2},
        {"spectrum_tilt_db_per_octave": 3},
        {"bar_count": 20},
        {"bar_center_line_width": 3},
        {"bar_alternate": True},
        {"field_geometry": "mirrored_bars"},
        {"visual_geometry": "temporal_rms"},
        {"spectrum_layout": "center_out"},
        {"render_path": "typo"},
        {"render_aa": "typo"},
        {"ribbon_supersample": 0},
        {"ribbon_supersample": True},
    ],
)
def test_refined_profile_never_discards_low_level_overrides(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="filled-ribbon-v2"):
        resolve_fixed_axis_appearance(_preset(), **options)


@pytest.mark.parametrize("name", ["iuris-default", "iuris-spectrum", "iuris-ribbon-fixed"])
def test_detail_is_incompatible_with_legacy_profiles(name: str) -> None:
    preset = load_preset(name)
    with pytest.raises(ValueError, match="require"):
        apply_public_appearance(preset, detail_level="detailed")
    data = preset.model_dump()
    data["signal"]["detail_level"] = "detailed"
    with pytest.raises(ValidationError, match="requires"):
        VisualPreset.model_validate(data)


def test_detail_has_audio_information_and_multi_scale_variation_not_just_size() -> None:
    bands = [0.02 + (0.8 if i in {4, 12, 22, 40, 50} else 0.0) for i in range(64)]
    frame = AnalysisFrame.from_bands(bands)
    shapes = []
    for detail in DETAIL_SETTINGS:
        mapping = RefinedRibbonMapping(detail_level=detail)
        output = np.array(mapping.apply(frame).amplitude)
        louder = mapping.apply(AnalysisFrame.from_bands([v * 2 for v in bands])).amplitude
        assert louder == pytest.approx(output * 2)
        assert mapping.apply(AnalysisFrame.from_bands([0.0] * 64)).amplitude == (0.0,) * 65
        different = mapping.apply(AnalysisFrame.from_bands(list(reversed(bands)))).amplitude
        assert different != pytest.approx(output)
        assert mapping.n_bands == 64
        shapes.append(output / output.max())
    assert not np.allclose(shapes[0], shapes[1]) and not np.allclose(shapes[1], shapes[2])

    def variation(row: np.ndarray) -> float:
        return float(np.sum(np.abs(np.diff(row))))

    # Total variation normalized by each frame's maximum need not be monotone:
    # one narrow dominant peak can reduce that sum. Test fine-scale information
    # and peak width instead, not hashes or decorative sample-count differences.
    assert variation(shapes[1]) > variation(shapes[0])
    fine_power = []
    for shape in shapes:
        power = np.abs(np.fft.rfft(shape - shape.mean())) ** 2
        fine_power.append(float(power[12:].sum() / power[1:].sum()))
    assert fine_power[2] > fine_power[1] > fine_power[0]
    assert (
        np.count_nonzero(shapes[2] > 0.5)
        < np.count_nonzero(shapes[1] > 0.5)
        < np.count_nonzero(shapes[0] > 0.5)
    )
    assert np.count_nonzero(shapes[2] < 0.1) > np.count_nonzero(shapes[0] < 0.1)
    old = np.array(CenterOutMapping().apply(frame).amplitude)
    assert np.count_nonzero(shapes[2] >= 0.5) < np.count_nonzero(old / old.max() >= 0.5)


def test_baseline_thickness_is_independent_and_legacy_is_exact_noop() -> None:
    columns = [0.0, 0.1, 0.7]
    original = load_preset("iuris-ribbon-fixed")
    assert _ribbon_baseline(columns, original, 16) is columns
    refined = _preset()
    assert _ribbon_baseline(columns, refined, 16) is columns
    thick = apply_public_appearance(refined, stroke_width=8)
    result = _ribbon_baseline(columns, thick, 16)
    assert result[0] > 0 and result[1:] == columns[1:]
    assert refined.waveform.stroke_width == 1


@pytest.mark.parametrize("command", ["dry-run", "preview", "render"])
def test_cli_propagates_controls(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import ewp_waveform.application.service as service

    seen: dict[str, Any] = {}

    class Stop(Exception):
        pass

    def capture(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(service, "plan_jobs" if command == "dry-run" else "render", capture)
    result = CliRunner().invoke(
        app,
        [
            command,
            "input.wav",
            "--preset",
            "iuris-ribbon-refined",
            "--detail-level",
            "detailed",
            "--waveform-color",
            "pale_cyan",
            "--glow-level",
            "low",
            "--amplitude",
            "0.4",
            "--stroke-width",
            "5",
        ],
    )
    assert isinstance(result.exception, Stop), result.output
    assert {
        k: seen[k]
        for k in ("detail_level", "waveform_color", "glow_level", "amplitude", "stroke_width")
    } == {
        "detail_level": "detailed",
        "waveform_color": "pale_cyan",
        "glow_level": "low",
        "amplitude": 0.4,
        "stroke_width": 5.0,
    }


def test_unknown_service_and_helper_overrides_rejected() -> None:
    with pytest.raises(TypeError):
        apply_public_appearance(_preset(), nonexistent="x")  # type: ignore[call-arg]
    copy = deepcopy(_preset())
    copy.signal["detail_level"] = "typo"
    with pytest.raises(ValueError):
        resolve_fixed_axis_appearance(copy)


@pytest.mark.parametrize("key", ["fmin_hz", "fmax_hz"])
def test_refined_partial_frequency_pair_rejected_but_legacy_unchanged(key: str) -> None:
    data = _preset().model_dump()
    data["signal"]["frequency"] = {"range": "auto", key: 1000.0}
    with pytest.raises(ValidationError, match="both fmin_hz and fmax_hz or neither"):
        VisualPreset.model_validate(data)
    legacy = load_preset("iuris-ribbon-fixed").model_dump()
    legacy["signal"]["frequency"] = data["signal"]["frequency"]
    assert VisualPreset.model_validate(legacy).signal["frequency"] == data["signal"]["frequency"]


@pytest.mark.parametrize("bounds", [{}, {"fmin_hz": 100.0, "fmax_hz": 1000.0}])
def test_refined_complete_or_automatic_frequency_pair_stays_valid(bounds: dict[str, float]) -> None:
    data = _preset().model_dump()
    data["signal"]["frequency"] = {"range": "auto", **bounds}
    assert VisualPreset.model_validate(data).signal["frequency"] == data["signal"]["frequency"]


def _schema_and_raw_preset(name: str) -> tuple[Any, dict[str, Any]]:
    # Optional validator tooling is not a production dependency. Never install it here.
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((project_root() / "schemas" / "preset.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    raw = tomllib.loads((builtin_presets_dir() / f"{name}.toml").read_text())
    return jsonschema.Draft202012Validator(schema), raw


@pytest.mark.parametrize(
    ("bounds", "valid"),
    [({}, True), ({"fmin_hz": 100.0, "fmax_hz": 1000.0}, True),
     ({"fmin_hz": 1000.0}, False), ({"fmax_hz": 1000.0}, False)],
)
def test_refined_frequency_schema_and_model_agree(bounds: dict[str, float], valid: bool) -> None:
    validator, data = _schema_and_raw_preset("iuris-ribbon-refined")
    data["signal"]["frequency"] = {"range": "auto", **bounds}
    assert validator.is_valid(data) is valid
    if valid:
        VisualPreset.model_validate(data)
    else:
        with pytest.raises(ValidationError, match="both fmin_hz and fmax_hz or neither"):
            VisualPreset.model_validate(data)


@pytest.mark.parametrize("key", ["fmin_hz", "fmax_hz"])
def test_legacy_schema_and_model_keep_partial_bounds_and_eight_digit_color(key: str) -> None:
    validator, data = _schema_and_raw_preset("iuris-ribbon-fixed")
    data["signal"]["frequency"] = {"range": "auto", key: 1000.0}
    data["waveform"]["color"] = "#C7E6EC80"
    assert validator.is_valid(data)
    assert VisualPreset.model_validate(data).waveform.color == "#C7E6EC80"


@pytest.mark.parametrize("color,valid", [("#C7E6EC", True), ("#C7E6EC80", False)])
def test_refined_color_schema_and_model_agree(color: str, valid: bool) -> None:
    validator, data = _schema_and_raw_preset("iuris-ribbon-refined")
    data["waveform"]["color"] = color
    data["effects"]["glow"].pop("color", None)
    assert validator.is_valid(data) is valid
    if valid:
        VisualPreset.model_validate(data)
    else:
        with pytest.raises(ValidationError, match=r"waveform\.color must be #RRGGBB"):
            VisualPreset.model_validate(data)


@pytest.mark.parametrize("glow_color", [None, "#123aBc", "#FFFFFF", "#123ABC"])
def test_glow_color_equality_is_documented_runtime_semantics(glow_color: str | None) -> None:
    validator, data = _schema_and_raw_preset("iuris-ribbon-refined")
    data["waveform"]["color"] = "#123aBc"
    if glow_color is None:
        data["effects"]["glow"].pop("color", None)
    else:
        data["effects"]["glow"]["color"] = glow_color
    assert validator.is_valid(data)  # Standard schema cannot compare arbitrary siblings.
    comment = validator.schema["allOf"][2]["then"]["properties"]["effects"]["properties"][
        "glow"
    ]["properties"]["color"]["$comment"]
    assert "semantic runtime validation" in comment
    if glow_color in (None, "#123aBc"):
        VisualPreset.model_validate(data)
    else:
        with pytest.raises(ValidationError, match="independent glow color is unsupported"):
            VisualPreset.model_validate(data)
