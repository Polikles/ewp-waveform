"""RMS envelope over a sliding time window. Source audio is not modified."""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ENVELOPE_OVERSAMPLE_ALLOWED = frozenset({1, 2, 4, 8})


def envelope_oversample_from_signal(signal: dict[str, object]) -> int:
    raw = signal.get("envelope_oversample", 1)
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int) and raw in ENVELOPE_OVERSAMPLE_ALLOWED:
        return raw
    if isinstance(raw, float) and int(raw) == raw and int(raw) in ENVELOPE_OVERSAMPLE_ALLOWED:
        return int(raw)
    return 1


def hop_samples(
    sample_rate: int,
    width: int,
    window_seconds: float,
    oversample: int = 1,
) -> int:
    """Hop so ``width * oversample`` real RMS bins cover ``window_seconds``."""
    if width < 1 or window_seconds <= 0 or sample_rate < 1 or oversample < 1:
        msg = "invalid envelope hop parameters"
        raise ValueError(msg)
    analysis_width = width * oversample
    return max(1, int(sample_rate * window_seconds / analysis_width))


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


def soft_clip_unit(value: float, *, knee: float = 0.88) -> float:
    """Compress values above ``knee`` toward 1.0 so peaks are not a hard ceiling."""
    v = max(0.0, value)
    if v <= knee:
        return v
    t = (v - knee) / max(1e-6, 1.0 - knee)
    return knee + (1.0 - knee) * math.tanh(t)


def normalize_bins(
    bins: Sequence[float],
    *,
    percentile: float = 95.0,
    soft_clip: bool = False,
    knee: float = 0.88,
) -> list[float]:
    """Scale visualization bins so typical peaks fill the range. Does not touch source audio."""
    active = [v for v in bins if v > 1e-4]
    if not active:
        return list(bins)
    ordered = sorted(active)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile / 100.0)))
    peak = ordered[index]
    if peak <= 0.0:
        return list(bins)
    if not soft_clip:
        return [min(1.0, v / peak) for v in bins]
    scale = knee / peak
    return [min(1.0, soft_clip_unit(v * scale, knee=knee)) for v in bins]


def column_offset(frame_index: int, fps: float, window_seconds: float, width: int) -> int:
    """Integer columns advanced at this frame. Scroll is translation-only."""
    return round(column_offset_float(frame_index, fps, window_seconds, width))


def column_offset_float(frame_index: int, fps: float, window_seconds: float, width: int) -> float:
    """Output-pixel columns advanced at this frame. Timestamp-derived; not quantized."""
    if fps <= 0 or window_seconds <= 0 or width < 1:
        msg = "invalid scroll offset parameters"
        raise ValueError(msg)
    return frame_index * width / (window_seconds * fps)


def viewport_left_px(frame_index: int, fps: float, window_seconds: float, width: int) -> float:
    """Left edge of the visible window in output pixels (right edge is 'now')."""
    return column_offset_float(frame_index, fps, window_seconds, width) + 1.0 - width


@dataclass(frozen=True)
class ScrollTiming:
    frame_index: int
    timestamp: float
    scroll_phase: float
    fractional_phase: float
    expected_delta_px: float
    envelope_position: float

    def as_row(self) -> str:
        return (
            f"{self.frame_index:5d}  t={self.timestamp:9.6f}  "
            f"phase={self.scroll_phase:14.8f}  frac={self.fractional_phase:10.8f}  "
            f"dpx={self.expected_delta_px:10.8f}  env={self.envelope_position:14.8f}"
        )


def scroll_timing(
    frame_index: int,
    *,
    fps: float,
    window_seconds: float,
    width: int,
    oversample: int = 1,
) -> ScrollTiming:
    """Diagnostic row: constant pixel delta implies constant envelope sampling."""
    vis = viewport_left_px(frame_index, fps, window_seconds, width)
    expected = width / (window_seconds * fps)
    return ScrollTiming(
        frame_index=frame_index,
        timestamp=frame_index / fps,
        scroll_phase=vis,
        fractional_phase=vis - math.floor(vis),
        expected_delta_px=expected,
        envelope_position=vis * oversample,
    )


def iter_scroll_timing(
    n_frames: int,
    *,
    fps: float,
    window_seconds: float,
    width: int,
    oversample: int = 1,
) -> list[ScrollTiming]:
    return [
        scroll_timing(
            i,
            fps=fps,
            window_seconds=window_seconds,
            width=width,
            oversample=oversample,
        )
        for i in range(n_frames)
    ]


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


def _box_blur(values: Sequence[float], radius: int) -> list[float]:
    """Zero-padded box blur of window 2*radius+1."""
    n = len(values)
    if n == 0 or radius < 1:
        return list(values)
    pref = [0.0] * (n + 1)
    acc = 0.0
    for i, value in enumerate(values):
        acc += float(value)
        pref[i + 1] = acc
    width = float(2 * radius + 1)
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - radius)
        hi = min(n, i + radius + 1)
        out[i] = (pref[hi] - pref[lo]) / width
    return out


def smooth_bins(bins: Sequence[float], *, sigma: float) -> list[float]:
    """Approximate Gaussian blur along the envelope. ``sigma`` is in bins (viewport pixels).

    Time+scroll uses this so hop-scale spikes are not drawn. Bars/spikes belong on
    the fixed-axis frequency path. ``sigma <= 0`` is a no-op.
    """
    if sigma <= 0.0 or len(bins) < 2:
        return list(bins)
    radius = max(1, round(sigma))
    values = list(bins)
    for _ in range(3):
        values = _box_blur(values, radius)
    return values


def sample_bin(bins: Sequence[float], index: float) -> float:
    """Linear interpolation at a fractional envelope index. Out of range is 0."""
    if not bins:
        return 0.0
    i0 = math.floor(index)
    t = index - i0

    def at(i: int) -> float:
        if 0 <= i < len(bins):
            return min(max(float(bins[i]), 0.0), 1.0)
        return 0.0

    if t <= 1e-12:
        return at(i0)
    return at(i0) * (1.0 - t) + at(i0 + 1) * t


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
