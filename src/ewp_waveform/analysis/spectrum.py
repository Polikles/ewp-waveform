"""Fixed-axis frequency analysis. Does not mutate source audio."""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ewp_waveform.analysis.envelope import bin_peak, scale_amplitude, smooth_bins
from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.analysis.interp import pchip_eval_many, pchip_slopes

Float64 = NDArray[np.float64]


def _float_list(values: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(values, dtype=np.float64).ravel()]


FFT_SIZE = 2048
AUTO_FALLBACK_FMIN = 80.0
AUTO_FALLBACK_FMAX = 8000.0
HEARING_FMIN = 20.0
MIN_SPAN_RATIO = 8.0
ENERGY_LO = 0.05
ENERGY_HI = 0.95
ANALYSIS_HOP_SECONDS = 0.05
DB_PER_OCTAVE_EXP = 20.0 * math.log10(2.0)
PIVOT_TAU_SECONDS = 0.5
DOMINANT_PEAK_FRACTION = 0.35
EDGE_TAPER_FRACTION = 0.125


@dataclass(frozen=True)
class FrequencySpan:
    fmin_hz: float
    fmax_hz: float
    source: str


def frequency_config_from_signal(
    signal: dict[str, object],
) -> tuple[str, float | None, float | None]:
    raw = signal.get("frequency")
    if not isinstance(raw, dict):
        return "auto", None, None
    mode = str(raw.get("range") or "auto").lower()
    if mode not in {"auto", "project"}:
        mode = "auto"
    fmin = _positive_hz(raw.get("fmin_hz"))
    fmax = _positive_hz(raw.get("fmax_hz"))
    return mode, fmin, fmax


def _positive_hz(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    if value <= 0.0:
        return None
    return value


_HANN: dict[int, Float64] = {}


def hann(n: int) -> list[float]:
    return _float_list(_hann_array(n))


def _hann_array(n: int) -> Float64:
    cached = _HANN.get(n)
    if cached is not None:
        return cached
    if n <= 1:
        window = np.ones(max(n, 0), dtype=np.float64)
    else:
        window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n, dtype=np.float64) / (n - 1))
    _HANN[n] = window
    return window


def rfft_magnitudes(samples: Sequence[float]) -> list[float]:
    """Real FFT magnitudes for a power-of-two window. DC..Nyquist inclusive."""
    array = np.asarray(samples, dtype=np.float64)
    if array.ndim != 1:
        msg = "FFT window must be a 1-D real sequence"
        raise ValueError(msg)
    return _float_list(_rfft_magnitudes_array(array[np.newaxis, :])[0])


def _rfft_magnitudes_array(windows: Float64) -> Float64:
    """Hann-windowed rFFT magnitudes. ``windows`` is (n_windows, n_fft)."""
    if windows.ndim != 2:
        msg = "FFT windows must be a 2-D array"
        raise ValueError(msg)
    n = windows.shape[1]
    if n < 2 or n & (n - 1):
        msg = "FFT window must be a power of two"
        raise ValueError(msg)
    spec = np.fft.rfft(windows * _hann_array(n), axis=1)
    mags = np.abs(spec).astype(np.float64, copy=False) * (2.0 / n)
    mags[:, 0] *= 0.5
    mags[:, -1] *= 0.5
    return np.asarray(mags, dtype=np.float64)


def load_mono_pcm(path: Path) -> tuple[Float64, int]:
    """Load a mono s16le WAV as float64 samples in [-1, 1]."""
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            msg = "spectrum expects mono 16-bit WAV"
            raise ValueError(msg)
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64) * (1.0 / 32768.0)
    return pcm, rate


