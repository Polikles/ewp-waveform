from __future__ import annotations

import math

import pytest

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.ribbon import apply_public_appearance
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.mapping import MovingMouthMapping


def _revision4(sequence: AnalysisSequence, index: int, detail: str, fps: float) -> list[float]:
    """Independent frozen equation oracle, revision4 before the style split."""
    sigma, mix, contrast = {
        "smooth": (2.6, 0.65, 1.15),
        "balanced": (1.2, 0.30, 1.6),
        "detailed": (0.45, 0.08, 1.95),
    }[detail]
    frame = sequence[index]

    def level(f: AnalysisFrame) -> float:
        if f.overall_level is not None:
            return max(0.0, float(f.overall_level))
        return math.sqrt(sum(v * v for v in f.bands) / len(f.bands)) if f.bands else 0.0

    if level(frame) <= 0.0:
        return [0.0] * 65
    result = []
    for slot in range(65):
        band = slot * 63 / 64
        residual = total = 0.0
        for lag in range(min(index, math.ceil(0.60 * fps)) + 1):
            src = sequence[index - lag].bands[:64]
            peak = max(src, default=0.0)
            value = 0.0
            if peak > 0.0:
                means = []
                for spread in (sigma, 4.0):
                    weights = [math.exp(-0.5 * ((j - band) / spread) ** 2) for j in range(64)]
                    norm = sum(weights)
                    means.append(
                        sum((w / norm) * v for w, v in zip(weights, src, strict=False)) / peak
                    )
                mixed = (1.0 - mix) * means[0] + mix * means[1]
                value = 2.0 * min(1.0, max(0.0, mixed)) ** contrast - 1.0
            weight = math.exp(-lag / (fps * 0.24))
            residual += weight * value
            total += weight
        d = float(slot - 32)
        edge = min(1.0, (32 - abs(d)) / 3.0)
        ribs = 0.78 + 0.12 * math.cos(0.73 * d) + 0.07 * math.cos(1.61 * d)
        ribs += 0.03 * math.sin(0.37 * d)
        carrier = edge * math.exp(-(d**2) / (2.0 * 19.0 * 19.0)) * ribs
        result.append(level(frame) * carrier * (1.0 + 0.24 * residual / total))
    return result


@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
def test_frozen_revision4_fields_and_history(fps: float, detail: str) -> None:
    frames = []
    for t in range(85):
        # Broadband-only, sparse regions, broad spectra, changing tilt, pauses,
        # explicit level and band-RMS fallback; deterministic non-render fixture.
        bands = tuple(
            (0.03 + (j % 7) * 0.02) * (1.0 + 0.8 * math.sin(t * 0.13 + j * 0.29))
            + (0.5 if (j // 8) == (t // 11) % 8 else 0.0)
            for j in range(64)
        )
        overall = None if t % 3 else (0.0 if t in (0, 84) else 0.3 + t / 200.0)
        frames.append(AnalysisFrame(bands, overall))
    seq = AnalysisSequence(tuple(frames))
    mapping = MovingMouthMapping(detail_level=detail, fps=fps)
    for i in (0, 1, 17, 36, 57, 83, 84):
        expected = _revision4(seq, i, detail, fps)
        assert mapping.apply_at(seq, i).amplitude == pytest.approx(expected, abs=2e-15)
    assert mapping.apply(frames[17]).amplitude == pytest.approx(
        _revision4(AnalysisSequence((frames[17],)), 0, detail, fps), abs=2e-15
    )


def test_public_selection_controls_and_identity() -> None:
    mouth = load_preset("iuris-moving-mouth")
    ribbon = load_preset("iuris-ribbon-refined")
    assert mouth.signal["fixed_axis_profile"] == "moving-mouth-v1"
    assert resolve_fixed_axis_appearance(mouth).identity()["mapping_revision"] == 4
    assert mouth.name != ribbon.name

    def identity(preset_name: str) -> str:
        p = load_preset(preset_name)
        return render_signature(
            source_sha256="fixture",
            preset=p,
            fps=60,
            fixed_axis_recipe=resolve_fixed_axis_appearance(p).identity(),
        )

    assert identity("iuris-moving-mouth") != identity("iuris-ribbon-refined")
    original = identity("iuris-moving-mouth")
    for changed in (
        apply_public_appearance(mouth, detail_level="detailed"),
        apply_public_appearance(mouth, waveform_color="steel_blue"),
        apply_public_appearance(mouth, glow_level="none"),
        apply_public_appearance(mouth, amplitude=0.6),
        apply_public_appearance(mouth, stroke_width=8.0),
    ):
        assert (
            render_signature(
                source_sha256="fixture",
                preset=changed,
                fps=60,
                fixed_axis_recipe=resolve_fixed_axis_appearance(changed).identity(),
            )
            != original
        )
