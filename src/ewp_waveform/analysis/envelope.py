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


def window_at_time(
    bins: Sequence[float],
    *,
    time_seconds: float,
    sample_rate: int,
    hop: int,
    width: int,
) -> list[float]:
    """Right edge is 'now'; left edge is now minus the window. Pad with zeros."""
    now_index = int(time_seconds * sample_rate / hop)
    start = now_index - width + 1
    out: list[float] = []
    for i in range(width):
        idx = start + i
        if 0 <= idx < len(bins):
            out.append(bins[idx])
        else:
            out.append(0.0)
    return out
