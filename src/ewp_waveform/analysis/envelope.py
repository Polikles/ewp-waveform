"""RMS envelope over a sliding time window. Source audio is not modified."""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ENVELOPE_OVERSAMPLE_ALLOWED = frozenset({1, 2, 4, 8})
ENVELOPE_AA_ALLOWED = frozenset({"none", "area", "lanczos"})


def envelope_oversample_from_signal(signal: dict[str, object]) -> int:
    raw = signal.get("envelope_oversample", 1)
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int) and raw in ENVELOPE_OVERSAMPLE_ALLOWED:
        return raw
    if isinstance(raw, float) and int(raw) == raw and int(raw) in ENVELOPE_OVERSAMPLE_ALLOWED:
        return int(raw)
    return 1


def envelope_aa_from_signal(signal: dict[str, object]) -> tuple[str, float]:
    """Return (kind, support_in_output_pixels). Independent of ``smoothing``."""
    raw_kind = signal.get("envelope_aa", "none")
    kind = str(raw_kind or "none").lower()
    if kind not in ENVELOPE_AA_ALLOWED:
        kind = "none"
    support = 2.0 if kind == "lanczos" else 1.0
    raw_support = signal.get("envelope_aa_support")
    if (
        isinstance(raw_support, int | float)
        and not isinstance(raw_support, bool)
        and raw_support > 0
    ):
        support = float(raw_support)
    return kind, support


MOTION_LPF_ALLOWED = frozenset({"none", "sinc", "gaussian"})


def motion_lpf_from_signal(signal: dict[str, object]) -> tuple[str, float, float]:
    """Return (kind, explicit_cutoff_cyc_px or 0 for auto, safety margin)."""
    kind = str(signal.get("envelope_motion_lpf") or "sinc").lower()
    if kind not in MOTION_LPF_ALLOWED:
        kind = "sinc"
    cutoff = 0.0
    raw_c = signal.get("envelope_motion_cutoff")
    if isinstance(raw_c, int | float) and not isinstance(raw_c, bool) and raw_c > 0:
        cutoff = float(raw_c)
    margin = 0.85
    raw_m = signal.get("envelope_motion_margin")
    if isinstance(raw_m, int | float) and not isinstance(raw_m, bool) and raw_m > 0:
        margin = float(raw_m)
    return kind, cutoff, margin


def motion_cutoff_cyc_px(
    *,
    width: int,
    window_seconds: float,
    fps: float,
    margin: float = 0.85,
    explicit: float = 0.0,
) -> float:
    """Temporal Nyquist in cycles/output-pixel: fps / (2 * width/window)."""
    if explicit > 0.0:
        return explicit
    if width < 1 or window_seconds <= 0.0 or fps <= 0.0:
        return 0.0
    velocity = width / window_seconds
    nyquist = fps / (2.0 * velocity)
    return nyquist * min(max(margin, 0.05), 1.0)


def hop_samples(
    sample_rate: int,
    width: int,
    window_seconds: float,
    oversample: int = 1,
) -> float:
    """Ideal hop in samples. Not truncated; bin edges use absolute positions."""
    if width < 1 or window_seconds <= 0 or sample_rate < 1 or oversample < 1:
        msg = "invalid envelope hop parameters"
        raise ValueError(msg)
    return float(sample_rate) * window_seconds / float(width * oversample)


def rms_bins_from_wav(path: Path, hop: float) -> list[float]:
    """Return one RMS value per hop of mono s16le WAV.

    Bin edges are ``i * hop`` in absolute sample coordinates. A truncated integer
    hop is not used, so window mapping does not drift.
    """
    if hop <= 0.0:
        msg = "hop must be positive"
        raise ValueError(msg)
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1:
            msg = f"envelope expects mono WAV, got {wav.getnchannels()} channels"
            raise ValueError(msg)
        if wav.getsampwidth() != 2:
            msg = "envelope expects 16-bit PCM"
            raise ValueError(msg)
        total = wav.getnframes()
        bins: list[float] = []
        file_pos = 0
        bin_index = 0
        while True:
            start = float(bin_index) * hop
            if start >= total:
                break
            end = min(start + hop, float(total))
            i0 = math.floor(start)
            i1 = min(total, math.ceil(end))
            if i1 <= i0:
                break
            if i0 > file_pos:
                wav.readframes(i0 - file_pos)
                file_pos = i0
            raw = wav.readframes(i1 - file_pos)
            file_pos = i1
            count = len(raw) // 2
            if count == 0:
                break
            acc = 0.0
            weight_sum = 0.0
            for j in range(count):
                abs_i = i0 + j
                left = max(float(abs_i), start)
                right = min(float(abs_i + 1), end)
                weight = right - left
                if weight <= 0.0:
                    continue
                sample = int.from_bytes(raw[j * 2 : j * 2 + 2], "little", signed=True)
                acc += weight * float(sample) * float(sample)
                weight_sum += weight
            if weight_sum > 0.0:
                bins.append(math.sqrt(acc / weight_sum) / 32768.0)
            bin_index += 1
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


