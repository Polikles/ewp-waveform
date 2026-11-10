from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.application.render_fixed import _ribbon_baseline
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.config.ribbon import apply_public_appearance, ribbon_finish
from ewp_waveform.identity import render_signature


def test_defaults_and_false_zero_precedence() -> None:
    original = load_preset("iuris-ribbon-refined")
    assert ribbon_finish(original) == (0.45, True, 1.0, 0.96, 0.55)
    saved = apply_public_appearance(original, reflection_opacity=0.8, stroke_width=8)
    result = apply_public_appearance(
        saved, reflection_opacity=0, center_line=False, center_line_extent=0, center_line_opacity=0
    )
    assert ribbon_finish(result) == (0, False, 8, 0, 0)
    columns = [0.0] * 40
    assert _ribbon_baseline(columns, result, 16) is columns
    assert ribbon_finish(saved) == (0.8, True, 8, 0.96, 0.55)
    assert resolve_fixed_axis_appearance(result).identity()["mapping_revision"] == 7


@pytest.mark.parametrize("key", ["reflection_opacity", "center_line_extent", "center_line_opacity"])
@pytest.mark.parametrize(
    "value", [-0.001, 1.001, float("nan"), float("inf"), -float("inf"), True, "0.5"]
)
def test_invalid_values_reject(key: str, value: Any) -> None:
    original = load_preset("iuris-ribbon-refined")
    with pytest.raises(ValueError):
        apply_public_appearance(original, **{key: value})
    raw = original.model_dump()
    raw["waveform"][key] = value
    with pytest.raises(ValidationError):
        VisualPreset.model_validate(raw)


@pytest.mark.parametrize("value", [0, 1, "false", "true"])
def test_line_is_strict_boolean(value: Any) -> None:
    with pytest.raises(ValueError):
        apply_public_appearance(load_preset("iuris-ribbon-refined"), center_line=value)


@pytest.mark.parametrize(
    "name", ["iuris-default", "iuris-spectrum", "iuris-ribbon-fixed", "iuris-moving-mouth"]
)
@pytest.mark.parametrize(
    "options",
    [
        {"reflection_opacity": 0},
        {"center_line": False},
        {"center_line_extent": 0},
        {"center_line_opacity": 0},
    ],
)
def test_unsupported_explicit_values_reject(name: str, options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="require"):
        apply_public_appearance(load_preset(name), **options)


@pytest.mark.parametrize(
    "options",
    [
        {"reflection_opacity": 0},
        {"reflection_opacity": 1},
        {"center_line": False},
        {"stroke_width": 2.5},
        {"center_line_extent": 0},
        {"center_line_opacity": 0},
    ],
)
def test_every_appearance_control_enters_standalone_and_recipe_identity(
    options: dict[str, Any],
) -> None:
    original = load_preset("iuris-ribbon-refined")
    modified = apply_public_appearance(original, **options)
    a = resolve_fixed_axis_appearance(original).identity()
    b = resolve_fixed_axis_appearance(modified).identity()
    assert a != b
    assert a["mapping_revision"] == b["mapping_revision"] == 7
    for recipe in [False, True]:

        def sig(p: VisualPreset) -> str:
            return render_signature(
                source_sha256="fixture",
                preset=p,
                fps=60,
                fixed_axis_recipe=resolve_fixed_axis_appearance(p).identity() if recipe else None,
            )

        assert sig(original) != sig(modified)


@pytest.mark.parametrize("command", ["dry-run", "preview", "render"])
def test_cli_forwards_false_zero_and_fractional_thickness(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ewp_waveform.application.service as service

    seen: dict[str, Any] = {}

    class Stop(Exception):
        pass

    def capture(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(service, "plan_jobs" if command == "dry-run" else "render", capture)
    result = CliRunner().invoke(
        app,
        [
            command,
            "input.wav",
            "--preset",
            "iuris-ribbon-refined",
            "--reflection-opacity",
            "0",
            "--no-center-line",
            "--center-line-extent",
            "0",
            "--center-line-opacity",
            "0",
            "--stroke-width",
            "2.5",
        ],
    )
    assert isinstance(result.exception, Stop), result.output
    assert {
        k: seen[k]
        for k in (
            "reflection_opacity",
            "center_line",
            "center_line_extent",
            "center_line_opacity",
            "stroke_width",
        )
    } == {
        "reflection_opacity": 0.0,
        "center_line": False,
        "center_line_extent": 0.0,
        "center_line_opacity": 0.0,
        "stroke_width": 2.5,
    }


def test_missing_line_uses_provisional_filled_default() -> None:
    data = load_preset("iuris-ribbon-refined").model_dump()
    data["waveform"].pop("center_line")
    assert VisualPreset.model_validate(data).waveform.center_line is True
