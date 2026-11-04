from __future__ import annotations

from typing import Any

import pytest

from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.style_defaults import default_bar_style


def _preset() -> VisualPreset:
    preset = load_preset("iuris-default").model_copy(deep=True)
    preset.waveform.domain = "frequency"
    preset.signal["smoothing"] = 0.2
    return preset


def _recipe(**options: Any) -> dict[str, Any]:
    return resolve_fixed_axis_appearance(_preset(), **options).identity()


def _signature(**options: Any) -> str:
    return render_signature(
        source_sha256="abc", preset=_preset(), fps=60.0, fixed_axis_recipe=_recipe(**options)
    )


@pytest.mark.parametrize(
    ("base", "change"),
    [
        ({}, {"spectrum_contour": True}),
        ({}, {"spectrum_spatial_scale": 2.0}),
        ({}, {"spectrum_spatial_filter": "gaussian"}),
        ({}, {"spectrum_n_bands": 32}),
        ({"spectrum_n_bands": 32}, {"spectrum_tilt_db_per_octave": 2.0}),
        ({"spectrum_n_bands": 32}, {"spectrum_compress": 0.5}),
        ({"spectrum_n_bands": 32}, {"spectrum_recenter": True}),
        ({}, {"spectrum_edge_taper": 0.2}),
        ({}, {"visual_geometry": "temporal_rms"}),
        ({"visual_geometry": "temporal_rms"}, {"visual_geometry": "temporal_rms_peak"}),
        ({"spectrum_n_bands": 32}, {"spectrum_layout": "center_out"}),
        ({"spectrum_layout": "center_out", "spectrum_n_bands": 32}, {"spectrum_slot_sigma": 1.0}),
        ({}, {"ribbon_supersample": 4}),
        ({}, {"spectrum_layout": "field_center_out"}),
        ({"spectrum_layout": "field_center_out"}, {"field_geometry": "segmented_impulse"}),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_width": 8.0},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_gap": 10.0},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_count": 8},
        ),
        (
            {
                "spectrum_layout": "field_center_out",
                "field_geometry": "mirrored_bars",
                "bar_count": 8,
            },
            {"bar_fill": 0.3},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_align": "slots"},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_alternate": False},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_color_b": "#FFFFFF"},
        ),
        (
            {"spectrum_layout": "field_center_out", "field_geometry": "mirrored_bars"},
            {"bar_center_line_width": 5.0},
        ),
        (
            {"spectrum_layout": "field_center_out", "bar_alternate": False},
            {"render_aa": "coverage_taps"},
        ),
    ],
)
def test_active_controls_change_identity(base: dict[str, Any], change: dict[str, Any]) -> None:
    assert _signature(**base) != _signature(**{**base, **change})
    assert _signature(**base) == _signature(**base)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ({}, {"spectrum_contour": False, "ribbon_supersample": 2}),
        ({}, {"spectrum_layout": "unknown", "spectrum_spatial_filter": "unknown"}),
        ({}, {"spectrum_n_bands": True, "spectrum_spatial_scale": False}),
        (
            {},
            {
                "spectrum_tilt_db_per_octave": 3,
                "spectrum_compress": 0.5,
                "spectrum_recenter": True,
                "spectrum_slot_sigma": 2,
                "spectrum_layout": "center_out",
            },
        ),
        ({"spectrum_edge_taper": 0.49}, {"spectrum_edge_taper": 0.9}),
        (
            {"spectrum_n_bands": 32, "spectrum_compress": 1.0},
            {"spectrum_n_bands": 32, "spectrum_compress": 2.0},
        ),
        (
            {"spectrum_n_bands": 32, "spectrum_compress": 0.05},
            {"spectrum_n_bands": 32, "spectrum_compress": 0.01},
        ),
        ({"ribbon_supersample": 1}, {"ribbon_supersample": 0}),
        (
            {"spectrum_layout": "field_center_out"},
            {"spectrum_layout": "field_center_out", "spectrum_n_bands": 64},
        ),
        (
            {"spectrum_layout": "field_center_out"},
            {"spectrum_layout": "field_center_out", "field_geometry": "unknown"},
        ),
        (
            {"spectrum_layout": "field_center_out"},
            {
                "spectrum_layout": "field_center_out",
                "spectrum_contour": True,
                "spectrum_recenter": True,
                "spectrum_edge_taper": 0.3,
                "spectrum_slot_sigma": 2,
            },
        ),
        (
            {"visual_geometry": "temporal_rms"},
            {
                "visual_geometry": "temporal_rms",
                "spectrum_layout": "field_center_out",
                "spectrum_contour": True,
                "spectrum_n_bands": 32,
                "ribbon_supersample": 4,
            },
        ),
        (
            {"spectrum_layout": "field_center_out"},
            {"spectrum_layout": "field_center_out", "bar_width": 10, "bar_gap": 1},
        ),
        (
            {
                "spectrum_layout": "field_center_out",
                "field_geometry": "mirrored_bars",
                "bar_count": 8,
            },
            {
                "spectrum_layout": "field_center_out",
                "field_geometry": "mirrored_bars",
                "bar_count": 8,
                "bar_align": "count",
            },
        ),
        (
            {
                "spectrum_layout": "field_center_out",
                "bar_alternate": False,
                "render_path": "mask_fast",
            },
            {
                "spectrum_layout": "field_center_out",
                "bar_alternate": False,
                "render_path": "rgba_2d",
            },
        ),
        (
            {
                "spectrum_layout": "field_center_out",
                "bar_alternate": False,
                "render_path": "rgba_2d",
                "render_aa": "coverage_taps",
            },
            {
                "spectrum_layout": "field_center_out",
                "bar_alternate": False,
                "render_path": "rgba_2d",
                "render_aa": "physical_ss",
            },
        ),
        (
            {
                "spectrum_layout": "field_center_out",
                "field_geometry": "segmented_impulse",
                "render_aa": "coverage_taps",
                "ribbon_supersample": 2,
            },
            {
                "spectrum_layout": "field_center_out",
                "field_geometry": "segmented_impulse",
                "render_aa": "coverage_taps",
                "ribbon_supersample": 4,
            },
        ),
    ],
)
def test_equivalent_effective_controls_share_identity(
    left: dict[str, Any], right: dict[str, Any]
) -> None:
    assert _recipe(**left) == _recipe(**right)
    assert _signature(**left) == _signature(**right)


