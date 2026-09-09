"""Audio-domain analysis frames. Independent of visual presentation."""

from __future__ import annotations

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
        level = max(values) if values else 0.0
        return cls(bands=values, overall_level=level)
