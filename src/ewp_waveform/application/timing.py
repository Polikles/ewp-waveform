"""Lightweight phase timers for render-path benchmarks."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any


class PhaseTimes:
    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self.extras: dict[str, Any] = {}

    def add(self, name: str, delta: float) -> None:
        self.seconds[name] = self.seconds.get(name, 0.0) + delta
        self.counts[name] = self.counts.get(name, 0) + 1

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, time.perf_counter() - start)

    def snapshot(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seconds": dict(self.seconds),
            "counts": dict(self.counts),
        }
        if self.extras:
            payload["extras"] = dict(self.extras)
        return payload


def merge_phase_maps(*maps: Mapping[str, float] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in maps:
        if not item:
            continue
        for key, value in item.items():
            out[key] = out.get(key, 0.0) + float(value)
    return out