def bin_peak(bins: Sequence[float], percentile: float = 95.0) -> float:
    """Percentile of active envelope bins. Silence is ignored. 0 if none."""
    active = [v for v in bins if v > 1e-4]
    if not active:
        return 0.0
    ordered = sorted(active)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile / 100.0)))
    return ordered[index]


def normalize_bins(
    bins: Sequence[float],
    *,
    percentile: float = 95.0,
    soft_clip: bool = False,
    knee: float = 0.88,
    peak: float | None = None,
) -> list[float]:
    """Scale visualization bins so typical peaks fill the range. Does not touch source audio.

    ``peak`` is the global scale when chunking; if omitted it is measured from ``bins``.
    """
    measured = bin_peak(bins, percentile) if peak is None else peak
    if measured <= 0.0:
        return list(bins)
    if not soft_clip:
        return [min(1.0, v / measured) for v in bins]
    scale = knee / measured
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


def read_bin(bins: Sequence[float], index: float) -> float:
    """Linear interpolation at a fractional envelope index. Out of range is 0. Not clamped."""
    if not bins:
        return 0.0
    i0 = math.floor(index)
    t = index - i0

    def at(i: int) -> float:
        if 0 <= i < len(bins):
            return float(bins[i])
        return 0.0

    if t <= 1e-12:
        return at(i0)
    return at(i0) * (1.0 - t) + at(i0 + 1) * t


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


def window_from_origin(
    bins: Sequence[float],
    *,
    global_end_exclusive: int,
    width: int,
    origin: float,
) -> list[float]:
    """Window ending at a global bin index when ``bins[0]`` sits at ``origin``."""
    start = float(global_end_exclusive - width) - origin
    return [read_bin(bins, start + i) for i in range(width)]


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


def _lanczos_weight(x: float, a: float) -> float:
    if abs(x) < 1e-12:
        return 1.0
    if abs(x) >= a:
        return 0.0
    px = math.pi * x
    return (a * math.sin(px) * math.sin(px / a)) / (px * px)


def _normalize_kernel(taps: list[float]) -> list[float]:
    total = sum(taps)
    if total <= 0.0:
        return [1.0]
    return [tap / total for tap in taps]


def reconstruction_kernel(kind: str, *, oversample: int, support_px: float) -> list[float]:
    """FIR taps in dense-bin steps. ``support_px`` is in output pixels."""
    support_px = max(support_px, 1.0 / oversample)
    if kind == "area":
        half_px = support_px / 2.0
        radius = max(1, math.ceil(half_px * oversample))
        taps = []
        for k in range(-radius, radius + 1):
            x = abs(k / oversample)
            taps.append(1.0 if x <= half_px + 1e-12 else 0.0)
        return _normalize_kernel(taps)
    if kind == "lanczos":
        a = max(support_px, 1.0)
        radius = max(1, math.ceil(a * oversample))
        taps = [_lanczos_weight(k / oversample, a) for k in range(-radius, radius + 1)]
        return _normalize_kernel(taps)
    return [1.0]