def gather_windows(pcm: Float64, starts: NDArray[np.int64], count: int) -> Float64:
    """Slice ``count`` samples at each start. Out-of-range samples are 0."""
    n_windows = int(starts.shape[0])
    if count < 1 or n_windows < 1:
        return np.zeros((n_windows, max(count, 0)), dtype=np.float64)
    if pcm.shape[0] < 1:
        return np.zeros((n_windows, count), dtype=np.float64)
    idx = starts.astype(np.int64, copy=False)[:, np.newaxis] + np.arange(count, dtype=np.int64)
    valid = (idx >= 0) & (idx < pcm.shape[0])
    clipped = np.clip(idx, 0, int(pcm.shape[0]) - 1)
    gathered = pcm[clipped]
    return np.where(valid, gathered, 0.0)


def _read_window(path: Path, *, start: int, count: int) -> tuple[list[float], int, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            msg = "spectrum expects mono 16-bit WAV"
            raise ValueError(msg)
        total = wav.getnframes()
        rate = wav.getframerate()
        if count < 1:
            return [], rate, total
        samples = np.zeros(count, dtype=np.float64)
        i0 = max(0, start)
        dest = i0 - start
        if dest >= count or i0 >= total:
            return _float_list(samples), rate, total
        n = min(count - dest, total - i0)
        if n <= 0:
            return _float_list(samples), rate, total
        wav.setpos(i0)
        raw = wav.readframes(n)
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64) * (1.0 / 32768.0)
        samples[dest : dest + n] = pcm[:n]
        return _float_list(samples), rate, total


def power_spectrum(samples: Sequence[float]) -> list[float]:
    return [v * v for v in rfft_magnitudes(samples)]


def _energy_percentiles(power: Sequence[float], sample_rate: int) -> tuple[float, float, float]:
    n_fft = (len(power) - 1) * 2
    weighted: list[tuple[float, float]] = []
    total = 0.0
    for k, p in enumerate(power):
        if k == 0:
            continue
        freq = k * sample_rate / n_fft
        if freq < HEARING_FMIN:
            continue
        energy = max(0.0, float(p))
        if energy <= 0.0:
            continue
        weighted.append((freq, energy))
        total += energy
    if total <= 0.0 or len(weighted) < 2:
        return (
            AUTO_FALLBACK_FMIN,
            AUTO_FALLBACK_FMAX,
            math.sqrt(AUTO_FALLBACK_FMIN * AUTO_FALLBACK_FMAX),
        )
    acc = 0.0
    lo = weighted[0][0]
    hi = weighted[-1][0]
    log_num = 0.0
    for freq, energy in weighted:
        prev = acc
        acc += energy
        if prev / total <= ENERGY_LO <= acc / total:
            lo = freq
        if prev / total <= ENERGY_HI <= acc / total:
            hi = freq
        log_num += energy * math.log(freq)
    centroid = math.exp(log_num / total)
    return lo, hi, centroid


def clamp_span(fmin: float, fmax: float, nyquist: float) -> tuple[float, float]:
    hi = min(max(fmax, HEARING_FMIN * MIN_SPAN_RATIO), max(nyquist, HEARING_FMIN * MIN_SPAN_RATIO))
    lo = min(max(fmin, HEARING_FMIN), hi / MIN_SPAN_RATIO)
    if hi / lo < MIN_SPAN_RATIO:
        mid = math.sqrt(max(lo, HEARING_FMIN) * hi)
        lo = mid / math.sqrt(MIN_SPAN_RATIO)
        hi = mid * math.sqrt(MIN_SPAN_RATIO)
    lo = max(HEARING_FMIN, lo)
    hi = min(nyquist, max(hi, lo * MIN_SPAN_RATIO))
    if hi <= lo:
        return AUTO_FALLBACK_FMIN, min(AUTO_FALLBACK_FMAX, nyquist)
    return lo, hi


