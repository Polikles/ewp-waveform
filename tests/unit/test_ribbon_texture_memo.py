"""Exact descriptor memo oracles; synthetic only, no FFmpeg/media calls."""

from __future__ import annotations

import math
import pickle
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.visual.mapping import RefinedRibbonMapping, _broadband
from ewp_waveform.visual.models import VisualField


class UncachedRibbon(RefinedRibbonMapping):
    """Frozen base apply_at arithmetic from P3f71663d, independent cache oracle."""

    def apply_at(self, sequence: AnalysisSequence, index: int) -> VisualField:
        current = _broadband(sequence[index])
        if current <= 0.0:
            return VisualField.from_amplitudes([0.0] * self.n_slots)
        texture = [0.0] * len(self.LOBE_CENTERS)
        total = 0.0
        support = math.ceil(self.SHAPE_SUPPORT_SECONDS * self.fps)
        for lag in range(min(index, support) + 1):
            weight = math.exp(-lag / (self.fps * self.SHAPE_SECONDS))
            for k, value in enumerate(self._texture(sequence[index - lag])):
                texture[k] += weight * value
            total += weight
        return self._compose_field(
            current, [v / total for v in texture], self.audio_start_seconds + index / self.fps
        )


def sequence(size: int = 81, offset: int = 0) -> AnalysisSequence:
    return AnalysisSequence(
        tuple(
            AnalysisFrame.from_bands(
                [0.0] * 64
                if 41 <= i < 47
                else [0.01 + ((j * 17 + i * 11 + offset) % 101) / 101.0 for j in range(64)]
            )
            for i in range(size)
        )
    )


@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
@pytest.mark.parametrize("fps", [24.0, 30.0, 59.94, 60.0])
@pytest.mark.parametrize("origin", [0.0, 25.0])
def test_exact_random_access_and_sequence_switch(detail: str, fps: float, origin: float) -> None:
    def make(cls: type[RefinedRibbonMapping]) -> RefinedRibbonMapping:
        return cls(
            detail_level=detail,
            fps=fps,
            audio_start_seconds=origin,
            visual_noise=0.35,
            idle_activity=0.035,
            noise_seed=1729,
        )

    cached, base = make(RefinedRibbonMapping), make(UncachedRibbon)
    a, b = sequence(), sequence(offset=19)
    order = [0, 1, 14, 36, 37, 40, 41, 46, 47, 79, 80, 37, 2, 80]
    for seq in (a, b, a):
        for index in order:
            assert cached.apply_at(seq, index) == base.apply_at(seq, index)
            assert cached.idle_at(index) == base.idle_at(index)
    assert cached.apply(a[3]) == base.apply(a[3])


def test_descriptor_work_is_linear_bounded_and_peak_sweep_safe() -> None:
    seq = sequence(130)
    cached = RefinedRibbonMapping()
    with patch.object(cached, "_texture", wraps=cached._texture) as texture:
        for index in range(len(seq)):
            cached.apply_at(seq, index)
        # Zero-level current frames skip history, but later history evaluates them.
        assert texture.call_count == len(seq)
    memo = cached._texture_memo
    assert memo is not None and memo[0] is seq
    assert len(memo[1]) == 37
    assert sum(item is not None for item in memo[1]) == 37
    base = UncachedRibbon()
    for index in [0, 64, 129, 0, 1, 36, 37, 128, 129]:
        assert cached.apply_at(seq, index) == base.apply_at(seq, index)
    other = sequence(130)
    assert other == seq and other is not seq
    with patch.object(cached, "_texture", wraps=cached._texture) as texture:
        cached.apply_at(other, 0)
        assert texture.call_count == 1


def test_pickling_thread_interleaving_different_sequences_and_silence() -> None:
    mapping = RefinedRibbonMapping(visual_noise=0.35, noise_seed=1729, audio_start_seconds=25)
    a, b = sequence(), sequence(offset=35)
    mapping.apply_at(a, 80)
    clone = pickle.loads(pickle.dumps(mapping))
    base = UncachedRibbon(visual_noise=0.35, noise_seed=1729, audio_start_seconds=25)
    requests = [(a if i % 2 else b, (i * 19) % 81) for i in range(140)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda item: clone.apply_at(*item), requests))
    assert actual == [base.apply_at(*item) for item in requests]
    zero = AnalysisSequence((AnalysisFrame((0.0,) * 64, 0.0),) * 40)
    for i in (0, 36, 39):
        assert clone.apply_at(zero, i).amplitude == (0.0,) * 129
    assert RefinedRibbonMapping()._texture_memo is None
