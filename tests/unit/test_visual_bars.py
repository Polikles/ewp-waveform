from ewp_waveform.visual.bars import BarStyle, bar_spans, draw_mirrored_bars_alpha


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
