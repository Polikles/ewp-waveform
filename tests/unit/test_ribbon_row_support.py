from __future__ import annotations

import pytest

from ewp_waveform.ffmpeg.ribbon import ribbon_graph


def _expression(height: int, finish: tuple[float, bool, float, float, float]) -> str:
    graph = ribbon_graph(
        width=18,
        height=height,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=0,
        finish=finish,
    )
    return graph.split("geq=lum='", 1)[1].split("'", 1)[0]


def _legacy(height: int, finish: tuple[float, bool, float, float, float]) -> str:
    reflection, enabled, thickness, extent, opacity = finish
    left, right = 18 * (1 - extent) / 2, 18 * (1 + extent) / 2
    cy = height // 2 + 0.5
    top, bottom = cy - thickness / 2, cy + thickness / 2
    line = "0"
    if enabled and extent > 0 and opacity > 0:
        line = (
            f"({opacity}*clip(min(X+1,{right})-max(X,{left}),0,1)"
            f"*clip(min(Y+1,{bottom})-max(Y,{top}),0,1))"
        )
    return f"255*{line}+(lum(X,Y)*if(gt(Y,{height // 2}),{reflection},1))*(1-{line})"


@pytest.mark.parametrize(
    ("height", "thickness", "first", "last"),
    [
        (16, 1.0, 8, 8),
        (17, 1.0, 8, 8),
        (16, 0.25, 8, 8),
        (17, 2.0, 7, 9),
        (16, 2.5, 7, 9),
        (17, 3.0, 7, 9),
        (16, 15.0, 1, 15),
    ],
)
def test_guard_retains_original_arithmetic_and_exact_support(
    height: int,
    thickness: float,
    first: int,
    last: int,
) -> None:
    finish = (0.45, True, thickness, 0.73, 0.55)
    body = f"lum(X,Y)*if(gt(Y,{height // 2}),0.45,1)"
    assert _expression(height, finish) == (
        f"if(between(Y,{first},{last}),{_legacy(height, finish)},{body})"
    )
    # No interpolation option, nearest-neighbor shortcut or change of lum sampler.
    assert "interpolation=" not in _expression(height, finish)


@pytest.mark.parametrize(
    "finish",
    [
        (0.45, False, 2.5, 0.73, 0.55),
        (0.0, True, 2.5, 0.0, 0.55),
        (1.0, True, 2.5, 0.73, 0.0),
        (0.45, True, 0.0, 0.73, 0.55),
        (0.45, True, 16.0, 0.73, 0.55),
        (0.45, True, 32.0, 1.0, 1.0),
    ],
)
def test_no_gain_cases_keep_legacy_expression(
    finish: tuple[float, bool, float, float, float],
) -> None:
    assert _expression(16, finish) == _legacy(16, finish)
