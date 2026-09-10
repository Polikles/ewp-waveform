"""Static AnalysisFrame -> VisualField maps. Weights never depend on the current frame."""

from __future__ import annotations

import math
from collections.abc import Sequence

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.visual.models import VisualField

CENTER_OUT_SLOTS = 65
CORE_RADIUS = 5
SHOULDER_EXTENT = 6
SIDE_TO_CENTER = 0.9


def _odd_at_least(value: int, minimum: int) -> int:
    n = max(minimum, int(value))
    return n if n % 2 == 1 else n + 1


def _broadband(frame: AnalysisFrame) -> float:
    if frame.overall_level is not None:
        return max(0.0, float(frame.overall_level))
    values = frame.bands
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / float(len(values)))


def _gaussian(offset: int, sigma: float) -> float:
    if sigma <= 0.0:
        return 1.0 if offset == 0 else 0.0
    return math.exp(-(float(offset) ** 2) / (2.0 * sigma * sigma))


def _core_kernel(radius: int) -> tuple[float, ...]:
    """Wide unimodal Gaussian for offsets -radius..radius. Unique max at 0."""
    span = max(1, radius)
    sigma = span * 1.1
    return tuple(_gaussian(offset, sigma) for offset in range(-span, span + 1))


def center_out_layout(
    n_slots: int, n_bands: int
) -> tuple[tuple[tuple[float, ...], ...], tuple[float, ...], tuple[float, ...], int]:
    """Return (side_mix, visual_gain, shoulder_gain, core_radius).

    Core slots use visual_gain only. Shoulder gain continues the same
    Gaussian under the first side slots as a floor so the ribbon does not
    neck. Independent bands start outside the core.
    """
    slots = _odd_at_least(n_slots, 3)
    bands = max(2, int(n_bands))
    center = slots // 2
    radius = min(CORE_RADIUS, max(1, center - 1))
    sigma = float(radius) * 1.1
    shoulder_span = radius + min(SHOULDER_EXTENT, max(0, center - radius - 1))
    side_mix = [[0.0] * bands for _ in range(slots)]
    visual_gain = [1.0] * slots
    shoulder_gain = [0.0] * slots
    kernel = _core_kernel(radius)
    for i, gain in enumerate(kernel):
        visual_gain[center - radius + i] = gain
    for i in range(slots):
        distance = abs(i - center)
        if distance <= shoulder_span:
            shoulder_gain[i] = _gaussian(distance, sigma)
    side_slots: list[int] = []
    for distance in range(radius + 1, center + 1):
        for slot in (center + distance, center - distance):
            if 0 <= slot < slots:
                side_slots.append(slot)
    n_side = len(side_slots)
    last = float(max(bands - 1, 1))
    for index, slot in enumerate(side_slots):
        t = (index / max(n_side - 1, 1)) * last
        j0 = min(bands - 1, max(0, math.floor(t)))
        j1 = min(bands - 1, j0 + 1)
        frac = t - float(j0)
        side_mix[slot][j0] += 1.0 - frac
        if j1 != j0:
            side_mix[slot][j1] += frac
        row_sum = sum(side_mix[slot])
        if row_sum > 0.0:
            side_mix[slot] = [value / row_sum for value in side_mix[slot]]
    frozen_sides = tuple(tuple(row) for row in side_mix)
    return frozen_sides, tuple(visual_gain), tuple(shoulder_gain), radius


class CenterOutMapping:
    """Stationary center-out field. ``n_slots`` need not equal the band count."""

    def __init__(self, n_slots: int = CENTER_OUT_SLOTS, n_bands: int = 64) -> None:
        slots = _odd_at_least(n_slots, 3)
        bands = max(2, int(n_bands))
        side_mix, visual_gain, shoulder_gain, radius = center_out_layout(slots, bands)
        self.n_slots = slots
        self.n_bands = bands
        self.center = slots // 2
        self.core_radius = radius
        self.side_mix = side_mix
        self.visual_gain = visual_gain
        self.shoulder_gain = shoulder_gain
        self.side_to_center = SIDE_TO_CENTER

    def apply(self, frame: AnalysisFrame) -> VisualField:
        src = frame.bands
        n = min(len(src), self.n_bands)
        center_amplitude = _broadband(frame)
        lo = self.center - self.core_radius
        hi = self.center + self.core_radius
        amplitudes = [0.0] * self.n_slots
        for i in range(self.n_slots):
            gain = self.visual_gain[i]
            if lo <= i <= hi:
                amplitudes[i] = gain * center_amplitude
                continue
            acc = 0.0
            row = self.side_mix[i]
            for j in range(n):
                acc += row[j] * src[j]
            amplitudes[i] = gain * max(0.0, acc)
        apex = amplitudes[self.center]
        cap = self.side_to_center * apex
        side_peak = 0.0
        for i in range(self.n_slots):
            if i < lo or i > hi:
                side_peak = max(side_peak, amplitudes[i])
        if apex > 0.0 and side_peak > cap:
            factor = cap / side_peak
            for i in range(self.n_slots):
                if i < lo or i > hi:
                    amplitudes[i] *= factor
        for i in range(self.n_slots):
            if lo <= i <= hi:
                continue
            floor = self.shoulder_gain[i] * center_amplitude
            if floor > amplitudes[i]:
                amplitudes[i] = floor
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
