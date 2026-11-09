"""Focused synthetic boundaries for vectorized gapless span preparation/edges."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
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


def _boundaries(height: int) -> list[tuple[float, float]]:
    bounds = [
        (-1e300, 1e300),
        (-1e300, -1e300),
        (1e300, 1e300),
        (-10.0, -1.0),
        (float(height) + 1.0, float(height) + 2.0),
        (-1.25, 0.25),
        (float(height) - 0.25, float(height) + 2.0),
        (0.25, 0.75),
        (0.25, 1.25),
        (0.75, 1.75),
        (1.0, 1.0),
        (2.5, 0.25),
        (-0.0, 0.0),
    ]
    for integer in (0, 1, 2, 63, 64, 65, height):
        edge = float(integer)
        for value in (math.nextafter(edge, -math.inf), edge, math.nextafter(edge, math.inf)):
            bounds.extend(((value, value + 2.0), (value - 2.0, value)))
    for coverage in (0.5 / 255, 1.5 / 255, 126.5 / 255, 127.5 / 255, 1.0 - 1e-6):
        for value in (
            math.nextafter(coverage, -math.inf),
            coverage,
            math.nextafter(coverage, math.inf),
        ):
            # At origin, on either side of a full interior, and without full rows.
            bounds.extend(((0.0, value), (0.0, 2.0 + value), (1.0 - value, 3.0)))
    rng = random.Random(411 + height)
    bounds.extend((rng.uniform(-4, height + 4), rng.uniform(-4, height + 4)) for _ in range(156))
    return bounds


@pytest.mark.parametrize("height", [1, 2, 7, 63, 64, 65, 129])
@pytest.mark.parametrize("seed_alpha", [None, 0, 1, 128, 254, 255])
def test_vector_edges_exact_on_boundary_and_random_spans(
    monkeypatch: pytest.MonkeyPatch, height: int, seed_alpha: int | None
) -> None:
    bounds = _boundaries(height)
    assert len(bounds) >= 256
    width = 2 * len(bounds) + 1
    spans = [(2 * x, y0, y1) for x, (y0, y1) in enumerate(bounds)]
    rng = random.Random(8128 + height)
    frame = bytearray(rng.randbytes(width * height * 4))
    if seed_alpha is not None:
        frame[3::4] = bytes([seed_alpha]) * (width * height)
    expected = bytearray(frame)
    _scalar_gapless(expected, width=width, height=height, spans=spans, r=17, g=29, b=43)

    def forbidden_scalar(*args: Any, **kwargs: Any) -> None:
        pytest.fail("eligible boundary batches must use vector edges")

    monkeypatch.setattr(draw, "_put_span", forbidden_scalar)
    with np.errstate(all="raise"):
        draw._put_gapless_spans(frame, width=width, height=height, spans=spans, r=17, g=29, b=43)
    assert frame == expected


@pytest.mark.parametrize("width", [1, 2, 137, 255, 256])
def test_small_eligible_batches_also_vectorize_edges(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    spans = [(x, 0.25, 3.75) for x in range(width)]
    frame = bytearray(bytes((80, 81, 82, 128)) * width * 4)
    expected = bytearray(frame)
    _scalar_gapless(expected, width=width, height=4, spans=spans, r=1, g=2, b=3)

    def forbidden_scalar(*args: Any, **kwargs: Any) -> None:
        pytest.fail("eligible production edges must not retain obsolete scalar instrumentation")

    monkeypatch.setattr(draw, "_put_span", forbidden_scalar)
    draw._put_gapless_spans(frame, width=width, height=4, spans=spans, r=1, g=2, b=3)
    assert frame == expected


@pytest.mark.parametrize("seed_alpha", [0, 128, 255])
def test_vector_edges_all_half_alpha_steps_and_neighbors(seed_alpha: int) -> None:
    bounds = []
    for half_step in range(255):
        coverage = (half_step + 0.5) / 255.0
        for value in (
            math.nextafter(coverage, -math.inf),
            coverage,
            math.nextafter(coverage, math.inf),
        ):
            bounds.extend(((0.0, value), (0.0, 2.0 + value), (1.0 - value, 3.0)))
    width, height = len(bounds), 4
    spans = [(x, y0, y1) for x, (y0, y1) in enumerate(bounds)]
    frame = bytearray(bytes((80, 81, 82, seed_alpha)) * width * height)
    expected = bytearray(frame)
    _scalar_gapless(expected, width=width, height=height, spans=spans, r=1, g=2, b=3)
    with np.errstate(all="raise"):
        draw._put_gapless_spans(frame, width=width, height=height, spans=spans, r=1, g=2, b=3)
    assert frame == expected


def test_vector_edges_retain_rgb_ties_and_nearfull_overwrite() -> None:
    width, height = 256, 4
    # Upper and lower fractional alpha ties keep old RGB; opaque ties overwrite.
    frame = bytearray(bytes((80, 81, 82, 128)) * width * height)
    frame[width * 4 : 2 * width * 4] = bytes((90, 91, 92, 255)) * width
    spans = [(x, 0.5, 2.5) for x in range(width)]
    draw._put_gapless_spans(frame, width=width, height=height, spans=spans, r=1, g=2, b=3)
    assert frame[: width * 4] == bytes((80, 81, 82, 128)) * width
    assert frame[width * 4 : 2 * width * 4] == bytes((1, 2, 3, 255)) * width
    assert frame[2 * width * 4 :] == bytes((80, 81, 82, 128)) * (2 * width)
    spans = [(x, 0.0, 1.0 - 1e-6) for x in range(width)]
    frame = bytearray(bytes((80, 81, 82, 255)) * width * height)
    draw._put_gapless_spans(frame, width=width, height=height, spans=spans, r=1, g=2, b=3)
    assert frame[: width * 4] == bytes((1, 2, 3, 255)) * width


def test_vector_edges_use_single_view_bounded_tiles_and_no_scalar_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frombuffer, copyto = np.frombuffer, np.copyto
    views: list[int] = []
    tiles: list[int] = []

    def view(*args: Any, **kwargs: Any) -> Any:
        views.append(1)
        return frombuffer(*args, **kwargs)

    def tile(dst: Any, src: Any, **kwargs: Any) -> None:
        tiles.append(dst.shape[0])
        copyto(dst, src, **kwargs)

    def forbidden_scalar(*args: Any, **kwargs: Any) -> None:
        pytest.fail("eligible batches must not call scalar edges")

    monkeypatch.setattr(np, "frombuffer", view)
    monkeypatch.setattr(np, "copyto", tile)
    monkeypatch.setattr(draw, "_put_span", forbidden_scalar)
    frame = bytearray(256 * 129 * 4)
    draw._put_gapless_spans(
        frame, width=256, height=129, spans=[(x, 0.25, 128.75) for x in range(256)], r=1, g=2, b=3
    )
    assert views == [1]
    assert tiles == [64, 64, 1]
    assert frame[(64 * 256 + 50) * 4 : (64 * 256 + 50) * 4 + 4] == bytes((1, 2, 3, 255))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("lower", [False, True])
@pytest.mark.parametrize("position", [0, 129, 255])
def test_large_nonfinite_batch_preserves_exception_and_prefix(
    bad: float, lower: bool, position: int
) -> None:
    spans = [(x, 0.25, 2.75) for x in range(256)]
    spans[position] = (position, bad if lower else 0.0, 2.0 if lower else bad)
    frames = [bytearray(256 * 3 * 4) for _ in range(2)]
    errors = []
    for function, frame in zip((_scalar_gapless, draw._put_gapless_spans), frames, strict=True):
        with pytest.raises((ValueError, OverflowError)) as exc:
            function(frame, width=256, height=3, spans=spans, r=17, g=29, b=43)
        errors.append((type(exc.value), str(exc.value)))
    assert errors[0] == errors[1]
    assert frames[0] == frames[1]


@pytest.mark.parametrize("case", ["list_entry", "unordered", "duplicate", "integer_bounds"])
def test_ineligible_batches_retain_scalar_edge_path(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    spans: list[Any] = [(x, 0.25, 3.75) for x in range(256)]
    if case == "list_entry":
        spans[129] = list(spans[129])
    elif case == "unordered":
        spans.reverse()
    elif case == "duplicate":
        spans[129] = spans[128]
    elif case == "integer_bounds":
        spans[129] = (129, 0, 4)
    scalar = draw._put_span
    calls: list[tuple[float, float]] = []

    def record(frame: bytearray, **kwargs: Any) -> None:
        calls.append((kwargs["y0"], kwargs["y1"]))
        scalar(frame, **kwargs)

    expected = bytearray(256 * 4 * 4)
    _scalar_gapless(expected, width=256, height=4, spans=spans, r=17, g=29, b=43)
    monkeypatch.setattr(draw, "_put_span", record)
    frame = bytearray(256 * 4 * 4)
    draw._put_gapless_spans(frame, width=256, height=4, spans=spans, r=17, g=29, b=43)
    assert calls
    assert frame == expected
