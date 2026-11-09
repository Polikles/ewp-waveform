"""Validated refined-ribbon appearance, shared by config, service and future UI."""

from __future__ import annotations

import math
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ewp_waveform.config.models import VisualPreset

REFINED_RIBBON = "filled-ribbon-v2"
BRAND_COLORS = MappingProxyType(
    {
        "steel_blue": "#3D5D73",
        "periwinkle_blue": "#6E7BA7",
        "slate_teal": "#2F474F",
        "pale_cyan": "#C7E6EC",
        "soft_yellow": "#F2C558",
    }
)
# Fixed 64-band analysis for every detail. (band sigma, coarse mix, contrast, spatial scale).
DETAIL_SETTINGS = MappingProxyType(
    {
        "smooth": (2.6, 0.65, 1.15, 1.2),
        "balanced": (1.2, 0.30, 1.6, 0.45),
        "detailed": (0.45, 0.08, 1.95, 0.18),
    }
)


def resolve_color(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("waveform_color must be a brand color name or #RRGGBB")
    resolved = BRAND_COLORS.get(value, value)
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", resolved) is None:
        raise ValueError("waveform_color must be a brand color name or #RRGGBB")
    return resolved


def _number(value: object, key: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{key} must be in [{minimum}, {maximum}]")
    return result


def _keys(value: object, allowed: set[str], path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unsupported {path} setting(s): {', '.join(sorted(unknown))}")


def validate_refined_data(data: Any) -> Any:
    """Strictness is opt-in: never change legacy preset parsing/defaults."""
    if not isinstance(data, dict):
        return data
    signal = data.get("signal", {})
    if not isinstance(signal, dict):
        return data
    profile = signal.get("fixed_axis_profile")
    if "detail_level" in signal and profile != REFINED_RIBBON:
        raise ValueError("signal.detail_level requires filled-ribbon-v2")
    if profile != REFINED_RIBBON:
        return data
    _keys(
        data,
        {
            "schema_version",
            "name",
            "description",
            "canvas",
            "waveform",
            "signal",
            "effects",
            "palette",
        },
        "preset",
    )
    _keys(data.get("canvas"), {"width", "height", "fps"}, "canvas")
    _keys(
        data.get("waveform"),
        {
            "style",
            "domain",
            "color",
            "amplitude",
            "stroke_width",
            "center_line",
            "time_mode",
            "window_seconds",
        },
        "waveform",
    )
    _keys(
        signal,
        {"fixed_axis_profile", "detail_level", "scale", "smoothing", "normalization", "frequency"},
        "signal",
    )
    wave = data["waveform"]
    if wave.get("domain") != "frequency" or wave.get("style") != "filled":
        raise ValueError("filled-ribbon-v2 requires waveform.domain=frequency and style=filled")
    if wave.get("time_mode") is not None or wave.get("window_seconds", 5.0) != 5.0:
        raise ValueError("filled-ribbon-v2 does not support time/window controls")
    if (
        not isinstance(wave.get("color"), str)
        or re.fullmatch(r"#[0-9A-Fa-f]{6}", wave["color"]) is None
    ):
        raise ValueError("waveform.color must be #RRGGBB; service/CLI also resolve brand names")
    _number(wave.get("amplitude"), "waveform.amplitude", 0.01, 1.0)
    thickness = wave.get("stroke_width")
    if thickness is not None:
        _number(thickness, "waveform.stroke_width", 1.0, 12.0)
        if wave.get("center_line") is not True:
            raise ValueError("ribbon stroke_width requires center_line=true")
    detail = signal.get("detail_level", "balanced")
    if not isinstance(detail, str) or detail not in DETAIL_SETTINGS:
        raise ValueError("detail_level must be smooth, balanced or detailed")
    if signal.get("scale", "sqrt") not in ("linear", "sqrt", "cbrt", "log"):
        raise ValueError("Unsupported signal.scale")
    _number(signal.get("smoothing", 0.0), "signal.smoothing", 0.0, 0.5)
    norm = signal.get("normalization", {})
    _keys(norm, {"mode", "soft_clip"}, "signal.normalization")
    if norm.get("mode") not in ("auto", "none") or not isinstance(
        norm.get("soft_clip", False), bool
    ):
        raise ValueError("ribbon normalization supports auto/none and boolean soft_clip")
    freq = signal.get("frequency", {})
    _keys(freq, {"range", "fmin_hz", "fmax_hz"}, "signal.frequency")
    if freq.get("range", "auto") != "auto":
        raise ValueError("refined ribbon supports frequency.range=auto or explicit Hz bounds")
    for key in ("fmin_hz", "fmax_hz"):
        if key in freq:
            _number(freq[key], key, 0.01, 192000.0)
    if "fmin_hz" in freq and "fmax_hz" in freq and freq["fmin_hz"] >= freq["fmax_hz"]:
        raise ValueError("fmin_hz must be less than fmax_hz")
    effects = data.get("effects", {})
    _keys(effects, {"glow", "particles"}, "effects")
    glow = effects.get("glow", {})
    _keys(glow, {"enabled", "level", "color"}, "effects.glow")
    if glow.get("level") not in ("none", "low", "medium", "high"):
        raise ValueError("glow_level must be none, low, medium or high")
    if glow.get("enabled") is not (glow.get("level") != "none"):
        raise ValueError("glow.enabled must agree with glow.level")
    if glow.get("color", wave["color"]) != wave["color"]:
        raise ValueError("independent glow color is unsupported; use waveform.color")
    particles = effects.get("particles", {"enabled": False})
    _keys(particles, {"enabled"}, "effects.particles")
    if particles.get("enabled") is not False:
        raise ValueError("refined ribbon does not support particles")
    return data


def apply_public_appearance(
    preset: VisualPreset,
    *,
    detail_level: str | None = None,
    waveform_color: str | None = None,
    glow_level: str | None = None,
    amplitude: float | None = None,
    stroke_width: float | None = None,
) -> VisualPreset:
    """Explicit overrides beat preset defaults, on a fully validated private copy."""
    from ewp_waveform.config.models import VisualPreset

    refined = preset.signal.get("fixed_axis_profile") == REFINED_RIBBON
    if not refined and any(x is not None for x in (detail_level, amplitude, stroke_width)):
        raise ValueError("New detail/height/thickness overrides require filled-ribbon-v2")
    if all(x is None for x in (detail_level, waveform_color, glow_level, amplitude, stroke_width)):
        preset.validate_fixed_axis_profile()
        return preset
    data = preset.model_dump()
    if detail_level is not None:
        data["signal"]["detail_level"] = detail_level
    if amplitude is not None:
        _number(amplitude, "amplitude", 0.01, 1.0)
        data["waveform"]["amplitude"] = amplitude
    if stroke_width is not None:
        _number(stroke_width, "stroke_width", 1.0, 12.0)
        data["waveform"]["stroke_width"] = stroke_width
    if waveform_color is not None:
        color = resolve_color(waveform_color)
        data["waveform"]["color"] = color
        glow = data["effects"].get("glow")
        if isinstance(glow, dict):
            glow["color"] = color
    if glow_level is not None:
        if glow_level not in ("none", "low", "medium", "high"):
            raise ValueError("glow_level must be none, low, medium or high")
        data["effects"]["glow"] = {
            **data["effects"].get("glow", {}),
            "level": glow_level,
            "enabled": glow_level != "none",
        }
    return VisualPreset.model_validate(data)