def auto_frequency_span_from_pcm(pcm: Float64, rate: int) -> FrequencySpan:
    nyquist = float(rate) / 2.0
    total = int(pcm.shape[0])
    if total < 1 or rate < 1:
        return FrequencySpan(AUTO_FALLBACK_FMIN, min(AUTO_FALLBACK_FMAX, nyquist), "auto")
    hop = max(FFT_SIZE, round(rate * ANALYSIS_HOP_SECONDS))
    starts = np.arange(0, total, hop, dtype=np.int64)
    if starts.size == 0:
        return FrequencySpan(AUTO_FALLBACK_FMIN, min(AUTO_FALLBACK_FMAX, nyquist), "auto")
    windows = gather_windows(pcm, starts, FFT_SIZE)
    acc = np.sum(_rfft_magnitudes_array(windows) ** 2, axis=0)
    lo, hi, centroid = _energy_percentiles(acc.tolist(), rate)
    lo = lo / math.sqrt(2.0)
    hi = hi * math.sqrt(2.0)
    if hi / max(lo, HEARING_FMIN) < MIN_SPAN_RATIO:
        lo = centroid / math.sqrt(MIN_SPAN_RATIO)
        hi = centroid * math.sqrt(MIN_SPAN_RATIO)
    fmin, fmax = clamp_span(lo, hi, nyquist)
    return FrequencySpan(fmin, fmax, "auto")


def auto_frequency_span(path: Path) -> FrequencySpan:
    pcm, rate = load_mono_pcm(path)
    return auto_frequency_span_from_pcm(pcm, rate)


def resolve_frequency_span_from_pcm(
    pcm: Float64, rate: int, signal: dict[str, object]
) -> FrequencySpan:
    _mode, explicit_min, explicit_max = frequency_config_from_signal(signal)
    nyquist = float(rate) / 2.0
    if explicit_min is not None and explicit_max is not None and explicit_max > explicit_min:
        fmin, fmax = clamp_span(explicit_min, explicit_max, nyquist)
        return FrequencySpan(fmin, fmax, "explicit")
    return auto_frequency_span_from_pcm(pcm, rate)


def resolve_frequency_span(path: Path, signal: dict[str, object]) -> FrequencySpan:
    pcm, rate = load_mono_pcm(path)
    return resolve_frequency_span_from_pcm(pcm, rate, signal)


def _integrate_power(magnitudes: Sequence[float], k0: float, k1: float) -> float:
    """Integrate mag^2 over fractional FFT-bin coordinate [k0, k1)."""
    if k1 <= k0:
        return 0.0
    i0 = math.floor(k0)
    i1 = math.ceil(k1)
    acc = 0.0
    n_spec = len(magnitudes)
    for index in range(i0, i1):
        lo = max(float(index), k0)
        hi = min(float(index + 1), k1)
        if hi <= lo:
            continue
        mag = float(magnitudes[index]) if 0 <= index < n_spec else 0.0
        acc += mag * mag * (hi - lo)
    return acc


def band_weight_matrix(
    n_spec: int,
    *,
    sample_rate: int,
    fmin_hz: float,
    fmax_hz: float,
    n_bands: int,
) -> Float64:
    """Rows are log-band RMS weights over mag^2 bins. Static for a given FFT geometry."""
    count = max(2, int(n_bands))
    weights = np.zeros((count, max(n_spec, 0)), dtype=np.float64)
    if sample_rate < 1 or fmax_hz <= fmin_hz or n_spec < 2:
        return weights
    n_fft = (n_spec - 1) * 2
    ratio = fmax_hz / fmin_hz
    for i in range(count):
        lo = fmin_hz * (ratio ** (i / count))
        hi = fmin_hz * (ratio ** ((i + 1) / count))
        k0 = lo * n_fft / float(sample_rate)
        k1 = hi * n_fft / float(sample_rate)
        width = max(k1 - k0, 1e-12)
        i0 = math.floor(k0)
        i1 = math.ceil(k1)
        for index in range(i0, i1):
            bin_lo = max(float(index), k0)
            bin_hi = min(float(index + 1), k1)
            if bin_hi <= bin_lo or index < 0 or index >= n_spec:
                continue
            weights[i, index] = (bin_hi - bin_lo) / width
    return weights


