from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.config.ribbon import apply_public_appearance, ribbon_finish
from ewp_waveform.identity import render_signature


def test_stock_mode_resolves_dark_and_preserves_geometry_and_alpha_settings() -> None:
    original = load_preset("iuris-ribbon-refined")
    result = apply_public_appearance(original, background_mode="light-background")
    assert original.waveform.color == "#C7E6EC"
    assert original.waveform.background_mode == "dark-background"
    assert original.waveform.color_mode == result.waveform.color_mode == "auto"
    assert result.waveform.color == result.effects["glow"]["color"] == "#2F474F"  # type: ignore[index]
    assert original.signal == result.signal
    assert ribbon_finish(original) == ribbon_finish(result)
    a = resolve_fixed_axis_appearance(original)
    b = resolve_fixed_axis_appearance(result)
    assert a.field_plan == b.field_plan and a.motion == b.motion
    ai, bi = a.identity(), b.identity()
    for k in ("background_mode", "foreground_color"):
        assert ai.pop(k) != bi.pop(k)
    assert ai == bi


@pytest.mark.parametrize("color", ["pale_cyan", "#C7E6EC", "slate_teal", "#123456"])
def test_explicit_custom_never_guessed_from_rgb_and_auto_reset(color: str) -> None:
    original = load_preset("iuris-ribbon-refined")
    custom = apply_public_appearance(
        original, background_mode="light-background", waveform_color=color
    )
    assert custom.waveform.color_mode == "custom"
    expected = {"pale_cyan": "#C7E6EC", "slate_teal": "#2F474F"}.get(color, color)
    assert custom.waveform.color == expected
    changed = apply_public_appearance(custom, background_mode="dark-background")
    assert changed.waveform.color == expected and changed.waveform.color_mode == "custom"
    reset = apply_public_appearance(custom, color_mode="auto")
    assert reset.waveform.color == "#2F474F" and reset.waveform.color_mode == "auto"
    assert original.waveform.color_mode == "auto"


def test_saved_custom_policy_old_presets_and_semantic_halo_validation() -> None:
    data = load_preset("iuris-ribbon-refined").model_dump()
    data["waveform"].pop("background_mode")
    data["waveform"].pop("color_mode")
    data["waveform"]["color"] = data["effects"]["glow"]["color"] = "#abcdef"
    old = VisualPreset.model_validate(data)
    assert old.waveform.color_mode == "custom"
    assert (
        apply_public_appearance(old, background_mode="light-background").waveform.color == "#abcdef"
    )
    data["waveform"].update(background_mode="light-background", color_mode="auto")
    auto = VisualPreset.model_validate(data)
    assert auto.waveform.color == auto.effects["glow"]["color"] == "#2F474F"  # type: ignore[index]
    # Both model validation passes must remain coherent; do not mask mismatched tint.
    assert VisualPreset.model_validate(auto.model_dump()) == auto
    data["effects"]["glow"]["color"] = "#999999"
    with pytest.raises(ValueError, match="independent glow color"):
        VisualPreset.model_validate(data)


@pytest.mark.parametrize("key", ["background_mode", "color_mode"])
@pytest.mark.parametrize("value", ["", "automatic", "dark", 1, False, [], {}, float("nan")])
def test_invalid_saved_and_service_modes_reject(key: str, value: Any) -> None:
    original = load_preset("iuris-ribbon-refined")
    with pytest.raises(ValueError):
        apply_public_appearance(original, **{key: value})
    raw = original.model_dump()
    raw["waveform"][key] = value
    with pytest.raises(ValueError):
        VisualPreset.model_validate(raw)


@pytest.mark.parametrize(
    "name", ["iuris-default", "iuris-spectrum", "iuris-ribbon-fixed", "iuris-moving-mouth"]
)
@pytest.mark.parametrize(
    "options",
    [{"background_mode": "dark-background"}, {"color_mode": "auto"}, {"color_mode": "custom"}],
)
def test_unsupported_profiles_reject_explicit_modes(name: str, options: dict[str, Any]) -> None:
    original = load_preset(name)
    assert original.waveform.background_mode is None and original.waveform.color_mode is None
    with pytest.raises(ValueError, match="require"):
        apply_public_appearance(original, **options)
    raw = original.model_dump()
    raw["waveform"].update(options)
    with pytest.raises(ValueError, match="require"):
        VisualPreset.model_validate(raw)


def test_conflicting_auto_and_explicit_color_reject_and_custom_freezes() -> None:
    original = load_preset("iuris-ribbon-refined")
    with pytest.raises(ValueError, match="conflicts"):
        apply_public_appearance(original, color_mode="auto", waveform_color="pale_cyan")
    custom = apply_public_appearance(
        original, color_mode="custom", background_mode="light-background"
    )
    assert custom.waveform.color == "#C7E6EC" and custom.waveform.color_mode == "custom"


@pytest.mark.parametrize(
    "options",
    [
        {"background_mode": "light-background"},
        {"color_mode": "custom"},
        {"background_mode": "light-background", "waveform_color": "pale_cyan"},
    ],
)
def test_mode_and_policy_are_in_both_identities_even_with_equal_rgb(
    options: dict[str, Any],
) -> None:
    original = load_preset("iuris-ribbon-refined")
    modified = apply_public_appearance(original, **options)
    assert (
        resolve_fixed_axis_appearance(original).identity()
        != resolve_fixed_axis_appearance(modified).identity()
    )
    recipes: list[dict[str, Any] | None] = [None, {}]
    for recipe in recipes:
        assert render_signature(
            source_sha256="fixture", preset=original, fps=60, fixed_axis_recipe=recipe
        ) != render_signature(
            source_sha256="fixture", preset=modified, fps=60, fixed_axis_recipe=recipe
        )


@pytest.mark.parametrize("command", ["dry-run", "preview", "render"])
def test_cli_modes_and_custom_color_are_forwarded(
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
            "--background-mode",
            "light-background",
            "--color-mode",
            "custom",
            "--waveform-color",
            "pale_cyan",
        ],
    )
    assert isinstance(result.exception, Stop), result.output
    assert seen["background_mode"] == "light-background"
    assert seen["color_mode"] == "custom" and seen["waveform_color"] == "pale_cyan"


@pytest.mark.parametrize("color", ["invalid", "#12345", 123])
def test_auto_does_not_mask_invalid_saved_colors(color: Any) -> None:
    raw = load_preset("iuris-ribbon-refined").model_dump()
    raw["waveform"]["color"] = raw["effects"]["glow"]["color"] = color
    with pytest.raises(ValueError, match=r"waveform\.color"):
        VisualPreset.model_validate(raw)
