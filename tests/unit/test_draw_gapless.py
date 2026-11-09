"""Synthetic exact oracles for the gapless column raster specialization."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import ewp_waveform.ffmpeg.draw as draw


def _scalar_put_span(
    frame: bytearray,
    *,
    width: int,
    height: int,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    r: int,
    g: int,
    b: int,
    opacity: float = 1.0,
) -> None:
    """Frozen scalar oracle, including zero opacity and asymmetric alpha ties."""
    px0 = max(0, math.floor(x0))
    px1 = min(width, math.ceil(x1))
    py0 = max(0, math.floor(y0))
    py1 = min(height, math.ceil(y1))
    for px in range(px0, px1):
        xcov = min(float(px) + 1.0, x1) - max(float(px), x0)
        if xcov <= 0.0:
            continue
        xcov = min(1.0, xcov)
        for py in range(py0, py1):
            ycov = min(float(py) + 1.0, y1) - max(float(py), y0)
            if ycov <= 0.0:
                continue
            cov = xcov * min(1.0, ycov) * min(max(float(opacity), 0.0), 1.0)
            alpha = 255 if cov >= 1.0 - 1e-6 else max(1, min(255, round(255.0 * cov)))
            off = (py * width + px) * 4
            if alpha >= 255 or frame[off + 3] < alpha:
                frame[off] = r
                frame[off + 1] = g
                frame[off + 2] = b
                frame[off + 3] = alpha if alpha >= 255 else max(frame[off + 3], alpha)


def _scalar_gapless(
    frame: bytearray,
    *,
    width: int,
    height: int,
    spans: Sequence[tuple[int, float, float]],
    r: int,
    g: int,
    b: int,
) -> None:
    for x, y0, y1 in spans:
        _scalar_put_span(
            frame,
            width=width,
            height=height,
            x0=float(x),
            x1=float(x + 1),
            y0=y0,
            y1=y1,
            r=r,
            g=g,
            b=b,
        )


@pytest.mark.parametrize("height", [0, 1, 2, 7, 63, 64, 65, 129])
def test_gapless_exact_on_clipped_fractional_and_degenerate_spans(height: int) -> None:
    rng = random.Random(8128 + height)
    bounds = [
        (-10.0, -1.0),
        (-1.25, 0.25),
        (0.0, float(height)),
        (0.25, 0.75),
        (0.25, 1.25),
        (1.0, 1.0),
        (2.5, 0.25),
        (-1e300, 1e300),
        (1e300, 1e300),
        (-1e300, -1e300),
        (float(height) - 0.25, float(height) + 2.0),
    ]
    for integer in range(height + 1):
        edge = float(integer)
        for value in (math.nextafter(edge, -math.inf), edge, math.nextafter(edge, math.inf)):
            bounds.extend(((value, value + 2.0), (value - 2.0, value)))
    for coverage in (0.5 / 255, 1.5 / 255, 126.5 / 255, 1.0 - 1e-6):
        for value in (
            math.nextafter(coverage, -math.inf),
            coverage,
            math.nextafter(coverage, math.inf),
        ):
            bounds.append((0.0, 2.0 + value))
    bounds.extend((rng.uniform(-4, height + 4), rng.uniform(-4, height + 4)) for _ in range(80))
    width = len(bounds) + 2
    spans = [(x, y0, y1) for x, (y0, y1) in enumerate(bounds)]
    rng.shuffle(spans)  # Disjoint X permits any submission order, including sparse X.
    for seed_alpha in (None, 0, 1, 128, 254, 255):
        frame = bytearray(rng.randbytes(width * height * 4))
        if seed_alpha is not None:
            frame[3::4] = bytes([seed_alpha]) * (width * height)
        expected = bytearray(frame)
        _scalar_gapless(expected, width=width, height=height, spans=spans, r=17, g=29, b=43)
        draw._put_gapless_spans(frame, width=width, height=height, spans=spans, r=17, g=29, b=43)
        assert frame == expected


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("lower", [False, True])
def test_gapless_nonfinite_preserves_scalar_error_and_prefix(bad: float, lower: bool) -> None:
    spans = [(0, 0.25, 2.75), (1, bad if lower else 0.0, 2.0 if lower else bad)]
    frames = [bytearray(3 * 3 * 4) for _ in range(2)]
    errors = []
    for function, frame in zip((_scalar_gapless, draw._put_gapless_spans), frames, strict=True):
        with pytest.raises((ValueError, OverflowError)) as exc:
            function(frame, width=3, height=3, spans=spans, r=17, g=29, b=43)
        errors.append(type(exc.value))
    assert errors[0] is errors[1]
    assert frames[0] == frames[1]


def test_gapless_overwrites_opaque_ties_but_keeps_partial_rgb_ties() -> None:
    frame = bytearray(bytes((80, 81, 82, 128)) * 3)
    frame[4:8] = bytes((90, 91, 92, 255))
    draw._put_gapless_spans(
        frame,
        width=1,
        height=3,
        spans=[(0, 0.5, 2.5)],
        r=1,
        g=2,
        b=3,
    )
    assert frame == bytes((80, 81, 82, 128, 1, 2, 3, 255, 80, 81, 82, 128))


def test_gapless_batches_full_rows_without_scalar_interior_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scalar = draw._put_span
    copyto = np.copyto
    frombuffer = np.frombuffer
    scalar_calls: list[tuple[float, float]] = []
    tile_rows: list[int] = []
    views = 0

    def edge_only(frame: bytearray, **kwargs: Any) -> None:
        y0, y1 = kwargs["y0"], kwargs["y1"]
        assert math.floor(y1) <= math.ceil(y0)
        scalar_calls.append((y0, y1))
        scalar(frame, **kwargs)

    def copy_tile(dst: Any, src: Any, **kwargs: Any) -> None:
        tile_rows.append(dst.shape[0])
        copyto(dst, src, **kwargs)

    def frame_view(*args: Any, **kwargs: Any) -> Any:
        nonlocal views
        views += 1
        return frombuffer(*args, **kwargs)

    monkeypatch.setattr(draw, "_put_span", edge_only)
    monkeypatch.setattr(np, "copyto", copy_tile)
    monkeypatch.setattr(np, "frombuffer", frame_view)
    width, height = 137, 129
    frame = bytearray(width * height * 4)
    draw._put_gapless_spans(
        frame,
        width=width,
        height=height,
        spans=[(x, 0.25, 128.75) for x in range(width)],
        r=1,
        g=2,
        b=3,
    )
    assert len(scalar_calls) == 2 * width
    assert tile_rows == [64, 64, 1]
    assert views == 1
    assert frame[(64 * width + 50) * 4 : (64 * width + 50) * 4 + 4] == bytes((1, 2, 3, 255))


@pytest.mark.parametrize("style", ["mirrored", "filled", "classic", "segmented", "unknown"])
def test_envelope_exact_against_scalar_batch_replacement(
    monkeypatch: pytest.MonkeyPatch,
    style: str,
) -> None:
    batch = draw._put_gapless_spans
    rng = random.Random(551)
    columns_cases = [[], [0.0], [1.0], [-0.5, 0.0, 1e-12, 0.5, 1.5, math.nan]]
    columns_cases.append([rng.uniform(-0.25, 1.25) for _ in range(13)])
    for ss, phase, center_line, glow in product(
        (1, 2, 12), (-1.5, 0.0, 1 / 3), (False, True), (0.0, 1.25)
    ):
        kwargs: dict[str, Any] = dict(
            width=11,
            height=19,
            color="#6E7BA7",
            amplitude=0.82,
            stroke_width=3.0,
            style=style,
            center_line=center_line,
            scroll_phase=phase,
            content_height=13,
            supersample=ss,
            glow_sigma=glow,
            envelope_oversample=4,
            classic_alternate_opacity=0.25,
        )
        for columns in columns_cases:
            monkeypatch.setattr(draw, "_put_gapless_spans", _scalar_gapless)
            expected = draw.draw_envelope_frame(columns, **kwargs)
            monkeypatch.setattr(draw, "_put_gapless_spans", batch)
            assert draw.draw_envelope_frame(columns, **kwargs) == expected


@pytest.mark.parametrize(
    "opacity", [-math.inf, -1.0, 0.0, 1e-300, 0.25, 0.5, 1.0, 2.0, math.inf, math.nan]
)
def test_general_scalar_geometry_opacity_and_overlap_are_unchanged(opacity: float) -> None:
    rng = random.Random(455)
    frames = [bytearray(rng.randbytes(5 * 7 * 4))]
    frames.append(bytearray(frames[0]))
    rectangles: list[tuple[float, ...]] = [
        (-0.25, 3.25, -1.5, 4.25),
        (0.0, 5.0, 0.0, 7.0),
        (2.0, 1.0, 0.0, 7.0),
        (0.0, 5.0, 4.0, 2.0),
        (1.25, 1.75, 2.25, 2.75),
        (8.0, 9.0, 0.0, 7.0),
    ]
    rectangles.extend(tuple(rng.uniform(-2, 9) for _ in range(4)) for _ in range(80))
    for i, (x0, x1, y0, y1) in enumerate(rectangles):
        outcomes: list[type[Exception] | None] = []
        for function, frame in zip((_scalar_put_span, draw._put_span), frames, strict=True):
            try:
                function(
                    frame,
                    width=5,
                    height=7,
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    y1=y1,
                    r=i % 256,
                    g=17,
                    b=255 - i % 256,
                    opacity=opacity,
                )
            except (ValueError, OverflowError) as exc:
                outcomes.append(type(exc))
            else:
                outcomes.append(None)
        assert outcomes[0] is outcomes[1]
        assert frames[0] == frames[1]


def test_legacy_fixed_axis_production_iterator_uses_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the actual legacy iterator with synthetic analysis; never open media.
    import importlib

    from ewp_waveform.analysis.spectrum import FrequencySpan
    from ewp_waveform.config.load import load_preset

    render = importlib.import_module("ewp_waveform.application.render")
    batch = draw._put_gapless_spans
    calls: list[int] = []

    def record(frame: bytearray, **kwargs: Any) -> None:
        calls.append(len(kwargs["spans"]))
        batch(frame, **kwargs)

    preset = load_preset("iuris-spectrum")
    preset = preset.model_copy(
        update={"canvas": preset.canvas.model_copy(update={"width": 17, "height": 19})}
    )
    monkeypatch.setattr(render, "spectrum_columns", lambda *args, **kwargs: [0.25, 0.5, 1.0] * 6)
    monkeypatch.setattr(render, "draw_envelope_frame", draw.draw_envelope_frame)
    monkeypatch.setattr(draw, "_put_gapless_spans", record)
    kwargs: dict[str, Any] = dict(
        n_frames=3,
        preset=preset,
        fps=60.0,
        glow=0.0,
        span=FrequencySpan(fmin_hz=20.0, fmax_hz=2000.0, source="auto"),
        peak=None,
        scale="sqrt",
        tau_seconds=0.0,
        soft_clip=False,
    )
    actual = list(render.iter_spectrum_frames(Path("never-opened.wav"), **kwargs))
    assert calls == [34, 34, 34]
    monkeypatch.setattr(draw, "_put_gapless_spans", _scalar_gapless)
    expected = list(render.iter_spectrum_frames(Path("never-opened.wav"), **kwargs))
    assert actual == expected
    assert len(actual[0]) == 17 * 2 * 19 * 4


def test_general_span_zero_opacity_and_rgb_tie_contract() -> None:
    frame = bytearray(4)
    draw._put_span(
        frame, width=1, height=1, x0=0.0, x1=1.0, y0=0.0, y1=1.0, r=1, g=2, b=3, opacity=0.0
    )
    assert frame == bytes((1, 2, 3, 1))
    draw._put_span(
        frame, width=1, height=1, x0=0.0, x1=1.0, y0=0.0, y1=1.0, r=4, g=5, b=6, opacity=0.0
    )
    assert frame == bytes((1, 2, 3, 1))
    draw._put_span(frame, width=1, height=1, x0=0.0, x1=1.0, y0=0.0, y1=1.0, r=4, g=5, b=6)
    assert frame == bytes((4, 5, 6, 255))
    draw._put_span(frame, width=1, height=1, x0=0.0, x1=1.0, y0=0.0, y1=1.0, r=7, g=8, b=9)
    assert frame == bytes((7, 8, 9, 255))
