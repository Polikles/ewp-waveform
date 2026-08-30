from itertools import pairwise

from ewp_waveform.ffmpeg.draw import (
    bar_metrics,
    draw_envelope_frame,
    glow_overscan,
    glow_vertical_margin,
    peak_half_height,
)
from ewp_waveform.ffmpeg.encode import _glow_crop_graph, shutter_sigma


def _column_opaque_span(frame: bytes, width: int, height: int, x: int) -> tuple[int, int]:
    ys = []
    for y in range(height):
        alpha = frame[(y * width + x) * 4 + 3]
        if alpha == 255:
            ys.append(y)
    if not ys:
        return -1, -1
    return ys[0], ys[-1]


def _draw(
    columns: list[float],
    *,
    width: int,
    height: int = 40,
    scroll_phase: float = 0.0,
    vertical_margin: int = 2,
    content_height: int | None = None,
    center_line: bool = False,
    amplitude: float = 0.95,
    stroke_width: float = 3.0,
    glow_sigma: float = 0.0,
) -> bytes:
    return draw_envelope_frame(
        columns,
        width=width,
        height=height,
        color="#C7E6EC",
        amplitude=amplitude,
        stroke_width=stroke_width,
        style="mirrored",
        center_line=center_line,
        scroll_phase=scroll_phase,
        vertical_margin=vertical_margin,
        content_height=content_height,
        glow_sigma=glow_sigma,
    )


def test_mirrored_bars_have_no_gap() -> None:
    stroke, gap = bar_metrics("mirrored", 6.0)
    assert stroke == 6
    assert gap == 0


def test_peak_half_height_uses_glow_spread() -> None:
    spread = glow_overscan(8.0)
    assert peak_half_height(280, 8.0, 1.0) == 280 // 2 - spread
    assert peak_half_height(280, 0.0, 1.0) == 280 // 2 - 2


def test_scroll_phase_translates_bars_without_changing_height() -> None:
    columns = [0.1, 0.4, 0.9, 0.2, 0.7, 0.3, 0.8, 0.5, 0.6, 0.15]
    width = 8
    height = 40
    a = _draw(columns[:8], width=width, height=height, scroll_phase=0)
    b = _draw(columns[1:9], width=width, height=height, scroll_phase=1)
    top_a, bot_a = _column_opaque_span(a, width, height, 4)
    top_b, bot_b = _column_opaque_span(b, width, height, 3)
    assert top_a != -1
    assert (top_a, bot_a) == (top_b, bot_b)


def test_peak_bars_stay_inside_frame() -> None:
    width, height = 20, 40
    columns = [1.0] * width
    margin = glow_vertical_margin(8.0)
    frame = _draw(columns, width=width, height=height, vertical_margin=margin)
    for x in range(width):
        for y in (0, height - 1):
            assert frame[(y * width + x) * 4 + 3] == 0


def test_fractional_phase_keeps_height_on_flat_envelope() -> None:
    width, height = 16, 40
    columns = [1.0] * width
    solid = _draw(columns, width=width, height=height, scroll_phase=0.0)
    shifted = _draw(columns, width=width, height=height, scroll_phase=2.6)
    top_a, bot_a = _column_opaque_span(solid, width, height, 2)
    top_b, bot_b = _column_opaque_span(shifted, width, height, 2)
    assert top_a != -1
    assert (top_a, bot_a) == (top_b, bot_b)


def test_overscan_peaks_do_not_touch_draw_edges() -> None:
    pad = glow_overscan(8.0)
    width, height = 24, 80
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    frame = _draw(
        [1.0] * draw_w,
        width=draw_w,
        height=draw_h,
        content_height=height,
        amplitude=1.0,
        glow_sigma=8.0,
    )
    for y in (0, draw_h - 1):
        for x in range(draw_w):
            assert frame[(y * draw_w + x) * 4 + 3] != 255
    peak_y, _ = _column_opaque_span(frame, draw_w, draw_h, pad + 4)
    assert peak_y >= pad + pad


def test_glow_crop_graph_crops_overscan() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26)
    assert "gblur=sigma=8" in graph
    assert "crop=1400:280:26:26" in graph
    assert graph.endswith("[out]")


def test_glow_crop_graph_downsamples_supersample() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26, supersample=4)
    assert "scale=1452:332:flags=area" in graph
    assert "crop=1400:280:26:26" in graph


def test_glow_crop_graph_hybrid_shutter_under_sharp_base() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26, supersample=12, shutter_px=0.78, shutter_mix=0.25)
    assert "blend=all_expr='A*0.7500+B*0.2500'" in graph
    assert graph.find("scale=1452:332:flags=area") < graph.find("blend=")
    assert graph.find("blend=") < graph.find("gblur=sigma=8")
    assert "[gb][base]overlay" in graph


def test_glow_crop_graph_no_shutter_skips_blend() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26, supersample=12, shutter_px=0.0)
    assert "blend=" not in graph


def test_shutter_sigma_matches_short_shutter() -> None:
    assert shutter_sigma(0.0) == 0.0
    assert abs(shutter_sigma(0.78) - 0.78 / 2.355) < 1e-9


def _column_alpha_mass(frame: bytes, width: int, height: int, x: int) -> int:
    return sum(frame[(y * width + x) * 4 + 3] for y in range(height))


def test_adjacent_bin_lerp_is_monotonic_across_half_bin() -> None:
    """Nearest-neighbor snapped at 0.5; lerp must rise smoothly through that boundary."""
    columns = [0.2, 0.9] + [0.2] * 14
    width, height = 16, 80
    phases = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 0.99]
    masses = [
        _column_alpha_mass(
            _draw(columns, width=width, height=height, scroll_phase=phase),
            width,
            height,
            0,
        )
        for phase in phases
    ]
    assert masses[0] < masses[-1]
    for earlier, later in pairwise(masses):
        assert later >= earlier
    full = masses[-1] - masses[0]
    assert masses[3] - masses[2] <= full * 0.35
    assert masses[4] - masses[3] <= full * 0.35


def test_vertical_edge_has_partial_coverage() -> None:
    width, height = 8, 40
    frame = _draw([0.5] * width, width=width, height=height, amplitude=1.0)
    alphas = [frame[(y * width + 2) * 4 + 3] for y in range(height)]
    assert any(0 < a < 255 for a in alphas)
    assert any(a == 255 for a in alphas)


def test_twelve_x_keeps_third_pixel_phases_stable_on_high_frequency() -> None:
    width, height = 24, 40
    columns = ([0.25, 0.85] * (width // 2 + 2))[:width]

    def pump(ss: int) -> float:
        masses = [
            sum(
                draw_envelope_frame(
                    columns,
                    width=width,
                    height=height,
                    color="#FFFFFF",
                    amplitude=0.8,
                    stroke_width=6.0,
                    style="mirrored",
                    center_line=False,
                    scroll_phase=phase,
                    supersample=ss,
                )[3::4]
            )
            for phase in (0.0, 1.0 / 3.0, 2.0 / 3.0)
        ]
        return (max(masses) - min(masses)) / max(masses)

    assert pump(12) < 0.05


def test_supersample_frame_is_wider() -> None:
    width, height = 8, 20
    frame = draw_envelope_frame(
        [1.0] * width,
        width=width,
        height=height,
        color="#FFFFFF",
        amplitude=0.8,
        stroke_width=6.0,
        style="mirrored",
        center_line=False,
        supersample=4,
    )
    assert len(frame) == width * 4 * height * 4
