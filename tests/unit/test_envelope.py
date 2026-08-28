import struct
import wave
from pathlib import Path

from ewp_waveform.analysis.envelope import hop_samples, rms_bins_from_wav, window_at_time


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
