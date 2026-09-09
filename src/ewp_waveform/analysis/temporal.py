"""Centered temporal envelope for visual-shape experiments. Source audio is not modified."""

from __future__ import annotations

import math
import wave
from pathlib import Path

from ewp_waveform.analysis.envelope import bin_peak
from ewp_waveform.analysis.spectrum import compress_bands, gaussian_smooth, upsample_bands

TEMPORAL_WINDOW_SECONDS = 1.5
TEMPORAL_BINS = 64
TEMPORAL_BAND_SIGMA = 1.0
TEMPORAL_COMPRESS = 0.75
TEMPORAL_PEAK_MIX = 0.3


def load_mono_f32(path: Path) -> tuple[list[float], int]:
    """Load a mono s16le WAV as float samples in [-1, 1]."""
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            msg = "temporal envelope expects mono 16-bit WAV"
            raise ValueError(msg)
        rate = wav.getframerate()
        total = wav.getnframes()
        raw = wav.readframes(total)
    samples = [0.0] * total
    for i in range(total):
        sample = int.from_bytes(raw[i * 2 : i * 2 + 2], "little", signed=True)
        samples[i] = float(sample) / 32768.0
    return samples, rate


def _bin_stats(
    samples: list[float], rate: int, start_s: float, end_s: float
) -> tuple[float, float]:
    """Return (rms, peak_abs) for [start_s, end_s) in seconds. Out of range is 0."""
    if end_s <= start_s or rate < 1 or not samples:
        return 0.0, 0.0
    n = len(samples)
    start = start_s * rate
    end = end_s * rate
    i0 = max(0, math.floor(start))
    i1 = min(n, math.ceil(end))
    if i1 <= i0:
        return 0.0, 0.0
    acc = 0.0
    weight_sum = 0.0
    peak = 0.0
    for i in range(i0, i1):
        left = max(float(i), start)
        right = min(float(i + 1), end)
        weight = right - left
        if weight <= 0.0:
            continue
        value = samples[i]
        acc += weight * value * value
        weight_sum += weight
        abs_v = abs(value)
        if abs_v > peak:
            peak = abs_v
    if weight_sum <= 0.0:
        return 0.0, 0.0
    return math.sqrt(acc / weight_sum), peak


def temporal_window_bins(
    samples: list[float],
    rate: int,
    *,
    time_seconds: float,
    n_bins: int = TEMPORAL_BINS,
    window_seconds: float = TEMPORAL_WINDOW_SECONDS,
    peak_mix: float = 0.0,
) -> list[float]:
    """Equal-time energy bins in a window centered on ``time_seconds``.

    Bin 0 is the oldest edge, bin n-1 the newest. Center time is the middle bin.
    ``peak_mix`` 0 is RMS only; 1 is peak-abs only.
    """
    count = max(2, int(n_bins))
    half = max(window_seconds, 1e-6) / 2.0
    t0 = time_seconds - half
    mix = min(max(peak_mix, 0.0), 1.0)
    width = window_seconds / float(count)
    out = [0.0] * count
    for i in range(count):
        lo = t0 + i * width
        hi = lo + width
        rms, peak = _bin_stats(samples, rate, lo, hi)
        out[i] = (1.0 - mix) * rms + mix * peak
    return out


def temporal_envelope_bins(
    samples: list[float],
    rate: int,
    *,
    time_seconds: float,
    n_bins: int = TEMPORAL_BINS,
    window_seconds: float = TEMPORAL_WINDOW_SECONDS,
    peak_mix: float = 0.0,
    compress: float = TEMPORAL_COMPRESS,
    smooth_sigma: float = TEMPORAL_BAND_SIGMA,
) -> list[float]:
    """Compressed, spatially smoothed temporal bins ready to upsample."""
    raw = temporal_window_bins(
        samples,
        rate,
        time_seconds=time_seconds,
        n_bins=n_bins,
        window_seconds=window_seconds,
        peak_mix=peak_mix,
    )
    compressed = compress_bands(raw, compress)
    return gaussian_smooth(compressed, sigma=smooth_sigma)


def temporal_envelope_columns(
    samples: list[float],
    rate: int,
    *,
    time_seconds: float,
    width: int,
    peak_mix: float = 0.0,
) -> list[float]:
    bins = temporal_envelope_bins(samples, rate, time_seconds=time_seconds, peak_mix=peak_mix)
    return upsample_bands(bins, width)


def temporal_envelope_peak(
    samples: list[float],
    rate: int,
    *,
    n_frames: int,
    fps: float,
    origin_seconds: float,
    width: int,
    peak_mix: float = 0.0,
) -> float:
    collected: list[float] = []
    step = 1 if n_frames <= 240 else max(1, n_frames // 120)
    for i in range(0, n_frames, step):
        time_seconds = origin_seconds + (i / fps if fps > 0 else 0.0)
        collected.extend(
            temporal_envelope_columns(
                samples,
                rate,
                time_seconds=time_seconds,
                width=width,
                peak_mix=peak_mix,
            )
        )
    return bin_peak(collected)
