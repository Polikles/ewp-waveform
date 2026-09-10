"""Static AnalysisFrame -> VisualField maps. Weights never depend on the current frame."""

from __future__ import annotations

import math
from collections.abc import Sequence

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.visual.models import VisualField

CENTER_OUT_SLOTS = 65
CORE_RADIUS = 3
CENTER_SRC_BANDS = 6


def _odd_at_least(value: int, minimum: int) -> int:
    n = max(minimum, int(value))
    return n if n % 2 == 1 else n + 1


def _normalize(values: Sequence[float]) -> tuple[float, ...]:
    total = sum(max(0.0, float(v)) for v in values)
    if total <= 0.0:
        return tuple(0.0 for _ in values)
    return tuple(max(0.0, float(v)) / total for v in values)


def _center_mix(n_bands: int, n_src: int) -> tuple[float, ...]:
    mix = [0.0] * n_bands
    count = min(max(2, n_src), n_bands)
    for index in range(count):
        mix[index] = 1.0 / (1.0 + 0.35 * float(index))
    return _normalize(mix)


def _core_kernel(radius: int) -> tuple[float, ...]:
    """Unimodal gains for offsets -radius..radius. Unique max at 0."""
    span = max(1, radius)
    gains: list[float] = []
    for offset in range(-span, span + 1):
        gains.append(0.4 + 0.6 * math.cos(0.5 * math.pi * abs(offset) / span))
    return tuple(gains)


def _rms_mix(bands: Sequence[float], mix: Sequence[float]) -> float:
    acc = 0.0
    weight = 0.0
    n = min(len(bands), len(mix))
    for index in range(n):
        w = mix[index]
        if w <= 0.0:
            continue
        value = max(0.0, float(bands[index]))
        acc += w * value * value
        weight += w
    if weight <= 0.0:
        return 0.0
    return math.sqrt(acc / weight)


def center_out_layout(
    n_slots: int, n_bands: int
) -> tuple[tuple[float, ...], tuple[tuple[float, ...], ...], tuple[float, ...], int]:
    """Return (center_mix, side_mix, visual_gain, core_radius).

    Mix rows are normalized source combinations. Visual gain is a separate
    static envelope so row-normalization cannot flatten the central lobe.
    """
    slots = _odd_at_least(n_slots, 3)
    bands = max(2, int(n_bands))
    center = slots // 2
    radius = min(CORE_RADIUS, max(1, center - 1))
    n_src = min(CENTER_SRC_BANDS, max(2, bands // 2))
    center_mix = _center_mix(bands, n_src)
    side_mix = [[0.0] * bands for _ in range(slots)]
    visual_gain = [1.0] * slots
    kernel = _core_kernel(radius)
    for i, gain in enumerate(kernel):
        visual_gain[center - radius + i] = gain
    remaining = list(range(n_src, bands))
    cursor = 0
    for distance in range(radius + 1, center + 1):
        for slot in (center + distance, center - distance):
            if slot < 0 or slot >= slots:
                continue
            if cursor < len(remaining):
                side_mix[slot][remaining[cursor]] = 1.0
                cursor += 1
            elif remaining:
                side_mix[slot][remaining[-1]] = 1.0
    frozen_sides = tuple(tuple(row) for row in side_mix)
    return center_mix, frozen_sides, tuple(visual_gain), radius


class CenterOutMapping:
    """Stationary center-out field. ``n_slots`` need not equal the band count."""

    def __init__(self, n_slots: int = CENTER_OUT_SLOTS, n_bands: int = 64) -> None:
        slots = _odd_at_least(n_slots, 3)
        bands = max(2, int(n_bands))
        center_mix, side_mix, visual_gain, radius = center_out_layout(slots, bands)
        self.n_slots = slots
        self.n_bands = bands
        self.center = slots // 2
        self.core_radius = radius
        self.center_mix = center_mix
        self.side_mix = side_mix
        self.visual_gain = visual_gain

    def apply(self, frame: AnalysisFrame) -> VisualField:
        src = frame.bands
        n = min(len(src), self.n_bands)
        center_energy = _rms_mix(src[:n], self.center_mix)
        amplitudes = [0.0] * self.n_slots
        lo = self.center - self.core_radius
        hi = self.center + self.core_radius
        for i in range(self.n_slots):
            gain = self.visual_gain[i]
            if lo <= i <= hi:
                amplitudes[i] = gain * center_energy
                continue
            acc = 0.0
            row = self.side_mix[i]
            for j in range(n):
                acc += row[j] * src[j]
            amplitudes[i] = gain * max(0.0, acc)
        return VisualField.from_amplitudes(amplitudes)


def apply_static_weights(bands: Sequence[float], weights: Sequence[Sequence[float]]) -> VisualField:
    frame = AnalysisFrame.from_bands(bands)
    n_slots = len(weights)
    n_bands = len(weights[0]) if n_slots else 0
    amplitudes = [0.0] * n_slots
    src = frame.bands
    n = min(len(src), n_bands)
    for i, row in enumerate(weights):
        acc = 0.0
        for j in range(n):
            acc += row[j] * src[j]
        amplitudes[i] = max(0.0, acc)
    return VisualField.from_amplitudes(amplitudes)