def log_band_rms(
    magnitudes: Sequence[float],
    *,
    sample_rate: int,
    fmin_hz: float,
    fmax_hz: float,
    n_bands: int,
) -> list[float]:
    """RMS energy in log-spaced bands. Empty bands stay 0."""
    mags = np.asarray(magnitudes, dtype=np.float64)
    weights = band_weight_matrix(
        int(mags.shape[0]),
        sample_rate=sample_rate,
        fmin_hz=fmin_hz,
        fmax_hz=fmax_hz,
        n_bands=n_bands,
    )
    rms = np.sqrt(np.maximum(mags * mags @ weights.T, 0.0))
    return _float_list(rms)


def tilt_gains(
    n_bands: int,
    *,
    fmin_hz: float,
    fmax_hz: float,
    db_per_octave: float,
) -> list[float]:
    """Gains pivoted at the log-mid of the span. 0 dB/oct is all ones."""
    count = max(1, int(n_bands))
    if db_per_octave == 0.0 or fmax_hz <= fmin_hz:
        return [1.0] * count
    ratio = fmax_hz / fmin_hz
    fref = math.sqrt(fmin_hz * fmax_hz)
    exp = db_per_octave / DB_PER_OCTAVE_EXP
    gains = [0.0] * count
    for i in range(count):
        center = fmin_hz * (ratio ** ((i + 0.5) / count))
        gains[i] = (center / fref) ** exp
    return gains


def fold_bands_center_out(bands: Sequence[float]) -> list[float]:
    """Static center-out fold. Identical permutation every frame.

    Left-to-right visual slots: even bands descending into the center, then
    odd bands ascending: ``..., b4, b2, b0 | b1, b3, b5, ...``.
    Band 0 (lowest) sits immediately left of center; band 1 immediately right.
    """
    n = len(bands)
    if n < 2:
        return [max(0.0, float(v)) for v in bands]
    out = [0.0] * n
    left = n // 2
    for i in range(left):
        out[i] = max(0.0, float(bands[2 * (left - 1 - i)]))
    right = n - left
    for i in range(right):
        odd = 2 * i + 1
        if odd < n:
            out[left + i] = max(0.0, float(bands[odd]))
    return out


def compress_bands(values: Sequence[float], exponent: float) -> list[float]:
    """Power compressor on non-negative amplitudes. 1.0 is a no-op."""
    if exponent >= 1.0:
        return [max(0.0, float(v)) for v in values]
    exp = max(0.05, float(exponent))
    return [float(v) ** exp if v > 0.0 else 0.0 for v in values]


def dominant_band_pivot(bands: Sequence[float]) -> float:
    """Energy-weighted centroid of the dominant region. Not argmax.

    Bands below ``DOMINANT_PEAK_FRACTION`` of the peak are ignored so a long
    low-level tail cannot pull the center, and a single-bin spike cannot win
    against a broader plateau.
    """
    n = len(bands)
    if n <= 2:
        return max(n - 1, 0) / 2.0
    values = [max(0.0, float(v)) for v in bands]
    peak = max(values)
    last = float(n - 1)
    if peak <= 1e-12:
        return last / 2.0
    thresh = DOMINANT_PEAK_FRACTION * peak
    weights = [max(0.0, value - thresh) ** 2 for value in values]
    total = sum(weights)
    if total <= 1e-18:
        weights = [value * value for value in values]
        total = sum(weights)
    if total <= 1e-18:
        return last / 2.0
    pivot = sum(index * weight for index, weight in enumerate(weights)) / total
    return min(max(pivot, 1.0), last - 1.0)


def remap_band_index(t: float, *, n_bands: int, pivot: float | None) -> float:
    """Map normalized X in [0, 1] to a band index. ``pivot`` lands at X=0.5."""
    last = float(max(n_bands - 1, 1))
    x = min(max(t, 0.0), 1.0)
    if pivot is None:
        return x * last
    p = min(max(pivot, 1e-6), last - 1e-6)
    if x <= 0.5:
        return (x / 0.5) * p
    return p + ((x - 0.5) / 0.5) * (last - p)


