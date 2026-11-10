from __future__ import annotations

import math

import numpy as np
import pytest

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import load_preset
from ewp_waveform.visual.mapping import MovingMouthMapping, RefinedRibbonMapping


def _frame(center: float, level: float = 0.5) -> AnalysisFrame:
    return AnalysisFrame(
        tuple(0.02 + math.exp(-0.5 * ((j - center) / 6.0) ** 2) for j in range(64)),
        overall_level=level,
    )


@pytest.mark.parametrize("detail", ["balanced", "detailed"])
@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
def test_constant_broadband_content_changes_have_different_local_envelopes(
    detail: str, fps: float
) -> None:
    mapping = RefinedRibbonMapping(detail_level=detail, fps=fps)
    left, right = _frame(10.0), _frame(48.0)
    seq = AnalysisSequence((left,) * 50 + (right,) * 60 + (left,) * 50)
    rows = np.asarray([mapping.apply_at(seq, i).amplitude for i in range(len(seq))])
    # No common activity modulation: broadband is exactly constant. Non-proportional
    # fields are required; synthetic changing content, not phase-shifted envelopes.
    before, after = rows[49], rows[109]
    assert not np.allclose(before / before.max(), after / after.max())
    ratios = after[8:57] / before[8:57]
    assert ratios.min() < 0.8 and ratios.max() > 1.2
    # Different regions rise and settle with the actual spectral change.
    steps = rows[109] - rows[49]
    assert steps.min() < -0.01 and steps.max() > 0.01
    instant = np.asarray(mapping.apply(right).amplitude)
    assert np.max(np.abs(rows[50] - rows[49])) < np.max(np.abs(instant - rows[49])) / 3.0
    for i in reversed(range(len(seq))):
        assert mapping.apply_at(seq, i).amplitude == tuple(rows[i])
    halo = math.ceil(mapping.SHAPE_SUPPORT_SECONDS * fps)
    sub = AnalysisSequence(seq.frames[50:])
    assert mapping.apply_at(sub, halo) == mapping.apply_at(seq, 50 + halo)


def test_sparse_weak_regions_remain_supported_silence_and_homogeneity() -> None:
    mapping = RefinedRibbonMapping()
    for center in (0.0, 8.0, 24.0, 40.0, 63.0):
        frame = _frame(center)
        row = np.asarray(mapping.apply(frame).amplitude)
        assert np.all(row[1:-1] > 0.0)
        loud = AnalysisFrame(tuple(v * 2.0 for v in frame.bands), 1.0)
        assert mapping.apply(loud).amplitude == pytest.approx(row * 2.0)
    speech = _frame(20.0)
    silence = AnalysisFrame((0.0,) * 64, 0.0)
    sequence = AnalysisSequence((speech,) * 50 + (silence,) * 100)
    for index in (50, 70, 149):
        assert mapping.apply_at(sequence, index).amplitude == (0.0,) * 65
    # Explicit activity with absent bands retains a broad minority support floor.
    assert max(mapping.apply(AnalysisFrame((0.0,) * 64, 1.0)).amplitude) > 0.0


def test_distinct_revision_identities_and_frozen_moving_mouth() -> None:
    ribbon = resolve_fixed_axis_appearance(load_preset("iuris-ribbon-refined")).identity()
    mouth = resolve_fixed_axis_appearance(load_preset("iuris-moving-mouth")).identity()
    assert ribbon["mapping_revision"] == 6 and mouth["mapping_revision"] == 4
    assert RefinedRibbonMapping.DETAIL_BOUND == MovingMouthMapping.DETAIL_BOUND == 0.24
    # A true new mapping, not a larger old residual bound or shared subclass state.
    assert not issubclass(RefinedRibbonMapping, MovingMouthMapping)
