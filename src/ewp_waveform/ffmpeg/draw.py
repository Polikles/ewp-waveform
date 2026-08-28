"""Draw RGBA frames for scrolling envelope bars (linia lustrzana family)."""

from __future__ import annotations

from collections.abc import Sequence


def parse_rgb(color: str) -> tuple[int, int, int]:
    raw = color.removeprefix("#")
    if len(raw) != 6:
        msg = f"expected #RRGGBB color, got {color!r}"
        raise ValueError(msg)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def bar_metrics(style: str, stroke_width: float) -> tuple[int, int]:
    stroke = max(1, round(stroke_width or 1.0))
    if style == "segmented":
        return max(stroke, 4), max(stroke, 4)
    if style == "filled":
        return 1, 0
    if style == "classic":
        return max(1, stroke // 2), 2
    return stroke, 1


def glow_vertical_margin(sigma: float) -> int:
    """Keep bar tips inside the frame so gblur does not clip."""
    if sigma <= 0:
        return 1
    return max(2, round(sigma * 2) + 1)


def draw_envelope_frame(
    columns: Sequence[float],
    *,
    width: int,
    height: int,
    color: str,
    amplitude: float,
    stroke_width: float,
    style: str,
    center_line: bool,
    scroll_phase: int = 0,
    vertical_margin: int = 1,
) -> bytes:
    """Mirrored vertical bars. Bar grid is locked to envelope index, not screen x."""
    r, g, b = parse_rgb(color)
    frame = bytearray(width * height * 4)
    center = height // 2
    margin = max(0, vertical_margin)
    usable = min(center, height - center - 1) - margin
    max_half = max(1, round(max(1, usable) * min(max(amplitude, 0.0), 1.0)))
    stroke, gap = bar_metrics(style, stroke_width)
    period = stroke + gap
    if columns:
        if period <= 1:
            xs = range(width)
        else:
            rem = scroll_phase % period
            first = 0 if rem == 0 else period - rem
            xs = range(first, width, period)
        for x in xs:
            mag = columns[x] if x < len(columns) else 0.0
            mag = min(max(mag, 0.0), 1.0)
            half = min(max_half, round(max_half * mag))
            x1 = min(width, x + stroke)
            if half > 0:
                y0 = center - half
                y1 = center + half + 1
                if y0 < 0 or y1 > height:
                    half = min(half, center - margin, height - center - 1 - margin)
                    half = max(0, half)
                    y0 = center - half
                    y1 = center + half + 1
                y0 = max(0, y0)
                y1 = min(height, y1)
                for y in range(y0, y1):
                    row = y * width * 4
                    for px in range(x, x1):
                        off = row + px * 4
                        frame[off] = r
                        frame[off + 1] = g
                        frame[off + 2] = b
                        frame[off + 3] = 255
    if center_line:
        y = min(height - 1, max(0, center))
        row = y * width * 4
        for px in range(width):
            off = row + px * 4
            if frame[off + 3] == 0:
                frame[off] = r
                frame[off + 1] = g
                frame[off + 2] = b
                frame[off + 3] = 140
    return bytes(frame)
