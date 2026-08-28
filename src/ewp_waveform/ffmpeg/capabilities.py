"""Honest FFmpeg capability table (FR-RENDER-007/008)."""

from __future__ import annotations

from ewp_waveform.domain.diagnostics import CapabilityItem, CapabilityLevel


def ffmpeg_capabilities() -> list[CapabilityItem]:
    return [
        CapabilityItem(
            name="renderer:ffmpeg",
            level=CapabilityLevel.LIMITED,
            notes="MVP reference backend. Looks are not brand-faithful yet.",
        ),
        CapabilityItem(
            name="domain:time+scroll",
            level=CapabilityLevel.LIMITED,
            notes=(
                "Application RMS envelope over window_seconds with envelope_oversample, "
                "mirrored columns, FFmpeg encode+glow. Limited vs brand stroke density."
            ),
        ),
        CapabilityItem(
            name="domain:time+playhead",
            level=CapabilityLevel.UNSUPPORTED,
            notes="Deferred for later viz and GUI scrubber.",
        ),
        CapabilityItem(
            name="domain:frequency+fixed-axis",
            level=CapabilityLevel.EXPERIMENTAL,
            notes="showfreqs is the right axis; stock graphs are not the product look.",
        ),
        CapabilityItem(
            name="style:classic",
            level=CapabilityLevel.LIMITED,
            notes="Linia klasyczna: phrase-length thin ticks. Not 33 ms PCM.",
        ),
        CapabilityItem(
            name="style:mirrored",
            level=CapabilityLevel.LIMITED,
            notes="Scrolling RMS bars implemented; not yet pixel-matched to the boards.",
        ),
        CapabilityItem(
            name="style:filled",
            level=CapabilityLevel.LIMITED,
            notes="Wstęga. showwavespic matches time scale, not discrete bars.",
        ),
        CapabilityItem(
            name="style:segmented",
            level=CapabilityLevel.EXPERIMENTAL,
            notes="Impuls segmentowy: discrete columns. Slim-gap sausage is the wrong experiment.",
        ),
        CapabilityItem(
            name="effect:glow",
            level=CapabilityLevel.FULL,
            notes="gblur + overlay. Does not create bar geometry.",
        ),
        CapabilityItem(
            name="effect:particles",
            level=CapabilityLevel.UNSUPPORTED,
            notes="Custom renderer. Collision with fixed-axis wave is MVP2.",
        ),
        CapabilityItem(
            name="output:prores4444",
            level=CapabilityLevel.FULL,
            notes="prores_ks profile 4444. 10-bit request vs 12-bit probe still open.",
        ),
        CapabilityItem(
            name="output:png",
            level=CapabilityLevel.FULL,
            notes="RGBA sequence with fps_mode=cfr.",
        ),
        CapabilityItem(
            name="continuity:chunk-concat",
            level=CapabilityLevel.LIMITED,
            notes="Naive concat warms up showwaves; application preroll required.",
        ),
    ]
