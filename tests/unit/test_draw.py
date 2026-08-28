from ewp_waveform.ffmpeg.draw import (
    draw_envelope_frame,
    glow_overscan,
    glow_vertical_margin,
)
from ewp_waveform.ffmpeg.encode import _glow_crop_graph


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
) -> bytes:
    return draw_envelope_frame(
        columns,
        width=width,
        height=height,
        color="#C7E6EC",
        amplitude=amplitude,
        stroke_width=3.0,
        style="mirrored",
        center_line=center_line,
        scroll_phase=scroll_phase,
        vertical_margin=vertical_margin,
        content_height=content_height,
    )


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


def test_fractional_phase_keeps_height_and_covers_partial_column() -> None:
    width, height = 16, 40
    columns = [1.0] * width
    solid = _draw(columns, width=width, height=height, scroll_phase=0.0)
    # period 4: phase 3.6 puts a bar at x=0.4 covering [0.4, 3.4).
    shifted = _draw(columns, width=width, height=height, scroll_phase=3.6)
    top_a, bot_a = _column_opaque_span(solid, width, height, 2)
    top_b, bot_b = _column_opaque_span(shifted, width, height, 2)
    assert (top_a, bot_a) == (top_b, bot_b)
    alphas = [shifted[(y * width + 0) * 4 + 3] for y in range(height)]
    assert any(0 < a < 255 for a in alphas)


def test_overscan_peaks_do_not_touch_draw_edges() -> None:
    pad = glow_overscan(8.0)
    width, height = 24, 40
    draw_w = width + 2 * pad
    draw_h = height + 2 * pad
    frame = _draw(
        [1.0] * draw_w,
        width=draw_w,
        height=draw_h,
        vertical_margin=1,
        content_height=height,
        amplitude=1.0,
    )
    for y in (0, draw_h - 1):
        for x in range(draw_w):
            assert frame[(y * draw_w + x) * 4 + 3] != 255
    crop_top = pad
    peak_y, _ = _column_opaque_span(frame, draw_w, draw_h, pad + 4)
    assert peak_y >= crop_top


def test_glow_crop_graph_crops_overscan() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26)
    assert "gblur=sigma=8" in graph
    assert "crop=1400:280:26:26" in graph
    assert graph.endswith("[out]")


def test_glow_crop_graph_downsamples_supersample() -> None:
    graph = _glow_crop_graph(8.0, 1400, 280, 26, supersample=4)
    assert "scale=1452:332:flags=area" in graph
    assert "crop=1400:280:26:26" in graph


def test_bar_mag_stays_on_envelope_origin_across_phase() -> None:
    columns = [0.1] * 4 + [1.0] + [0.1] * 11
    width, height = 16, 40
    a = _draw(columns, width=width, height=height, scroll_phase=0.0)
    b = _draw(columns, width=width, height=height, scroll_phase=0.6)
    top_a, bot_a = _column_opaque_span(a, width, height, 5)
    top_b, bot_b = _column_opaque_span(b, width, height, 4)
    assert top_a != -1
    assert (top_a, bot_a) == (top_b, bot_b)


def test_supersample_frame_is_wider() -> None:
    width, height = 8, 20
    frame = draw_envelope_frame(
        [1.0] * width,
        width=width,
        height=height,
        color="#FFFFFF",
        amplitude=0.8,
        stroke_width=3.0,
        style="mirrored",
        center_line=False,
        supersample=4,
    )
    assert len(frame) == width * 4 * height * 4
