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


class RefinedRibbonMapping(CenterOutMapping):
    """Designed amplitude field: irregular stationary wavelets, not Hz-to-X.

    Local normalized spectral texture drives height and width, while broadband
    gates the speech rhythm. Optional artistic modulation is smooth value noise,
    stateless and keyed by absolute audio seconds. No moving centers or sorting.
    """

    SHAPE_SECONDS = 0.24
    SHAPE_SUPPORT_SECONDS = 0.60
    LOBE_CENTERS = (
        -58.0,
        -52.1,
        -47.0,
        -40.4,
        -34.8,
        -28.5,
        -23.2,
        -17.0,
        -11.7,
        -5.1,
        0.8,
        6.1,
        12.8,
        18.0,
        24.4,
        30.0,
        35.1,
        42.0,
        47.3,
        53.8,
        59.0,
    )

    def __init__(
        self,
        n_bands: int = 64,
        detail_level: str = "balanced",
        fps: float = 60.0,
        *,
        visual_noise: float = 0.0,
        idle_activity: float = 0.0,
        noise_rate: float = 0.8,
        noise_seed: int = 0,
        audio_start_seconds: float = 0.0,
    ) -> None:
        super().__init__(n_slots=129, n_bands=n_bands)
        self.fps = max(1.0, float(fps))
        self.visual_noise = visual_noise
        self.idle_activity = idle_activity
        self.noise_rate = noise_rate
        self.noise_seed = noise_seed
        self.audio_start_seconds = audio_start_seconds
        # A bounded, sequence-identity-scoped descriptor memo, not temporal state.
        # Each immutable slot update is independent; concurrent/random accesses
        # may recompute a value but cannot change the returned field.
        self._texture_memo: tuple[
            AnalysisSequence, list[tuple[int, tuple[float, ...]] | None]
        ] | None = None
        sigma = {"smooth": 2.6, "balanced": 1.2, "detailed": 0.6}[detail_level]
        self.contrast = 2.0
        self.width_scale = {"smooth": 1.8, "balanced": 1.0, "detailed": 0.65}[detail_level]
        rows = []
        for k in range(len(self.LOBE_CENTERS)):
            # Coprime permutation spreads neighboring spectral neighborhoods over
            # the width; neither frequency position nor speaker identity implied.
            center = ((k * 8) % 21 + 0.5) * self.n_bands / 21 - 0.5
            row = [math.exp(-0.5 * ((j - center) / sigma) ** 2) for j in range(self.n_bands)]
            total = sum(row)
            rows.append(tuple(w / total for w in row))
        self.feature_weights = tuple(rows)
        self.carrier = tuple(
            min(1.0, (self.center - abs(i - self.center)) / 4.0)
            * math.exp(-0.5 * ((i - self.center) / 48.0) ** 2)
            for i in range(self.n_slots)
        )

    def _texture(self, frame: AnalysisFrame) -> tuple[float, ...]:
        src = frame.bands[: self.n_bands]
        mean = math.sqrt(sum(v * v for v in src) / max(1, len(src)))
        if mean <= 0.0:
            return (0.5,) * len(self.LOBE_CENTERS)
        energies = [
            math.sqrt(sum(w * v * v for w, v in zip(row, src, strict=False)))
            for row in self.feature_weights
        ]
        return tuple(v / (v + mean) for v in energies)

    def _texture_at(self, sequence: AnalysisSequence, index: int) -> tuple[float, ...]:
        """Reuse exact frame-local descriptors within the finite history window.

        Capture one memo locally so another caller switching sequences cannot
        associate a descriptor with the wrong sequence. There are no global
        caches, float-key comparisons, rounded keys or changes to reduction order.
        """
        capacity = math.ceil(self.SHAPE_SUPPORT_SECONDS * self.fps) + 1
        memo = self._texture_memo
        if memo is None or memo[0] is not sequence or len(memo[1]) != capacity:
            memo = (sequence, [None] * capacity)
            self._texture_memo = memo
        slot = index % capacity
        entry = memo[1][slot]
        if entry is not None and entry[0] == index:
            return entry[1]
        value = self._texture(sequence[index])
        memo[1][slot] = (index, value)
        return value

    def _value(self, channel: int, tick: int) -> float:
        # Integer hash; never Python's randomized hash or mutable RNG state.
        value = (self.noise_seed ^ (channel * 0x9E3779B1) ^ (tick * 0x85EBCA77)) & 0xFFFFFFFF
        value = ((value ^ (value >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
        value = ((value ^ (value >> 15)) * 0x846CA68B) & 0xFFFFFFFF
        value ^= value >> 16
        return 2.0 * value / 0xFFFFFFFF - 1.0

    def noise_at(self, channel: int, audio_seconds: float) -> float:
        """C2-continuous temporal lattice; slower neighboring channels correlate."""
        position = audio_seconds * self.noise_rate
        tick = math.floor(position)
        f = position - tick
        blend = f * f * f * (f * (6.0 * f - 15.0) + 10.0)

        def sample(c: int) -> float:
            a = self._value(c, tick)
            return a + blend * (self._value(c, tick + 1) - a)

        return 0.65 * sample(channel) + 0.35 * sample(channel // 3 + 100)

    def _compose_field(
        self,
        level: float,
        texture: Sequence[float],
        seconds: float,
        *,
        idle: bool = False,
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

    def idle_at(self, index: int) -> VisualField:
        """Normalized intentional idle floor, added AFTER speech normalization.

        It cannot be amplified into loud-looking silence by clip auto-normalization.
        Idle animation is independent of noise amount; both default to zero.
        """
        seconds = self.audio_start_seconds + index / self.fps
        return self._compose_field(
            self.idle_activity, (0.5,) * len(self.LOBE_CENTERS), seconds, idle=True
        )

    def apply(self, frame: AnalysisFrame) -> VisualField:
        return self._compose_field(
            _broadband(frame), self._texture(frame), self.audio_start_seconds
        )

    def apply_at(self, sequence: AnalysisSequence, index: int) -> VisualField:
        current = _broadband(sequence[index])
        if current <= 0.0:
            return VisualField.from_amplitudes([0.0] * self.n_slots)
        texture = [0.0] * len(self.LOBE_CENTERS)
        total = 0.0
        support = math.ceil(self.SHAPE_SUPPORT_SECONDS * self.fps)
        for lag in range(min(index, support) + 1):
            weight = math.exp(-lag / (self.fps * self.SHAPE_SECONDS))
            for k, value in enumerate(self._texture_at(sequence, index - lag)):
                texture[k] += weight * value
            total += weight
        return self._compose_field(
            current, [v / total for v in texture], self.audio_start_seconds + index / self.fps
        )


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