def _convolve_zero_pad(values: Sequence[float], kernel: Sequence[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    radius = len(kernel) // 2
    out = [0.0] * n
    for i in range(n):
        acc = 0.0
        for k, weight in enumerate(kernel):
            j = i + k - radius
            if 0 <= j < n:
                acc += float(values[j]) * weight
        out[i] = acc
    return out


def antialias_envelope(
    bins: Sequence[float],
    *,
    oversample: int,
    kind: str,
    support_px: float,
) -> list[float]:
    """Band-limit a dense envelope to output-pixel Nyquist. Not a shape-changing blur.

    ``kind`` is ``none``, ``area`` (box of ``support_px`` output pixels) or ``lanczos``.
    """
    if kind == "none" or oversample <= 1 or len(bins) < 2:
        return list(bins)
    kernel = reconstruction_kernel(kind, oversample=oversample, support_px=support_px)
    if len(kernel) <= 1:
        return list(bins)
    return _convolve_zero_pad(bins, kernel)


def _unit_sinc(x: float) -> float:
    if abs(x) < 1e-12:
        return 1.0
    return math.sin(math.pi * x) / (math.pi * x)


def motion_lpf_kernel(*, kind: str, oversample: int, cutoff_cyc_px: float) -> list[float]:
    """Low-pass FIR in dense-bin steps. ``cutoff_cyc_px`` is cycles per output pixel."""
    if cutoff_cyc_px <= 0.0 or oversample < 1:
        return [1.0]
    fc = min(cutoff_cyc_px / float(oversample), 0.49)
    if kind == "gaussian":
        sigma_px = math.sqrt(math.log(2.0)) / (2.0 * math.pi * cutoff_cyc_px)
        sigma_bins = max(0.5, sigma_px * oversample)
        radius = max(1, math.ceil(3.0 * sigma_bins))
        taps = [math.exp(-0.5 * (k / sigma_bins) ** 2) for k in range(-radius, radius + 1)]
        return _normalize_kernel(taps)
    radius = max(8, math.ceil(3.0 / (2.0 * max(fc, 1e-6))))
    taps = []
    for n in range(-radius, radius + 1):
        h = 2.0 * fc * _unit_sinc(2.0 * fc * n)
        window = 0.5 + 0.5 * math.cos(math.pi * n / radius)
        taps.append(h * window)
    return _normalize_kernel(taps)


def motion_lpf_envelope(
    bins: Sequence[float],
    *,
    oversample: int,
    cutoff_cyc_px: float,
    kind: str = "sinc",
) -> list[float]:
    """Remove envelope features above temporal Nyquist. Raster edges stay crisp."""
    if kind == "none" or cutoff_cyc_px <= 0.0 or oversample < 1 or len(bins) < 2:
        return list(bins)
    kernel = motion_lpf_kernel(kind=kind, oversample=oversample, cutoff_cyc_px=cutoff_cyc_px)
    if len(kernel) <= 1:
        return list(bins)
    return _convolve_zero_pad(bins, kernel)


def envelope_context_bins(
    *,
    oversample: int,
    aa_kind: str,
    aa_support: float,
    lpf_kind: str,
    lpf_cutoff: float,
    smoothing_sigma: float = 0.0,
) -> int:
    """Half-width of causal/anti-causal FIR context on the dense envelope, in bins."""
    radius = 0
    if aa_kind != "none" and oversample > 1:
        kernel = reconstruction_kernel(aa_kind, oversample=oversample, support_px=aa_support)
        radius = max(radius, len(kernel) // 2)
    if lpf_kind != "none" and lpf_cutoff > 0.0:
        kernel = motion_lpf_kernel(kind=lpf_kind, oversample=oversample, cutoff_cyc_px=lpf_cutoff)
        radius = max(radius, len(kernel) // 2)
    if smoothing_sigma > 0.0:
        radius += max(1, round(smoothing_sigma)) * 3
    return radius


def envelope_preroll_seconds(
    *,
    window_seconds: float,
    width: int,
    oversample: int,
    context_bins: int,
    extra_px: int = 0,
) -> tuple[float, float]:
    """Return ``(preroll, postroll)`` so the first/last published frame has FIR context.

    Preroll also covers the visible scroll window (right edge is 'now').
    """
    if width < 1 or window_seconds <= 0.0 or oversample < 1:
        return max(window_seconds, 0.0), 0.0
    bins_per_second = float(width * oversample) / window_seconds
    pad = float(max(0, context_bins) + max(0, extra_px) * oversample) / bins_per_second
    return window_seconds + pad, pad


def process_envelope_bins(
    bins: Sequence[float],
    *,
    scale: str,
    smoothing_sigma: float = 0.0,
    oversample: int = 1,
    aa_kind: str = "none",
    aa_support: float = 1.0,
    lpf_kind: str = "none",
    lpf_cutoff: float = 0.0,
) -> list[float]:
    """Scale, smooth, reconstruct, motion-LPF. Normalization is a separate global step."""
    out = [scale_amplitude(v, scale) for v in bins]
    if smoothing_sigma > 0.0:
        out = smooth_bins(out, sigma=smoothing_sigma)
    out = antialias_envelope(out, oversample=oversample, kind=aa_kind, support_px=aa_support)
    return motion_lpf_envelope(out, oversample=oversample, cutoff_cyc_px=lpf_cutoff, kind=lpf_kind)


def published_bin_slice(
    bins: Sequence[float],
    *,
    start_seconds: float,
    end_seconds: float,
    origin_seconds: float,
    bins_per_second: float,
) -> list[float]:
    """Bins whose time falls in ``[start_seconds, end_seconds)`` on the clip timeline."""
    if bins_per_second <= 0.0 or not bins:
        return []
    lo = (start_seconds - origin_seconds) * bins_per_second
    hi = (end_seconds - origin_seconds) * bins_per_second
    i0 = max(0, math.floor(lo))
    i1 = min(len(bins), math.ceil(hi))
    if i1 <= i0:
        return []
    return list(bins[i0:i1])


def sample_bin(bins: Sequence[float], index: float) -> float:
    """Linear interpolation at a fractional envelope index. Out of range is 0."""
    return min(max(read_bin(bins, index), 0.0), 1.0)


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
