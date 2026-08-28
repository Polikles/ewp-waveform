from ewp_waveform.ffmpeg.draw import draw_envelope_frame, glow_vertical_margin


def _column_opaque_span(frame: bytes, width: int, height: int, x: int) -> tuple[int, int]:
    ys = []
    for y in range(height):
        alpha = frame[(y * width + x) * 4 + 3]
        if alpha == 255:
            ys.append(y)
    if not ys:
        return -1, -1
    return ys[0], ys[-1]


def test_scroll_phase_translates_bars_without_changing_height() -> None:
    columns = [0.1, 0.4, 0.9, 0.2, 0.7, 0.3, 0.8, 0.5, 0.6, 0.15]
    width = 8
    height = 40
    a = draw_envelope_frame(
        columns[:8],
        width=width,
        height=height,
        color="#C7E6EC",
        amplitude=0.95,
        stroke_width=3.0,
        style="mirrored",
        center_line=False,
        scroll_phase=0,
        vertical_margin=2,
    )
    b = draw_envelope_frame(
        columns[1:9],
        width=width,
        height=height,
        color="#C7E6EC",
        amplitude=0.95,
        stroke_width=3.0,
        style="mirrored",
        center_line=False,
        scroll_phase=1,
        vertical_margin=2,
    )
    top_a, bot_a = _column_opaque_span(a, width, height, 4)
    top_b, bot_b = _column_opaque_span(b, width, height, 3)
    assert top_a != -1
    assert (top_a, bot_a) == (top_b, bot_b)


def test_peak_bars_stay_inside_frame() -> None:
    width, height = 20, 40
    columns = [1.0] * width
    margin = glow_vertical_margin(8.0)
    frame = draw_envelope_frame(
        columns,
        width=width,
        height=height,
        color="#FFFFFF",
        amplitude=0.95,
        stroke_width=3.0,
        style="mirrored",
        center_line=False,
        vertical_margin=margin,
    )
    for x in range(width):
        for y in (0, height - 1):
            assert frame[(y * width + x) * 4 + 3] == 0