def upsample_bands(
    bands: Sequence[float],
    width: int,
    *,
    pivot: float | None = None,
) -> list[float]:
    """PCHIP the coarse log-band envelope onto the output X axis."""
    if width < 1:
        return []
    n = len(bands)
    if n == 0:
        return [0.0] * width
    if n == 1:
        value = max(0.0, float(bands[0]))
        return [value] * width
    knots = [max(0.0, float(v)) for v in bands]
    slopes = pchip_slopes(knots)
    denom = max(width - 1, 1)
    xs = [remap_band_index(x / denom, n_bands=n, pivot=pivot) for x in range(width)]
    return _float_list(pchip_eval_many(knots, slopes, xs, unit=False))


def apply_edge_taper(
    columns: Sequence[float],
    *,
    content_width: int,
    pad: int = 0,
    fraction: float = EDGE_TAPER_FRACTION,
) -> list[float]:
    """Fade the outer ``fraction`` of the *content* width to zero (presentation)."""
    n = len(columns)
    if n < 2 or fraction <= 0.0 or content_width < 2:
        return list(columns)
    fade = min(max(fraction, 0.0), 0.49)
    out = [0.0] * n
    denom = max(content_width - 1, 1)
    for i, value in enumerate(columns):
        pos = (i - pad) / denom
        if pos <= 0.0 or pos >= 1.0:
            weight = 0.0
        elif pos < fade:
            weight = 0.5 - 0.5 * math.cos(math.pi * (pos / fade))
        elif pos > 1.0 - fade:
            weight = 0.5 - 0.5 * math.cos(math.pi * ((1.0 - pos) / fade))
        else:
            weight = 1.0
        out[i] = float(value) * weight
    return out


def log_resample(
    magnitudes: Sequence[float],
    *,
    sample_rate: int,
    fmin_hz: float,
    fmax_hz: float,
    width: int,
) -> list[float]:
    """Map DC..Nyquist FFT magnitudes onto a log-frequency axis of ``width`` bins."""
    if width < 1:
        return []
    n_spec = len(magnitudes)
    if n_spec < 2 or sample_rate < 1 or fmax_hz <= fmin_hz:
        return [0.0] * width
    n_fft = (n_spec - 1) * 2
    ratio = fmax_hz / fmin_hz
    out = [0.0] * width
    denom = max(width - 1, 1)
    for x in range(width):
        t = x / denom
        freq = fmin_hz * (ratio**t)
        k = freq * n_fft / float(sample_rate)
        i0 = math.floor(k)
        frac = k - i0
        a = max(0.0, float(magnitudes[i0])) if 0 <= i0 < n_spec else 0.0
        b = max(0.0, float(magnitudes[i0 + 1])) if 0 <= i0 + 1 < n_spec else 0.0
        out[x] = a * (1.0 - frac) + b * frac
    return out


def _scale_open(value: float, scale: str) -> float:
    """Amplitude map without clamping to 1 so tilt can exceed unit mag."""
    v = max(0.0, value)
    if scale == "sqrt":
        return math.sqrt(v)
    if scale == "cbrt":
        return float(v ** (1.0 / 3.0))
    if scale == "log":
        return math.log10(1.0 + 9.0 * v)
    return v


def _scale_open_array(values: Float64, scale: str) -> Float64:
    v = np.maximum(values, 0.0)
    if scale == "sqrt":
        return np.sqrt(v)
    if scale == "cbrt":
        return np.cbrt(v)
    if scale == "log":
        return np.log10(1.0 + 9.0 * v)
    return v


def compress_array(values: Float64, exponent: float) -> Float64:
    if exponent >= 1.0:
        return np.maximum(values, 0.0)
    exp = max(0.05, float(exponent))
    out = np.zeros_like(values)
    positive = values > 0.0
    out[positive] = values[positive] ** exp
    return out


