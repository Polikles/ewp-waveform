"""Deterministic render signatures (ADR-0004)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ewp_waveform.config.models import VisualPreset

VISUAL_CONTRACT_VERSION = 10


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
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def short_signature(full: str) -> str:
    return full[:12]
