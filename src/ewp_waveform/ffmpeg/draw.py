"""Draw RGBA frames for scrolling envelope bars (linia lustrzana family)."""

from __future__ import annotations

from collections.abc import Sequence


def parse_rgb(color: str) -> tuple[int, int, int]:
    raw = color.removeprefix("#")
    if len(raw) != 6:
        msg = f"expected #RRGGBB color, got {color!r}"
        raise ValueError(msg)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


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
) -> bytes:
    """Mirrored vertical bars. `columns[x]` is 0..1 for pixel column x."""
    r, g, b = parse_rgb(color)
    frame = bytearray(width * height * 4)
    center = height // 2
    # Leave 1px for glow; amplitude 1.0 uses the full half-height.
    usable = max(1, center - 1)
    max_half = max(1, round(usable * min(max(amplitude, 0.0), 1.0)))
    stroke = max(1, round(stroke_width or 1.0))
    if style == "segmented":
        stroke = max(stroke, 4)
        gap = stroke
    elif style == "filled":
        gap = 0
        stroke = 1
    elif style == "classic":
        gap = 2
        stroke = max(1, stroke // 2)
    else:
        gap = 1
    x = 0
    while x < width:
        idx = min(x, len(columns) - 1) if columns else 0
        mag = columns[idx] if columns else 0.0
        half = int(max_half * min(max(mag, 0.0), 1.0))
        x1 = min(width, x + stroke)
        if half > 0:
            y0 = max(0, center - half)
            y1 = min(height, center + half + 1)
            for y in range(y0, y1):
                row = y * width * 4
                for px in range(x, x1):
                    off = row + px * 4
                    frame[off] = r
                    frame[off + 1] = g
                    frame[off + 2] = b
                    frame[off + 3] = 255
        x += stroke + gap
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
