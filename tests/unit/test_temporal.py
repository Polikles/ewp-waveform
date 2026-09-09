import math
import struct
import wave
from pathlib import Path

from ewp_waveform.analysis.temporal import (
    TEMPORAL_BINS,
    load_mono_f32,
    temporal_envelope_bins,
    temporal_window_bins,
)


def _write_wav(path: Path, samples: list[float], rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for value in samples:
            clipped = max(-1.0, min(1.0, value))
            frames.extend(struct.pack("<h", int(clipped * 32000)))
        wav.writeframes(bytes(frames))


def test_centered_window_puts_a_click_at_mid_bin(tmp_path: Path) -> None:
    rate = 8000
    n = rate * 2
    samples = [0.0] * n
    samples[rate] = 1.0
    path = tmp_path / "click.wav"
    _write_wav(path, samples, rate=rate)
    loaded, loaded_rate = load_mono_f32(path)
    assert loaded_rate == rate
    bins = temporal_window_bins(
        loaded,
        loaded_rate,
        time_seconds=1.0,
        n_bins=64,
        window_seconds=1.5,
        peak_mix=0.0,
    )
    assert len(bins) == TEMPORAL_BINS
    peak = bins.index(max(bins))
    assert abs(peak - 32) <= 2
    assert max(bins) > 0.0
    assert bins[0] < max(bins)
    assert bins[-1] < max(bins)


def test_peak_mix_raises_a_transient_above_rms() -> None:
    rate = 8000
    samples = [0.05] * rate
    samples[rate // 2] = 1.0
    rms = temporal_window_bins(samples, rate, time_seconds=0.5, n_bins=16, peak_mix=0.0)
    mixed = temporal_window_bins(samples, rate, time_seconds=0.5, n_bins=16, peak_mix=0.3)
    assert max(mixed) > max(rms)


def test_temporal_envelope_is_64_smooth_bins() -> None:
    rate = 8000
    samples = [0.2 * math.sin(2.0 * math.pi * 80.0 * i / rate) for i in range(rate)]
    bins = temporal_envelope_bins(samples, rate, time_seconds=0.5, peak_mix=0.0)
    assert len(bins) == 64
    assert all(value >= 0.0 for value in bins)
