"""Frozen mapping7 arithmetic, not an oracle sharing optimized composition/history."""

from __future__ import annotations

import math
import pickle
import random
import struct
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.visual.mapping import RefinedRibbonMapping, _broadband
from ewp_waveform.visual.models import VisualField


class FrozenRibbon(RefinedRibbonMapping):
    """Compose/apply_at from 98e68e1; deliberately bypass all descriptor memoization."""

    def _compose_field(
        self, level: float, texture: Sequence[float], seconds: float, *, idle: bool = False
    ) -> VisualField:
        if level <= 0.0:
            return VisualField.from_amplitudes([0.0] * self.n_slots)
        lobes = []
        for k, descriptor in enumerate(texture):
            h_noise = self.noise_at(k, seconds)
            w_noise = self.noise_at(k + 43, seconds)
            if idle:
                strength = 0.40 + 0.32 * h_noise
                width = 1.20 + 0.40 * w_noise
            else:
                ratio = min(1.0, max(0.0, descriptor + 0.48 * self.visual_noise * h_noise))
                strength = 0.06 + 2.8 * ratio**self.contrast
                width = (0.68 + 3.0 * ratio * ratio) * self.width_scale
                width *= 1.0 + 0.48 * self.visual_noise * w_noise
            lobes.append((strength, width))
        amplitudes = []
        for slot, gain in enumerate(self.carrier):
            d = float(slot - self.center)
            local = sum(
                strength * math.exp(-0.5 * ((d - center) / width) ** 2)
                for center, (strength, width) in zip(self.LOBE_CENTERS, lobes, strict=True)
            )
            amplitudes.append(level * gain * (0.015 + local))
        return VisualField.from_amplitudes(amplitudes)

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


def make_sequence(seed: int = 1, n_bands: int = 64) -> AnalysisSequence:
    rng = random.Random(seed)
    return AnalysisSequence(
        tuple(
            AnalysisFrame(
                tuple(10 ** rng.uniform(-8, 1) for _ in range(n_bands)),
                0.0 if i in (0, 21, 22) else rng.random(),
            )
            for i in range(85)
        )
    )


def field_bytes(field: VisualField) -> bytes:
    return struct.pack(f"!{field.n_slots}d", *field.amplitude)


def assert_field(actual: VisualField, expected: VisualField) -> None:
    assert field_bytes(actual) == field_bytes(expected)


@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
@pytest.mark.parametrize("fps", [1.0, 23.976, 59.94, 120.0])
@pytest.mark.parametrize("noise", [0.0, 0.35, 1.0])
def test_frozen_exact_composition_history_random_access(
    detail: str, fps: float, noise: float
) -> None:
    options: dict[str, Any] = dict(
        n_bands=17,
        detail_level=detail,
        fps=fps,
        visual_noise=noise,
        idle_activity=0.035,
        noise_seed=1729,
        audio_start_seconds=25.125,
    )
    actual, oracle = RefinedRibbonMapping(**options), FrozenRibbon(**options)
    a, b = make_sequence(n_bands=17), make_sequence(3, n_bands=17)
    order = [0, 1, 2, 14, 36, 37, 80, 21, 22, 23, 84, 1, 36, 3]
    for seq in (a, b, a):
        for index in order:
            assert_field(actual.apply_at(seq, index), oracle.apply_at(seq, index))
            assert_field(actual.idle_at(index), oracle.idle_at(index))
    assert_field(actual.apply(a[12]), oracle.apply(a[12]))


