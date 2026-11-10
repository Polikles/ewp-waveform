from __future__ import annotations

import numpy as np
import pytest

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import load_preset
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.mapping import CenterOutMapping, RefinedRibbonMapping


@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
def test_activity_carrier_cannot_collapse_with_weak_local_bands(detail: str) -> None:
    mapping = RefinedRibbonMapping(detail_level=detail)
    carrier = np.asarray(mapping.carrier)
    for band in (0, 8, 24, 40, 56, 63):
        bands = [0.0] * 64
        bands[band] = 1.0
        frame = AnalysisFrame(tuple(bands), overall_level=0.7)
        slots = np.asarray(mapping.apply(frame).amplitude)
        assert np.all(slots >= 0.7 * carrier * (1 - mapping.DETAIL_BOUND) - 1e-15)
        assert np.all(slots <= 0.7 * carrier * (1 + mapping.DETAIL_BOUND) + 1e-15)
        assert 24 <= int(slots.argmax()) <= 40
        assert slots[0] == slots[-1] == 0.0
        louder = mapping.apply(AnalysisFrame(tuple(2 * v for v in bands), overall_level=1.4))
        assert louder.amplitude == pytest.approx(2 * slots)
    # Explicit broadband energy drives activity even when local bands vanish.
    assert max(mapping.apply(AnalysisFrame((0.0,) * 64, overall_level=1.0)).amplitude) > 0
    assert mapping.apply(AnalysisFrame((1.0,) * 64, overall_level=0.0)).amplitude == (0.0,) * 65


def test_shape_response_is_separate_from_current_activity_and_random_access() -> None:
    mapping = RefinedRibbonMapping(detail_level="detailed")
    left = AnalysisFrame.from_bands([1.0 if i < 20 else 0.0 for i in range(64)])
    right = AnalysisFrame.from_bands(list(reversed(left.bands)))
    sequence = AnalysisSequence((left,) * 60 + (right,) * 60)
    before = np.array(mapping.apply_at(sequence, 59).amplitude)
    after = np.array(mapping.apply_at(sequence, 60).amplitude)
    instant = np.array(mapping.apply(right).amplitude)
    assert np.max(np.abs(after - before)) < np.max(np.abs(instant - before)) / 5
    # A simultaneous 2x broadband step is not delayed by the shape filter.
    assert right.overall_level is not None
    louder = AnalysisSequence(
        (*sequence.frames[:60], AnalysisFrame(right.bands, right.overall_level * 2))
    )
    assert mapping.apply_at(louder, 60).amplitude == pytest.approx(after * 2)
    quiet = AnalysisSequence((*sequence.frames[:60], AnalysisFrame((0.0,) * 64, 0.0)))
    assert mapping.apply_at(quiet, 60).amplitude == (0.0,) * 65
    expected = [mapping.apply_at(sequence, i) for i in range(len(sequence))]
    # Nonsequential evaluation/worker partitions do not change canonical history.
    for i in reversed(range(len(sequence))):
        assert mapping.apply_at(sequence, i) == expected[i]
    split = [
        mapping.apply_at(sequence, i)
        for lo, hi in ((0, 17), (17, 61), (61, 120))
        for i in range(lo, hi)
    ]
    assert split == expected
    # Finite context reproduces an interior subclip exactly with its required halo.
    subclip = AnalysisSequence(sequence.frames[40:])
    assert mapping.apply_at(subclip, 40) == mapping.apply_at(sequence, 80)


def test_legacy_apply_at_is_exact_frame_local() -> None:
    mapping = CenterOutMapping()
    sequence = AnalysisSequence(tuple(AnalysisFrame.from_bands([i / 10] * 64) for i in range(5)))
    expected = [mapping.apply(f) for f in sequence.frames]
    assert [mapping.apply_at(sequence, i) for i in range(5)] == expected


def test_mapping_revision_invalidates_old_output_without_changing_v1_identity() -> None:
    preset = load_preset("iuris-ribbon-refined")
    recipe = resolve_fixed_axis_appearance(preset).identity()
    assert recipe["mapping_revision"] == 4
    old = dict(recipe, mapping_revision=3)
    assert render_signature(
        source_sha256="fixture", preset=preset, fps=60, fixed_axis_recipe=recipe
    ) != render_signature(source_sha256="fixture", preset=preset, fps=60, fixed_axis_recipe=old)
    v1 = resolve_fixed_axis_appearance(load_preset("iuris-ribbon-fixed")).identity()
    assert "mapping_revision" not in v1