@pytest.mark.parametrize(
    "geometry", ["ribbon", "mirrored_bars", "classic_ticks", "segmented_impulse"]
)
def test_omitted_and_explicit_field_defaults(geometry: str) -> None:
    pack = default_bar_style(geometry)
    base = {"spectrum_layout": "field_center_out", "field_geometry": geometry}
    assert _recipe(**base) == _recipe(
        **base,
        spectrum_n_bands=64,
        ribbon_supersample=2,
        render_aa="physical_ss",
        bar_width=pack.width,
        bar_gap=pack.gap,
        bar_count=None,
        bar_fill=pack.fill,
        bar_align=pack.align,
        bar_alternate=pack.alternate,
        bar_color_b=pack.color_b,
        bar_center_line_width=pack.center_line_width,
    )


def test_disabled_smoothing_ignores_spatial_options() -> None:
    preset = _preset()
    preset.signal["smoothing"] = 0.0
    assert (
        resolve_fixed_axis_appearance(preset).identity()
        == resolve_fixed_axis_appearance(
            preset, spectrum_spatial_scale=2, spectrum_spatial_filter="gaussian"
        ).identity()
    )


def test_alternate_pack_aa_fallback_is_preserved() -> None:
    base: dict[str, Any] = {"spectrum_layout": "field_center_out", "render_aa": "coverage_taps"}
    assert _signature(**base) != _signature(**base, bar_alternate=False)
    resolved = resolve_fixed_axis_appearance(_preset(), **base)
    assert resolved.field_plan is not None
    assert resolved.field_plan.path == "rgba_2d"
    assert resolved.field_plan.aa_mode == "physical_ss"
