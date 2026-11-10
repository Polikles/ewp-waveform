"""Static AnalysisFrame -> VisualField maps. Weights never depend on the current frame."""

from __future__ import annotations

import math
from collections.abc import Sequence

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.config.ribbon import MOVING_MOUTH_DETAIL_SETTINGS
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

    def apply_at(self, sequence: AnalysisSequence, index: int) -> VisualField:
        """Random-access field evaluation; legacy mapping is exactly frame-local."""
        return self.apply(sequence[index])

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


class MovingMouthMapping(CenterOutMapping):
    """Speech activity on a stationary designed carrier, not a faithful Hz plot.

    Broadband level controls height now; bounded normalized spectral detail has a
    separate finite causal response. No mutable history, pivot or moving X slots.
    """

    SHAPE_SECONDS = 0.24
    SHAPE_SUPPORT_SECONDS = 0.60
    DETAIL_BOUND = 0.24

    def __init__(
        self, n_bands: int = 64, detail_level: str = "balanced", fps: float = 60.0
    ) -> None:
        super().__init__(n_slots=CENTER_OUT_SLOTS, n_bands=n_bands)
        sigma, self.coarse_mix, self.contrast, _ = MOVING_MOUTH_DETAIL_SETTINGS[detail_level]
        self.fps = max(1.0, float(fps))
        fine: list[tuple[float, ...]] = []
        coarse: list[tuple[float, ...]] = []
        carrier: list[float] = []
        for slot in range(self.n_slots):
            band = slot * (self.n_bands - 1) / (self.n_slots - 1)
            for rows, spread in ((fine, sigma), (coarse, 4.0)):
                weights = [math.exp(-0.5 * ((j - band) / spread) ** 2) for j in range(self.n_bands)]
                total = sum(weights)
                rows.append(tuple(value / total for value in weights))
            d = float(slot - self.center)
            edge = min(1.0, (self.center - abs(d)) / 3.0)
            # A fixed, gently asymmetric multi-scale silhouette. These are spatial
            # design constants, never oscillators or synthetic temporal activity.
            ribs = 0.78 + 0.12 * math.cos(0.73 * d) + 0.07 * math.cos(1.61 * d)
            ribs += 0.03 * math.sin(0.37 * d)
            carrier.append(edge * _gaussian(int(d), 19.0) * ribs)
        self.fine_weights = tuple(fine)
        self.coarse_weights = tuple(coarse)
        self.carrier = tuple(carrier)

    def _detail(self, frame: AnalysisFrame) -> tuple[float, ...]:
        src = frame.bands[: self.n_bands]
        peak = max(src, default=0.0)
        if peak <= 0.0:
            return (0.0,) * self.n_slots
        values: list[float] = []
        for fine_row, coarse_row in zip(self.fine_weights, self.coarse_weights, strict=True):
            fine = sum(w * v for w, v in zip(fine_row, src, strict=False)) / peak
            coarse = sum(w * v for w, v in zip(coarse_row, src, strict=False)) / peak
            mixed = (1.0 - self.coarse_mix) * fine + self.coarse_mix * coarse
            # Homogeneous shape descriptor; weak bands can only alter the bounded
            # residual, never erase their region of the broadband carrier.
            values.append(2.0 * min(1.0, max(0.0, mixed)) ** self.contrast - 1.0)
        return tuple(values)

    def _compose(self, frame: AnalysisFrame, detail: Sequence[float]) -> VisualField:
        level = _broadband(frame)
        return VisualField.from_amplitudes(
            [
                level * gain * (1.0 + self.DETAIL_BOUND * value)
                for gain, value in zip(self.carrier, detail, strict=True)
            ]
        )

    def apply(self, frame: AnalysisFrame) -> VisualField:
        """Single-frame evaluation without context; use apply_at for sequences."""
        return self._compose(frame, self._detail(frame))

    def apply_at(self, sequence: AnalysisSequence, index: int) -> VisualField:
        frame = sequence[index]
        if _broadband(frame) <= 0.0:
            return VisualField.from_amplitudes([0.0] * self.n_slots)
        support = math.ceil(self.SHAPE_SUPPORT_SECONDS * self.fps)
        detail = [0.0] * self.n_slots
        total = 0.0
        for lag in range(min(index, support) + 1):
            weight = math.exp(-lag / (self.fps * self.SHAPE_SECONDS))
            values = self._detail(sequence[index - lag])
            for slot, value in enumerate(values):
                detail[slot] += weight * value
            total += weight
        return self._compose(frame, [value / total for value in detail])


class RefinedRibbonMapping(MovingMouthMapping):
    """Refined ribbon; separated from preserved Moving mouth for future evolution."""


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
