from ewp_waveform.visual.bars import (
    BarStyle,
    bar_spans,
    draw_mirrored_bars_alpha,
    draw_mirrored_bars_rgba,
)


def test_bar_spans_are_stationary_and_centered() -> None:
    style = BarStyle(width=5, gap=3)
    first = bar_spans(1400, style)
    second = bar_spans(1400, style)
    assert first == second
    assert first
    mid = 700.0
    covering = [span for span in first if span[0] <= mid < span[1]]
    assert len(covering) == 1
    left, right = covering[0]
    assert abs((left + right) / 2.0 - mid) < 1e-9
    widths = {round(b - a, 9) for a, b in first}
    assert widths == {5.0}


def test_bars_leave_horizontal_gaps() -> None:
    columns = [1.0] * 80
    frame = draw_mirrored_bars_alpha(
        columns,
        width=80,
        height=40,
        style=BarStyle(width=4, gap=4),
        amplitude=1.0,
        center_line=False,
        supersample=1,
    )
    row = 20
    alphas = [frame[row * 80 + x] for x in range(80)]
    assert max(alphas) == 255
    assert 0 in alphas
    # A solid run of zeros exists between opaque bars.
    joined = "".join("1" if a else "0" for a in alphas)
    assert "10" in joined and "01" in joined


def test_count_layout_places_odd_bar_on_midline() -> None:
    spans = bar_spans(1400, BarStyle(count=117, fill=0.62, align="count"))
    assert len(spans) == 117
    mid = 700.0
    covering = [span for span in spans if span[0] <= mid < span[1]]
    assert len(covering) == 1
    left, right = covering[0]
    assert abs((left + right) / 2.0 - mid) < 0.5


def test_slot_layout_puts_one_bar_per_field_knot() -> None:
    spans = bar_spans(1400, BarStyle(count=65, fill=0.55, align="slots", n_slots=65))
    assert len(spans) == 65
    centers = [(a + b) / 2.0 for a, b in spans]
    assert abs(centers[0] - 0.0) < 1e-6
    assert abs(centers[-1] - 1399.0) < 1e-6
    assert abs(centers[32] - 699.5) < 1e-6


def test_bar_height_follows_field_amplitude() -> None:
    columns = [0.2] * 20 + [1.0] * 20 + [0.2] * 40
    frame = draw_mirrored_bars_alpha(
        columns,
        width=80,
        height=48,
        style=BarStyle(width=4, gap=2),
        amplitude=1.0,
        center_line=False,
        supersample=1,
        glow_sigma=0.0,
    )

    def column_mass(x: int) -> int:
        return sum(frame[y * 80 + x] for y in range(48))

    peak_x = 28
    side_x = 8
    assert column_mass(peak_x) > column_mass(side_x) * 2


def test_alternate_bars_use_two_rgb_colors() -> None:
    columns = [1.0] * 64
    frame = draw_mirrored_bars_rgba(
        columns,
        width=64,
        height=32,
        style=BarStyle(count=8, fill=0.5, align="count", alternate=True, color_b="#112233"),
        color="#C7E6EC",
        amplitude=1.0,
        center_line=False,
        supersample=1,
        glow_sigma=0.0,
    )
    colors = {
        (frame[i], frame[i + 1], frame[i + 2]) for i in range(0, len(frame), 4) if frame[i + 3] > 0
    }
    assert (0xC7, 0xE6, 0xEC) in colors
    assert (0x11, 0x22, 0x33) in colors


def test_center_line_width_spans_full_row() -> None:
    columns = [0.2] * 40
    frame = draw_mirrored_bars_alpha(
        columns,
        width=40,
        height=24,
        style=BarStyle(count=5, fill=0.4, align="count", center_line_width=2.0),
        amplitude=1.0,
        center_line=False,
        supersample=1,
        glow_sigma=0.0,
    )
    mid = 12
    row = [frame[mid * 40 + x] for x in range(40)]
    assert min(row) > 0
