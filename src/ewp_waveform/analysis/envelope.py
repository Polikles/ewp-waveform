"""RMS envelope over a sliding time window. Source audio is not modified."""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from pathlib import Path


def hop_samples(sample_rate: int, width: int, window_seconds: float) -> int:
    if width < 1 or window_seconds <= 0 or sample_rate < 1:
        msg = "invalid envelope hop parameters"
        raise ValueError(msg)
    return max(1, int(sample_rate * window_seconds / width))


def rms_bins_from_wav(path: Path, hop: int) -> list[float]:
    """Return one RMS value per hop of mono s16le WAV."""
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1:
            msg = f"envelope expects mono WAV, got {wav.getnchannels()} channels"
            raise ValueError(msg)
        if wav.getsampwidth() != 2:
            msg = "envelope expects 16-bit PCM"
            raise ValueError(msg)
        total = wav.getnframes()
        bins: list[float] = []
        remaining = total
        while remaining > 0:
            take = min(hop, remaining)
            raw = wav.readframes(take)
            remaining -= take
            count = len(raw) // 2
            if count == 0:
                break
            acc = 0.0
            for i in range(0, count * 2, 2):
                sample = int.from_bytes(raw[i : i + 2], "little", signed=True)
                acc += float(sample) * float(sample)
            bins.append(math.sqrt(acc / count) / 32768.0)
    return bins


def scale_amplitude(value: float, scale: str) -> float:
    v = min(max(value, 0.0), 1.0)
    if scale == "sqrt":
        return math.sqrt(v)
    if scale == "cbrt":
        return float(v ** (1.0 / 3.0))
    if scale == "log":
        return math.log10(1.0 + 9.0 * v)
    return v


def normalize_bins(bins: Sequence[float], *, percentile: float = 95.0) -> list[float]:
    """Scale visualization bins so typical peaks fill 0..1. Does not touch source audio."""
    active = [v for v in bins if v > 1e-4]
    if not active:
        return list(bins)
    ordered = sorted(active)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile / 100.0)))
    peak = ordered[index]
    if peak <= 0.0:
        return list(bins)
    return [min(1.0, v / peak) for v in bins]


def column_offset(frame_index: int, fps: float, window_seconds: float, width: int) -> int:
    """Integer columns advanced at this frame. Scroll is translation-only."""
    if fps <= 0 or window_seconds <= 0 or width < 1:
        msg = "invalid scroll offset parameters"
        raise ValueError(msg)
    pixels_per_second = width / window_seconds
    return round(frame_index * pixels_per_second / fps)


def window_at_column(bins: Sequence[float], *, end_exclusive: int, width: int) -> list[float]:
    """Right edge is 'now' (end_exclusive-1). Values are copied, never recomputed."""
    start = end_exclusive - width
    out: list[float] = []
    for i in range(width):
        idx = start + i
        if 0 <= idx < len(bins):
            out.append(bins[idx])
        else:
            out.append(0.0)
    return out


def window_at_time(
    bins: Sequence[float],
    *,
    time_seconds: float,
    sample_rate: int,
    hop: int,
    width: int,
) -> list[float]:
    """Deprecated indexing helper; prefer column_offset + window_at_column."""
    now_index = int(time_seconds * sample_rate / hop)
    return window_at_column(bins, end_exclusive=now_index + 1, width=width)
