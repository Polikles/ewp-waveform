"""Deterministic render signatures (ADR-0004)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ewp_waveform.config.models import VisualPreset

VISUAL_CONTRACT_VERSION = 13
SPECTRUM_CONTRACT_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def render_signature(
    *,
    source_sha256: str,
    preset: VisualPreset,
    fps: float,
    renderer: str = "ffmpeg",
    clip_start: float = 0.0,
    clip_duration: float | None = None,
    fixed_axis_recipe: dict[str, Any] | None = None,
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "preset": preset.name,
        "style": preset.waveform.style,
        "domain": preset.waveform.domain,
        "time_mode": preset.waveform.time_mode,
        "color": preset.waveform.color,
        "amplitude": preset.waveform.amplitude,
        "stroke_width": preset.waveform.stroke_width,
        "center_line": preset.waveform.center_line,
        "window_seconds": preset.waveform.window_seconds,
        "fps": fps,
        "canvas": [preset.canvas.width, preset.canvas.height],
        "signal": preset.signal,
        "effects": preset.effects,
        "renderer": renderer,
        "visual_contract_version": VISUAL_CONTRACT_VERSION,
        "clip_start": round(max(clip_start, 0.0), 9),
        "clip_duration": None if clip_duration is None else round(max(clip_duration, 0.0), 9),
    }
    if preset.signal.get("fixed_axis_profile") == "filled-ribbon-v2":
        payload["ribbon_appearance"] = {
            "revision": 1,
            "foreground_appearance_revision": 1,
            "background_mode": preset.waveform.background_mode,
            "color_mode": preset.waveform.color_mode,
            "reflection_opacity": preset.waveform.reflection_opacity,
            "center_line_extent": preset.waveform.center_line_extent,
            "center_line_opacity": preset.waveform.center_line_opacity,
        }
    if preset.waveform.domain == "frequency":
        payload["spectrum_contract_version"] = SPECTRUM_CONTRACT_VERSION
    if fixed_axis_recipe is not None:
        payload["fixed_axis_recipe"] = fixed_axis_recipe
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def short_signature(full: str) -> str:
    return full[:12]
