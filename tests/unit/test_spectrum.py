import math
import struct
import wave
from pathlib import Path

from ewp_waveform.analysis.spectrum import (
    FFT_SIZE,
    auto_frequency_span,
    ema_alpha,
    log_resample,
    resolve_frequency_span,
    rfft_magnitudes,
)


def _sine_wav(path: Path, *, hz: float, seconds: float = 0.4, rate: int = 8000) -> None:
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            sample = int(16000 * math.sin(2.0 * math.pi * hz * i / rate))
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(frames))


def test_rfft_peaks_at_bin_frequency() -> None:
    n = FFT_SIZE
    k = 16
    samples = [math.cos(2.0 * math.pi * k * i / n) for i in range(n)]
    mags = rfft_magnitudes(samples)
    assert mags.index(max(mags)) == k


def test_log_resample_places_a_tone_at_log_midpoint() -> None:
    n = FFT_SIZE
    rate = 8000
    freq = 1000.0
    k = freq * n / rate
    mags = [0.0] * (n // 2 + 1)
    i0 = int(k)
    mags[i0] = 1.0
    width = 101
    columns = log_resample(mags, sample_rate=rate, fmin_hz=100.0, fmax_hz=10000.0, width=width)
    peak_x = columns.index(max(columns))
    expected = 0.5 * (width - 1)
    assert abs(peak_x - expected) <= 2


def test_auto_span_centers_a_tone_on_the_log_axis(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _sine_wav(path, hz=1000.0, rate=8000)
    span = auto_frequency_span(path)
    mid = math.sqrt(span.fmin_hz * span.fmax_hz)
    assert span.fmin_hz < 1000.0 < span.fmax_hz
    assert abs(math.log(mid / 1000.0)) < 0.35
    assert span.fmax_hz / span.fmin_hz >= 8.0


def test_explicit_span_wins_over_auto(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _sine_wav(path, hz=1000.0, rate=8000)
    span = resolve_frequency_span(
        path,
        {"frequency": {"range": "auto", "fmin_hz": 200.0, "fmax_hz": 2000.0}},
    )
    assert span.source == "explicit"
    assert abs(span.fmin_hz - 200.0) < 1.0
    assert abs(span.fmax_hz - 2000.0) < 1.0


def test_ema_alpha_is_one_when_tau_is_zero() -> None:
    assert ema_alpha(60.0, 0.0) == 1.0
    assert 0.0 < ema_alpha(60.0, 0.15) < 1.0
