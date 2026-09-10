"""Audio-domain analysis frames. Independent of visual presentation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisFrame:
    """One moment of audio features. Band count is analysis resolution, not pixels."""

    bands: tuple[float, ...]
    overall_level: float | None = None

    @classmethod
    def from_bands(cls, bands: Sequence[float]) -> AnalysisFrame:
        values = tuple(max(0.0, float(v)) for v in bands)
        mean_sq = sum(v * v for v in values) / float(len(values)) if values else 0.0
        return cls(bands=values, overall_level=math.sqrt(mean_sq))


@dataclass(frozen=True)
class AnalysisSequence:
    """Clip-length analysis. Conceptually frames x bands."""

    frames: tuple[AnalysisFrame, ...]

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> AnalysisFrame:
        return self.frames[index]
