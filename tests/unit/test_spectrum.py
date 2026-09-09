import math
import struct
import wave
from itertools import pairwise
from pathlib import Path

from ewp_waveform.analysis.spectrum import (
    FFT_SIZE,
    FrequencySpan,
    auto_frequency_span,
    compress_bands,
    ema_alpha,
    gaussian_kernel,
    gaussian_smooth,
    log_band_rms,
    log_resample,
    resolve_frequency_span,
    rfft_magnitudes,
    spectrum_columns,
    tilt_gains,
    upsample_bands,
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


def _total_variation(values: list[float]) -> float:
    return sum(abs(later - earlier) for earlier, later in pairwise(values))


def test_gaussian_kernel_is_normalized_and_symmetric() -> None:
    taps = gaussian_kernel(4.0)
    assert abs(sum(taps) - 1.0) < 1e-12
    assert taps == list(reversed(taps))
    assert max(taps) == taps[len(taps) // 2]


def test_gaussian_smooth_does_not_raise_peaks_or_darken_dc() -> None:
    dc = gaussian_smooth([0.4] * 32, sigma=5.0)
    assert all(abs(value - 0.4) < 1e-12 for value in dc)
    impulse = [0.0] * 31
    impulse[15] = 1.0
    blurred = gaussian_smooth(impulse, sigma=3.0)
    assert max(blurred) <= 1.0 + 1e-12
    assert blurred.index(max(blurred)) == 15
    wider = gaussian_smooth(impulse, sigma=6.0)
    assert _total_variation(wider) < _total_variation(blurred)


def test_stronger_gaussian_spatial_reduces_loghz_lumpiness(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _sine_wav(path, hz=1000.0, rate=8000)
    span = FrequencySpan(200.0, 2000.0, "explicit")
    mild = spectrum_columns(
        path,
        frame_index=2,
        fps=10.0,
        width=80,
        span=span,
        scale="sqrt",
        smoothing_sigma=1.0,
        spatial_filter="gaussian",
    )
    strong = spectrum_columns(
        path,
        frame_index=2,
        fps=10.0,
        width=80,
        span=span,
        scale="sqrt",
        smoothing_sigma=3.5,
        spatial_filter="gaussian",
    )
    assert _total_variation(strong) < _total_variation(mild)
    assert max(strong) <= max(mild) + 1e-12


def test_log_band_rms_puts_a_tone_in_the_expected_band() -> None:
    n = FFT_SIZE
    rate = 8000
    freq = 1000.0
    mags = [0.0] * (n // 2 + 1)
    k = round(freq * n / rate)
    mags[k] = 1.0
    fmin, fmax = 100.0, 10000.0
    n_bands = 32
    bands = log_band_rms(mags, sample_rate=rate, fmin_hz=fmin, fmax_hz=fmax, n_bands=n_bands)
    peak = bands.index(max(bands))
    t = math.log(freq / fmin) / math.log(fmax / fmin)
    expected = min(n_bands - 1, max(0, int(t * n_bands)))
    assert abs(peak - expected) <= 1
    assert sum(1 for value in bands if value > 0.0) <= 3


def test_tilt_boosts_highs_relative_to_lows_without_flattening() -> None:
    gains = tilt_gains(16, fmin_hz=100.0, fmax_hz=10000.0, db_per_octave=3.0)
    assert gains[0] < 1.0 < gains[-1]
    assert min(gains) == gains[0]
    assert max(gains) == gains[-1]
    assert gains[-1] / gains[0] > 2.0
    assert any(abs(gain - 1.0) < 0.2 for gain in gains)


def test_compress_reduces_peak_to_median_ratio() -> None:
    values = [0.05, 0.08, 0.1, 0.9, 0.12, 0.07]
    compressed = compress_bands(values, 0.55)

    def ratio(xs: list[float]) -> float:
        ordered = sorted(xs)
        median = ordered[len(ordered) // 2]
        return max(xs) / median

    assert ratio(compressed) < ratio(values)


def test_upsample_bands_is_width_long_and_preserves_peaks() -> None:
    bands = [0.1, 0.2, 1.0, 0.15, 0.2]
    wide = upsample_bands(bands, 41)
    assert len(wide) == 41
    assert abs(wide[0] - 0.1) < 1e-9
    assert abs(wide[-1] - 0.2) < 1e-9
    assert max(wide) <= 1.0 + 1e-12
    assert wide.index(max(wide)) == 20


def test_band_mapping_is_coarser_than_pixel_resample(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _sine_wav(path, hz=1000.0, rate=8000)
    span = FrequencySpan(200.0, 2000.0, "explicit")
    pixel = spectrum_columns(
        path,
        frame_index=2,
        fps=10.0,
        width=80,
        span=span,
        scale="sqrt",
        smoothing_sigma=0.0,
    )
    bands = spectrum_columns(
        path,
        frame_index=2,
        fps=10.0,
        width=80,
        span=span,
        scale="sqrt",
        smoothing_sigma=0.0,
        n_bands=16,
        tilt_db_per_octave=3.0,
        compress=0.75,
    )
    def lobe_width(values: list[float]) -> int:
        peak = max(values)
        return sum(1 for value in values if value >= 0.25 * peak)

    assert pixel != bands
    assert lobe_width(bands) > lobe_width(pixel)
