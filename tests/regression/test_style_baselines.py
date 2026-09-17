from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast

from ewp_waveform.config.models import CanvasSection, VisualPreset, WaveformSection
from ewp_waveform.ffmpeg.draw import (
    CLASSIC_SCROLL_ALTERNATE_OPACITY,
    draw_envelope_frame,
)
from ewp_waveform.visual.plan import resolve_render_plan
from ewp_waveform.visual.raster import raster_field_columns
from ewp_waveform.visual.style_defaults import default_bar_style

FIXTURE = Path(__file__).parents[1] / "fixtures" / "visual" / "style-baseline-v13.json"
FIELD_GEOMETRY = {
    "classic": "classic_ticks",
    "mirrored": "mirrored_bars",
    "filled": "ribbon",
    "segmented": "segmented_impulse",
}


class ExpectedHashes(TypedDict):
    time_scroll: dict[str, str]
    fixed_axis: dict[str, str]


class StyleBaselineFixture(TypedDict):
    visual_contract_version: int
    width: int
    height: int
    color: str
    amplitude: float
    columns: list[float]
    expected_sha256: ExpectedHashes


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture() -> StyleBaselineFixture:
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast(StyleBaselineFixture, loaded)


def test_time_scroll_style_raster_baseline() -> None:
    fixture = _fixture()
    columns = fixture["columns"]
    expected = fixture["expected_sha256"]
    hashes = expected["time_scroll"]
    for style in FIELD_GEOMETRY:
        frame = draw_envelope_frame(
            columns,
            width=int(fixture["width"]),
            height=int(fixture["height"]),
            color=str(fixture["color"]),
            amplitude=float(fixture["amplitude"]),
            stroke_width=6.0,
            style=style,
            center_line=True,
            supersample=2,
            classic_alternate_opacity=CLASSIC_SCROLL_ALTERNATE_OPACITY,
        )
        assert _digest(frame) == hashes[style]


def test_fixed_axis_style_raster_baseline() -> None:
    fixture = _fixture()
    columns = fixture["columns"]
    expected = fixture["expected_sha256"]
    hashes = expected["fixed_axis"]
    preset = VisualPreset(
        schema_version=1,
        name="style-regression",
        canvas=CanvasSection(
            width=int(fixture["width"]),
            height=int(fixture["height"]),
            fps=60,
        ),
        waveform=WaveformSection(
            style="mirrored",
            domain="frequency",
            color=str(fixture["color"]),
            amplitude=float(fixture["amplitude"]),
            center_line=True,
        ),
        effects={"glow": {"enabled": False}, "particles": {"enabled": False}},
    )
    for style, geometry in FIELD_GEOMETRY.items():
        bar_style = default_bar_style(geometry)
        plan = resolve_render_plan(
            preset,
            layout="field_center_out",
            field_geometry=geometry,
            ribbon_supersample=2,
            alternate_bars=bar_style.alternate,
        )
        frame = raster_field_columns(
            columns,
            plan=plan,
            width=int(fixture["width"]),
            height=int(fixture["height"]),
            color=str(fixture["color"]),
            amplitude=float(fixture["amplitude"]),
            center_line=geometry == "ribbon",
            bar_style=bar_style,
        )
        assert _digest(frame) == hashes[style]