def frame_window_starts(n_frames: int, *, sample_rate: int, fps: float) -> NDArray[np.int64]:
    """Center-timestamp window origins. Matches per-frame ``round(i * rate / fps)``."""
    if n_frames < 1:
        return np.zeros(0, dtype=np.int64)
    if fps <= 0.0:
        centers = np.zeros(n_frames, dtype=np.int64)
    else:
        centers = np.fromiter(
            (round(i * sample_rate / fps) for i in range(n_frames)),
            dtype=np.int64,
            count=n_frames,
        )
    return centers - FFT_SIZE // 2


def bands_from_windows(
    windows: Float64,
    *,
    sample_rate: int,
    span: FrequencySpan,
    scale: str,
    n_bands: int,
    tilt_db_per_octave: float,
    compress: float,
) -> Float64:
    """Tilted, compressed log-RMS bands for a batch of Hann-windowed frames."""
    count = max(2, int(n_bands))
    if windows.shape[0] < 1:
        return np.zeros((0, count), dtype=np.float64)
    mags = _rfft_magnitudes_array(windows)
    weights = band_weight_matrix(
        int(mags.shape[1]),
        sample_rate=sample_rate,
        fmin_hz=span.fmin_hz,
        fmax_hz=span.fmax_hz,
        n_bands=count,
    )
    rms = np.sqrt(np.maximum((mags * mags) @ weights.T, 0.0))
    gains = np.asarray(
        tilt_gains(
            count,
            fmin_hz=span.fmin_hz,
            fmax_hz=span.fmax_hz,
            db_per_octave=tilt_db_per_octave,
        ),
        dtype=np.float64,
    )
    return compress_array(_scale_open_array(rms * gains, scale), compress)


def build_analysis_sequence(
    pcm: Float64,
    sample_rate: int,
    *,
    n_frames: int,
    fps: float,
    span: FrequencySpan,
    scale: str,
    n_bands: int,
    tilt_db_per_octave: float,
    compress: float,
) -> AnalysisSequence:
    """One AnalysisFrame per video frame. FFT size, Hann, timestamps, and bands unchanged."""
    starts = frame_window_starts(n_frames, sample_rate=sample_rate, fps=fps)
    windows = gather_windows(pcm, starts, FFT_SIZE)
    matrix = bands_from_windows(
        windows,
        sample_rate=sample_rate,
        span=span,
        scale=scale,
        n_bands=n_bands,
        tilt_db_per_octave=tilt_db_per_octave,
        compress=compress,
    )
    frames = tuple(AnalysisFrame.from_bands(row.tolist()) for row in matrix)
    return AnalysisSequence(frames=frames)


def gaussian_kernel(sigma: float) -> list[float]:
    """Normalized Gaussian taps. ``sigma`` is in log-Hz axis pixels."""
    if sigma <= 0.0:
        return [1.0]
    radius = max(1, math.ceil(3.0 * sigma))
    denom = 2.0 * sigma * sigma
    taps = [math.exp(-(float(k) * float(k)) / denom) for k in range(-radius, radius + 1)]
    total = sum(taps)
    if total <= 0.0:
        return [1.0]
    return [tap / total for tap in taps]


def gaussian_smooth(values: Sequence[float], *, sigma: float) -> list[float]:
    """True Gaussian along the log-frequency axis. Edges clamp (no zero-pad fade)."""
    n = len(values)
    if sigma <= 0.0 or n < 2:
        return list(values)
    kernel = np.asarray(gaussian_kernel(sigma), dtype=np.float64)
    radius = int(kernel.shape[0]) // 2
    padded = np.pad(np.asarray(values, dtype=np.float64), (radius, radius), mode="edge")
    return _float_list(np.convolve(padded, kernel, mode="valid"))


def apply_spectrum_spatial(
    columns: Sequence[float],
    *,
    sigma: float,
    kind: str = "box",
) -> list[float]:
    """Spatial LPF on already log-resampled magnitudes. ``box`` is the production default."""
    if sigma <= 0.0:
        return list(columns)
    if kind == "gaussian":
        return gaussian_smooth(columns, sigma=sigma)
    return smooth_bins(columns, sigma=sigma)


