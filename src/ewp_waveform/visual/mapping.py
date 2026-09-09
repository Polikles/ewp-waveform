"""Static AnalysisFrame -> VisualField maps. Weights never depend on the current frame."""

from __future__ import annotations

import math
from collections.abc import Sequence

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.visual.models import VisualField

CENTER_OUT_SLOTS = 65


def _row_normalize(rows: list[list[float]]) -> tuple[tuple[float, ...], ...]:
    out: list[tuple[float, ...]] = []
    for row in rows:
        total = sum(row)
        if total <= 0.0:
            out.append(tuple(row))
        else:
            out.append(tuple(value / total for value in row))
    return tuple(out)


def center_out_weights(n_slots: int, n_bands: int) -> tuple[tuple[float, ...], ...]:
    """Fixed weights: one visual center, remaining bands alternate left/right.

    Slot ``n_slots//2`` is the unique center (band 0, spread over a few slots so
    it is one region). Right of center takes odd bands 1,3,5,... Left takes
    even bands 2,4,6,... No row is a copy of another; left and right differ.
    """
    slots = max(3, int(n_slots) | 1)
    bands = max(2, int(n_bands))
    center = slots // 2
    weights = [[0.0] * bands for _ in range(slots)]
    radius = 2
    for offset in range(-radius, radius + 1):
        slot = center + offset
        if 0 <= slot < slots:
            falloff = 0.5 + 0.5 * math.cos(math.pi * abs(offset) / (radius + 0.5))
            weights[slot][0] += falloff
    max_k = center
    for k in range(1, max_k + 1):
        right = center + k
        left = center - k
        if 0 <= right < slots:
            odd = min(2 * k - 1, bands - 1)
            weights[right][odd] += 1.0
        if 0 <= left < slots:
            even = 2 * k
            if even >= bands:
                even = bands - 1
            weights[left][even] += 1.0
    return _row_normalize(weights)


class CenterOutMapping:
    """Stationary center-out field. ``n_slots`` need not equal the band count."""

    def __init__(self, n_slots: int = CENTER_OUT_SLOTS, n_bands: int = 64) -> None:
        slots = max(3, int(n_slots) | 1)
        bands = max(2, int(n_bands))
        self.n_slots = slots
        self.n_bands = bands
        self.center = slots // 2
        self.weights = center_out_weights(slots, bands)

    def apply(self, frame: AnalysisFrame) -> VisualField:
        src = frame.bands
        n = min(len(src), self.n_bands)
        amplitudes = [0.0] * self.n_slots
        for i, row in enumerate(self.weights):
            acc = 0.0
            for j in range(n):
                acc += row[j] * src[j]
            amplitudes[i] = max(0.0, acc)
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
