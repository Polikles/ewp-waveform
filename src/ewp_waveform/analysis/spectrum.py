"""Fixed-axis frequency analysis. Does not mutate source audio."""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ewp_waveform.analysis.envelope import bin_peak, scale_amplitude, smooth_bins
from ewp_waveform.analysis.interp import pchip_eval, pchip_slopes

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


def _fft_inplace(buf: list[complex]) -> None:
    n = len(buf)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            buf[i], buf[j] = buf[j], buf[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wlen = complex(math.cos(ang), math.sin(ang))
        half = length // 2
        for i in range(0, n, length):
            w = 1 + 0j
            for k in range(half):
                u = buf[i + k]
                v = buf[i + k + half] * w
                buf[i + k] = u + v
                buf[i + k + half] = u - v
                w *= wlen
        length <<= 1


def hann(n: int) -> list[float]:
    if n <= 1:
        return [1.0] * n
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]


def rfft_magnitudes(samples: Sequence[float]) -> list[float]:
    """Real FFT magnitudes for a power-of-two window. DC..Nyquist inclusive."""
    n = len(samples)
    if n < 2 or n & (n - 1):
        msg = "FFT window must be a power of two"
        raise ValueError(msg)
    window = hann(n)
    buf = [complex(samples[i] * window[i], 0.0) for i in range(n)]
    _fft_inplace(buf)
    scale = 2.0 / n
    nyquist = n // 2
    mags = [abs(buf[k]) * scale for k in range(nyquist + 1)]
    mags[0] *= 0.5
    mags[-1] *= 0.5
    return mags


def _read_window(path: Path, *, start: int, count: int) -> tuple[list[float], int, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            msg = "spectrum expects mono 16-bit WAV"
            raise ValueError(msg)
        total = wav.getnframes()
        rate = wav.getframerate()
        samples = [0.0] * count
        if count < 1:
            return samples, rate, total
        i0 = max(0, start)
        n = min(count, total - i0) if i0 < total else 0
        if n <= 0:
            return samples, rate, total
        wav.setpos(i0)
        raw = wav.readframes(n)
        dest = i0 - start
        for j in range(n):
            sample = int.from_bytes(raw[j * 2 : j * 2 + 2], "little", signed=True)
            idx = dest + j
            if 0 <= idx < count:
                samples[idx] = float(sample) / 32768.0
        return samples, rate, total


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


def auto_frequency_span(path: Path) -> FrequencySpan:
    with wave.open(str(path), "rb") as wav:
        total = wav.getnframes()
        rate = wav.getframerate()
    nyquist = float(rate) / 2.0
    hop = max(FFT_SIZE, round(rate * ANALYSIS_HOP_SECONDS))
    acc: list[float] | None = None
    start = 0
    while start < total:
        samples, _, _ = _read_window(path, start=start, count=FFT_SIZE)
        power = power_spectrum(samples)
        if acc is None:
            acc = power
        else:
            for i, value in enumerate(power):
                acc[i] += value
        start += hop
    if acc is None:
        return FrequencySpan(AUTO_FALLBACK_FMIN, min(AUTO_FALLBACK_FMAX, nyquist), "auto")
    lo, hi, centroid = _energy_percentiles(acc, rate)
    lo = lo / math.sqrt(2.0)
    hi = hi * math.sqrt(2.0)
    if hi / max(lo, HEARING_FMIN) < MIN_SPAN_RATIO:
        lo = centroid / math.sqrt(MIN_SPAN_RATIO)
        hi = centroid * math.sqrt(MIN_SPAN_RATIO)
    fmin, fmax = clamp_span(lo, hi, nyquist)
    return FrequencySpan(fmin, fmax, "auto")


def resolve_frequency_span(path: Path, signal: dict[str, object]) -> FrequencySpan:
    _mode, explicit_min, explicit_max = frequency_config_from_signal(signal)
    with wave.open(str(path), "rb") as wav:
        nyquist = float(wav.getframerate()) / 2.0
    if explicit_min is not None and explicit_max is not None and explicit_max > explicit_min:
        fmin, fmax = clamp_span(explicit_min, explicit_max, nyquist)
        return FrequencySpan(fmin, fmax, "explicit")
    return auto_frequency_span(path)


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


def log_band_rms(
    magnitudes: Sequence[float],
    *,
    sample_rate: int,
    fmin_hz: float,
    fmax_hz: float,
    n_bands: int,
) -> list[float]:
    """RMS energy in log-spaced bands. Empty bands stay 0."""
    count = max(2, int(n_bands))
    if sample_rate < 1 or fmax_hz <= fmin_hz or len(magnitudes) < 2:
        return [0.0] * count
    n_fft = (len(magnitudes) - 1) * 2
    ratio = fmax_hz / fmin_hz
    out = [0.0] * count
    for i in range(count):
        lo = fmin_hz * (ratio ** (i / count))
        hi = fmin_hz * (ratio ** ((i + 1) / count))
        k0 = lo * n_fft / float(sample_rate)
        k1 = hi * n_fft / float(sample_rate)
        width = max(k1 - k0, 1e-12)
        out[i] = math.sqrt(_integrate_power(magnitudes, k0, k1) / width)
    return out


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
    return [
        pchip_eval(knots, slopes, remap_band_index(x / denom, n_bands=n, pivot=pivot), unit=False)
        for x in range(width)
    ]


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
    kernel = gaussian_kernel(sigma)
    radius = len(kernel) // 2
    out = [0.0] * n
    for i in range(n):
        acc = 0.0
        for k, weight in enumerate(kernel):
            j = i + k - radius
            if j < 0:
                j = 0
            elif j >= n:
                j = n - 1
            acc += float(values[j]) * weight
        out[i] = acc
    return out


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
    mags = rfft_magnitudes(samples)
    count = max(2, int(n_bands))
    rms = log_band_rms(
        mags,
        sample_rate=rate,
        fmin_hz=span.fmin_hz,
        fmax_hz=span.fmax_hz,
        n_bands=count,
    )
    gains = tilt_gains(
        count,
        fmin_hz=span.fmin_hz,
        fmax_hz=span.fmax_hz,
        db_per_octave=tilt_db_per_octave,
    )
    tilted = [rms[i] * gains[i] for i in range(count)]
    scaled = [_scale_open(v, scale) for v in tilted]
    return compress_bands(scaled, compress)


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
