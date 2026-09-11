from ewp_waveform.config.models import CanvasSection, VisualPreset, WaveformSection
from ewp_waveform.ffmpeg.draw import draw_spectrum_alpha, draw_spectrum_frame
from ewp_waveform.visual.plan import inspect_capabilities, resolve_render_plan


def _preset(*, particles: bool = False, frequency: bool = True) -> VisualPreset:
    return VisualPreset(
        schema_version=1,
        name="t",
        canvas=CanvasSection(width=1400, height=280, fps=60),
        waveform=WaveformSection(
            style="mirrored",
            color="#C7E6EC",
            amplitude=0.82,
            domain="frequency" if frequency else "time",
            center_line=True,
        ),
        effects={
            "glow": {"enabled": True, "level": "medium"},
            "particles": {"enabled": particles},
        },
    )


def test_monochrome_ribbon_with_glow_selects_mask_fast() -> None:
    plan = resolve_render_plan(_preset(), layout="field_center_out", field_geometry="ribbon")
    caps = inspect_capabilities(_preset(), layout="field_center_out", field_geometry="ribbon")
    assert caps.glow
    assert not caps.particles
    assert caps.mask_renderable_geometry
    assert plan.path == "mask_fast"
    assert plan.pix_fmt == "gray"
    assert plan.colorize
    assert plan.geometry == "ribbon"
    assert plan.bytes_per_pixel == 1


def test_monochrome_bars_with_glow_select_mask_fast() -> None:
    plan = resolve_render_plan(_preset(), layout="field_center_out", field_geometry="mirrored_bars")
    caps = inspect_capabilities(
        _preset(), layout="field_center_out", field_geometry="mirrored_bars"
    )
    assert caps.mask_renderable_geometry
    assert plan.path == "mask_fast"
    assert plan.geometry == "mirrored_bars"
    assert plan.pix_fmt == "gray"


def test_alternating_bar_colors_select_rgba_2d() -> None:
    plan = resolve_render_plan(
        _preset(),
        layout="field_center_out",
        field_geometry="mirrored_bars",
        alternate_bars=True,
    )
    assert plan.path == "rgba_2d"
    assert plan.pix_fmt == "rgba"
    assert plan.fallback_from == "mask_fast"


def test_particles_force_rgba_2d_fallback() -> None:
    plan = resolve_render_plan(
        _preset(particles=True), layout="field_center_out", field_geometry="ribbon"
    )
    assert plan.path == "rgba_2d"
    assert plan.pix_fmt == "rgba"
    assert plan.fallback_from == "mask_fast"


def test_scroll_style_does_not_take_mask_path() -> None:
    plan = resolve_render_plan(_preset(frequency=False), layout="linear", field_geometry="ribbon")
    assert plan.path == "rgba_2d"
    assert not inspect_capabilities(
        _preset(frequency=False), layout="linear", field_geometry="ribbon"
    ).mask_renderable_geometry


def test_force_rgba_keeps_mask_as_documented_fallback() -> None:
    plan = resolve_render_plan(
        _preset(), layout="field_center_out", field_geometry="ribbon", force_path="rgba_2d"
    )
    assert plan.path == "rgba_2d"
    assert plan.fallback_from == "mask_fast"


def test_coverage_taps_avoid_physical_2x_framebuffer() -> None:
    plan = resolve_render_plan(
        _preset(),
        layout="field_center_out",
        field_geometry="ribbon",
        ribbon_supersample=2,
        aa_mode="coverage_taps",
    )
    assert plan.path == "mask_fast"
    assert plan.supersample == 1
    assert plan.aa_taps == 2
    assert plan.bytes_per_frame(1400, 280, 26) == 1452 * 332 * 1


def test_gray_alpha_matches_rgba_alpha_channel() -> None:
    columns = [0.1, 0.4, 1.0, 0.5, 0.2] + [0.0] * 11
    rgba = draw_spectrum_frame(
        columns,
        width=16,
        height=32,
        color="#C7E6EC",
        amplitude=1.0,
        center_line=True,
        supersample=2,
    )
    gray = draw_spectrum_alpha(
        columns,
        width=16,
        height=32,
        amplitude=1.0,
        center_line=True,
        supersample=2,
    )
    assert len(gray) * 4 == len(rgba)
    for i, value in enumerate(gray):
        assert rgba[i * 4 + 3] == value
        if value:
            assert rgba[i * 4 : i * 4 + 3] == bytes((0xC7, 0xE6, 0xEC))
