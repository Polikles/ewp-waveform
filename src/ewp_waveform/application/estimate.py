"""Labelled output-size estimates from the FFmpeg spike table (docs/13)."""

from __future__ import annotations

from collections.abc import Sequence

from ewp_waveform.config.models import VisualPreset

# Spike note (docs/notes/ffmpeg-spike/findings.md): filled+medium glow, 1400x280, 30 fps.
SPIKE_PRORES_MB_PER_S = 12.5
SPIKE_PNG_MB_PER_S = 3.6
SPIKE_PIXEL_FPS = 1400 * 280 * 30
ESTIMATE_LABEL = (
    "labelled spike extrapolation (filled+glow 1400x280 @ 30 fps); not a profile default"
)


def estimate_output_mb(
    duration_seconds: float,
    preset: VisualPreset,
    formats: Sequence[str],
) -> float | None:
    if duration_seconds <= 0:
        return None
    scale = (preset.canvas.width * preset.canvas.height * preset.canvas.fps) / SPIKE_PIXEL_FPS
    total = 0.0
    want_png = "png" in formats
    want_mov = "prores4444" in formats or not formats
    if want_mov:
        total += duration_seconds * SPIKE_PRORES_MB_PER_S * scale
    if want_png:
        total += duration_seconds * SPIKE_PNG_MB_PER_S * scale
    return total
