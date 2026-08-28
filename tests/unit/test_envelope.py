import struct
import wave
from pathlib import Path

from ewp_waveform.analysis.envelope import (
    column_offset,
    column_offset_float,
    hop_samples,
    normalize_bins,
    rms_bins_from_wav,
    sample_bin,
    window_at_column,
    window_at_time,
)


def _write_mono_s16(path: Path, samples: list[int], rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def test_hop_samples_covers_window() -> None:
    assert hop_samples(48000, 1400, 5.0) == max(1, int(48000 * 5.0 / 1400))


def test_window_pads_before_audio_starts() -> None:
    bins = [0.1, 0.2, 0.3]
    got = window_at_time(bins, time_seconds=0.0, sample_rate=4, hop=1, width=4)
    assert got == [0.0, 0.0, 0.0, 0.1]


def test_scroll_is_translation_of_frozen_bins() -> None:
    bins = [0.1 * i for i in range(20)]
    width = 8
    first = window_at_column(bins, end_exclusive=8, width=width)
    second = window_at_column(bins, end_exclusive=11, width=width)
    assert second[:5] == first[3:]


def test_column_offset_is_integer_pixels() -> None:
    assert column_offset(0, 30.0, 5.0, 1400) == 0
    assert column_offset(30, 30.0, 5.0, 1400) == 1400 // 5
    assert column_offset_float(1, 30.0, 5.0, 1400) == 1400 / (5.0 * 30.0)


def test_normalize_raises_typical_peaks_without_using_silence() -> None:
    bins = [0.0] * 10 + [0.2, 0.2, 0.25]
    out = normalize_bins(bins, percentile=100)
    assert out[-1] == 1.0
    assert out[0] == 0.0


def test_sample_bin_lerps_adjacent_values() -> None:
    bins = [0.0, 1.0]
    assert sample_bin(bins, 0.0) == 0.0
    assert sample_bin(bins, 1.0) == 1.0
    assert abs(sample_bin(bins, 0.5) - 0.5) < 1e-9
    assert sample_bin(bins, -1.0) == 0.0
    assert sample_bin(bins, 3.0) == 0.0


def test_soft_clip_maps_percentile_to_knee_not_a_hard_ceiling() -> None:
    bins = [0.10] * 90 + [0.20] * 9 + [0.22]
    out = normalize_bins(bins, percentile=95.0, soft_clip=True, knee=0.88)
    assert max(out[:99]) <= 0.88 + 1e-6
    assert 0.88 < out[-1] < 1.0


def test_rms_silence_is_zero(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    _write_mono_s16(path, [0] * 8000)
    bins = rms_bins_from_wav(path, hop=800)
    assert bins
    assert max(bins) == 0.0


def test_rms_full_scale_is_near_one(tmp_path: Path) -> None:
    path = tmp_path / "full.wav"
    _write_mono_s16(path, [32767] * 1600)
    bins = rms_bins_from_wav(path, hop=800)
    assert all(v > 0.99 for v in bins)
