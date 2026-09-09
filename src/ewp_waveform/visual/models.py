"""Presentation-oriented visual field. Independent of FFT / band count."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualField:
    """Stationary 1-D amplitude field. Slot i is the same analysis mix every frame."""

    amplitude: tuple[float, ...]

    @classmethod
    def from_amplitudes(cls, values: Sequence[float]) -> VisualField:
        return cls(amplitude=tuple(max(0.0, float(v)) for v in values))

    @property
    def n_slots(self) -> int:
        return len(self.amplitude)
