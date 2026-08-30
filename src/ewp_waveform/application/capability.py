"""Preset capability notes shared by plan, render, and benchmark."""

from __future__ import annotations

from ewp_waveform.config.models import VisualPreset
from ewp_waveform.domain.diagnostics import CapabilityLevel


def capability_for_preset(preset: VisualPreset) -> tuple[CapabilityLevel, str]:
    domain = preset.waveform.domain
    if domain == "frequency":
        return (
            CapabilityLevel.EXPERIMENTAL,
            "Fixed-axis spectrum: log-Hz span with vertical motion. Experimental.",
        )
    if preset.waveform.time_mode == "playhead":
        return CapabilityLevel.UNSUPPORTED, "Playhead envelope is deferred."
    style = preset.waveform.style
    if style == "segmented":
        return CapabilityLevel.EXPERIMENTAL, "Impuls segmentowy is not implemented faithfully."
    if style in {"classic", "mirrored", "filled"}:
        return (
            CapabilityLevel.LIMITED,
            "Scrolling RMS envelope bars (5 s window). Limited vs brand linia lustrzana.",
        )
    return CapabilityLevel.UNSUPPORTED, f"Unknown style '{style}'."