def test_exposed_state_replacements_do_not_reuse_stale_dependencies() -> None:
    actual = RefinedRibbonMapping(visual_noise=0.35, idle_activity=0.035)
    oracle = FrozenRibbon(visual_noise=0.35, idle_activity=0.035)
    seq = make_sequence()
    changes = [
        ("fps", 23.976),
        ("SHAPE_SECONDS", 0.17),
        ("SHAPE_SUPPORT_SECONDS", 0.3),
        ("center", 61),
        ("LOBE_CENTERS", tuple(c + 0.125 for c in actual.LOBE_CENTERS)),
        ("carrier", actual.carrier[:-3]),
        ("carrier", tuple(v * 0.8 for v in actual.carrier)),
        ("n_bands", 32),
        ("feature_weights", tuple(tuple(reversed(row)) for row in actual.feature_weights)),
        ("width_scale", 0.8),
        ("contrast", 1.7),
        ("visual_noise", 1.0),
        ("idle_activity", 0.15),
        ("noise_rate", 1.2),
        ("noise_seed", 100),
        ("audio_start_seconds", 91.5),
        ("n_slots", 127),
    ]
    for key, value in [("fps", 60.0), *changes]:
        setattr(actual, key, value)
        setattr(oracle, key, value)
        # Same sequence/index hits all memos populated before each replacement.
        assert_field(actual.apply_at(seq, 80), oracle.apply_at(seq, 80))
        assert_field(actual.apply(seq[10]), oracle.apply(seq[10]))
        assert_field(actual.idle_at(80), oracle.idle_at(80))


def test_partition_pickle_and_parallel_evaluation_are_exact() -> None:
    options: dict[str, Any] = dict(
        visual_noise=0.35, idle_activity=0.035, audio_start_seconds=25.0, noise_seed=1729
    )
    seq = make_sequence()
    oracle = FrozenRibbon(**options)
    expected = [oracle.apply_at(seq, i) for i in range(len(seq))]
    actual = RefinedRibbonMapping(**options)
    actual.apply_at(seq, 80)
    actual = pickle.loads(pickle.dumps(actual))
    order = list(range(len(seq)))
    random.Random(91).shuffle(order)
    with ThreadPoolExecutor(max_workers=4) as pool:
        fields = list(pool.map(lambda i: actual.apply_at(seq, i), order))
    for index, field in zip(order, fields, strict=True):
        assert_field(field, expected[index])
    # Fresh workers use absolute sequence indexes and therefore identical context.
    for start, stop in ((0, 29), (29, 64), (64, 85)):
        worker = RefinedRibbonMapping(**options)
        for index in range(start, stop):
            assert_field(worker.apply_at(seq, index), expected[index])


def test_geometry_precomputation_is_one_bounded_dependency_keyed_table() -> None:
    mapping = RefinedRibbonMapping()
    assert mapping._offset_memo is None
    offsets = mapping._lobe_offsets()
    assert len(offsets) == 21 and all(len(column) == 129 for column in offsets)
    # A carrier gain replacement affects output, but not the geometry dependency.
    mapping.carrier = tuple(gain * 0.9 for gain in mapping.carrier)
    assert mapping._lobe_offsets() is offsets
    mapping.center -= 1
    assert mapping._lobe_offsets() is not offsets
    assert mapping._offset_memo is not None
    assert len(mapping._offset_memo) == 2  # one key/table, no historical geometry


def test_zero_lobes_are_the_original_stationary_floor() -> None:
    actual, oracle = RefinedRibbonMapping(), FrozenRibbon()
    actual.LOBE_CENTERS = oracle.LOBE_CENTERS = ()
    assert_field(actual._compose_field(0.5, (), 0.0), oracle._compose_field(0.5, (), 0.0))


def test_empty_carrier_malformed_texture_and_zero_gate_contracts() -> None:
    actual, oracle = RefinedRibbonMapping(), FrozenRibbon()
    for mapping in (actual, oracle):
        with pytest.raises(ValueError):
            mapping._compose_field(0.5, (0.5,) * 20, 0.0)
        mapping.carrier = ()
    assert_field(actual._compose_field(0.5, (), 0.0), oracle._compose_field(0.5, (), 0.0))
    for level in (-1.0, 0.0):
        assert_field(actual._compose_field(level, (), 0.0), oracle._compose_field(level, (), 0.0))