def spectrum_bands(
    path: Path,
    *,
    frame_index: int,
    fps: float,
    span: FrequencySpan,
    scale: str,
    n_bands: int,
    tilt_db_per_octave: float,
    compress: float,
) -> list[float]:
    """Tilted, compressed log-RMS bands. No pixel upsample or spatial LPF."""
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
    center = round(frame_index * rate / fps) if fps > 0 else 0
    start = center - FFT_SIZE // 2
    samples, rate, _total = _read_window(path, start=start, count=FFT_SIZE)
    windows = np.asarray(samples, dtype=np.float64)[np.newaxis, :]
    return _float_list(
        bands_from_windows(
            windows,
            sample_rate=rate,
            span=span,
            scale=scale,
            n_bands=n_bands,
            tilt_db_per_octave=tilt_db_per_octave,
            compress=compress,
        )[0]
    )


def spectrum_columns(
    path: Path,
    *,
    frame_index: int,
    fps: float,
    width: int,
    span: FrequencySpan,
    scale: str,
    smoothing_sigma: float,
    spatial_filter: str = "box",
    n_bands: int | None = None,
    tilt_db_per_octave: float = 0.0,
    compress: float = 1.0,
    pivot: float | None = None,
) -> list[float]:
    if n_bands is not None:
        values = spectrum_bands(
            path,
            frame_index=frame_index,
            fps=fps,
            span=span,
            scale=scale,
            n_bands=n_bands,
            tilt_db_per_octave=tilt_db_per_octave,
            compress=compress,
        )
        columns = upsample_bands(values, width, pivot=pivot)
    else:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
        center = round(frame_index * rate / fps) if fps > 0 else 0
        start = center - FFT_SIZE // 2
        samples, rate, _total = _read_window(path, start=start, count=FFT_SIZE)
        mags = rfft_magnitudes(samples)
        columns = log_resample(
            mags,
            sample_rate=rate,
            fmin_hz=span.fmin_hz,
            fmax_hz=span.fmax_hz,
            width=width,
        )
        columns = [scale_amplitude(v, scale) for v in columns]
    return apply_spectrum_spatial(columns, sigma=smoothing_sigma, kind=spatial_filter)


def spectrum_peak(
    path: Path,
    *,
    n_frames: int,
    fps: float,
    width: int,
    span: FrequencySpan,
    scale: str,
    smoothing_sigma: float,
    spatial_filter: str = "box",
    n_bands: int | None = None,
    tilt_db_per_octave: float = 0.0,
    compress: float = 1.0,
) -> float:
    collected: list[float] = []
    step = 1 if n_frames <= 240 else max(1, n_frames // 120)
    for i in range(0, n_frames, step):
        collected.extend(
            spectrum_columns(
                path,
                frame_index=i,
                fps=fps,
                width=width,
                span=span,
                scale=scale,
                smoothing_sigma=smoothing_sigma,
                spatial_filter=spatial_filter,
                n_bands=n_bands,
                tilt_db_per_octave=tilt_db_per_octave,
                compress=compress,
            )
        )
    return bin_peak(collected)


def ema_alpha(fps: float, tau_seconds: float) -> float:
    """Blend toward the new spectrum. ``tau_seconds`` 0 is a no-op (alpha 1)."""
    if tau_seconds <= 0.0 or fps <= 0.0:
        return 1.0
    return 1.0 - math.exp(-1.0 / (fps * tau_seconds))


def blend_columns(
    previous: Sequence[float] | None, current: Sequence[float], alpha: float
) -> list[float]:
    if previous is None or alpha >= 1.0 or len(previous) != len(current):
        return list(current)
    beta = 1.0 - alpha
    return [alpha * c + beta * p for p, c in zip(previous, current, strict=True)]
