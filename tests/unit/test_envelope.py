import math
import struct
import wave
from itertools import pairwise
from pathlib import Path

from ewp_waveform.analysis.envelope import (
    antialias_envelope,
    bin_peak,
    column_offset,
    column_offset_float,
    envelope_aa_from_signal,
    envelope_context_bins,
    envelope_oversample_from_signal,
    envelope_preroll_seconds,
    hop_samples,
    iter_scroll_timing,
    motion_cutoff_cyc_px,
    motion_lpf_envelope,
    motion_lpf_kernel,
    normalize_bins,
    process_envelope_bins,
    published_bin_slice,
    reconstruction_kernel,
    rms_bins_from_wav,
    sample_bin,
    smooth_bins,
    window_at_column,
    window_at_time,
    window_from_origin,
)


def _write_mono_s16(path: Path, samples: list[int], rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def test_hop_samples_covers_window() -> None:
    assert hop_samples(48000, 1400, 5.0) == 48000 * 5.0 / 1400


def test_hop_samples_shrinks_with_envelope_oversample() -> None:
    one = hop_samples(48000, 1400, 5.0, oversample=1)
    four = hop_samples(48000, 1400, 5.0, oversample=4)
    assert four * 4 == one
    assert four == 48000 * 5.0 / (1400 * 4)


def test_envelope_oversample_from_signal_allows_powers_of_two() -> None:
    assert envelope_oversample_from_signal({}) == 1
    assert envelope_oversample_from_signal({"envelope_oversample": 4}) == 4
    assert envelope_oversample_from_signal({"envelope_oversample": 3}) == 1


def test_envelope_aa_from_signal_defaults() -> None:
    assert envelope_aa_from_signal({}) == ("none", 1.0)
    assert envelope_aa_from_signal({"envelope_aa": "lanczos"})[0] == "lanczos"
    assert envelope_aa_from_signal({"envelope_aa": "lanczos"})[1] == 2.0
    assert envelope_aa_from_signal({"envelope_aa": "area", "envelope_aa_support": 1.0}) == (
        "area",
        1.0,
    )


def test_reconstruction_kernel_is_normalized() -> None:
    for kind, support in (("area", 1.0), ("lanczos", 2.0)):
        kernel = reconstruction_kernel(kind, oversample=4, support_px=support)
        assert abs(sum(kernel) - 1.0) < 1e-9


def test_antialias_none_is_identity() -> None:
    bins = [0.1, 0.8, 0.2, 0.4]
    assert antialias_envelope(bins, oversample=4, kind="none", support_px=1.0) == bins


def test_antialias_area_kills_subpixel_spike_keeps_wide_peak() -> None:
    oversample = 4
    spike = [0.0] * 40 + [1.0] + [0.0] * 40
    wide = [0.0] * 36 + [1.0] * 8 + [0.0] * 36
    a_spike = antialias_envelope(spike, oversample=oversample, kind="area", support_px=1.0)
    a_wide = antialias_envelope(wide, oversample=oversample, kind="area", support_px=1.0)
    assert max(a_spike) < 0.55
    assert max(a_wide) > 0.7


def test_motion_cutoff_matches_scroll_nyquist() -> None:
    full = motion_cutoff_cyc_px(width=1400, window_seconds=5.0, fps=60.0, margin=1.0)
    assert abs(full - 60.0 / (2.0 * 280.0)) < 1e-12
    safe = motion_cutoff_cyc_px(width=1400, window_seconds=5.0, fps=60.0, margin=0.85)
    assert 0.08 < safe < 0.10


def test_higher_fps_raises_motion_cutoff() -> None:
    slow = motion_cutoff_cyc_px(width=1400, window_seconds=5.0, fps=60.0, margin=1.0)
    fast = motion_cutoff_cyc_px(width=1400, window_seconds=5.0, fps=120.0, margin=1.0)
    assert abs(fast - 2.0 * slow) < 1e-12


def test_motion_lpf_kills_needles_keeps_broad_lobe() -> None:
    oversample = 4
    n = 400
    comb = [0.5 + 0.5 * math.sin(2 * math.pi * i / (2 * oversample)) for i in range(n)]
    lobe = [0.5 + 0.5 * math.sin(2 * math.pi * i / (40 * oversample)) for i in range(n)]
    cutoff = 0.09
    comb_out = motion_lpf_envelope(comb, oversample=oversample, cutoff_cyc_px=cutoff, kind="sinc")
    lobe_out = motion_lpf_envelope(lobe, oversample=oversample, cutoff_cyc_px=cutoff, kind="sinc")
    mid_c = comb_out[80:-80]
    mid_l = lobe_out[80:-80]
    assert max(mid_c) - min(mid_c) < 0.2
    assert max(mid_l) - min(mid_l) > 0.7


def test_antialias_preserves_flat_interior() -> None:
    bins = [0.4] * 80
    out = antialias_envelope(bins, oversample=4, kind="lanczos", support_px=2.0)
    assert abs(out[40] - 0.4) < 1e-9


def test_wider_aa_kills_one_pixel_hair_keeps_few_pixel_peak() -> None:
    """A 1 output-px hair (4 dense bins) must not survive support=3; a 4 px lobe should."""
    oversample = 4
    hair = [0.0] * 40 + [1.0] * 4 + [0.0] * 40
    lobe = [0.0] * 32 + [1.0] * 16 + [0.0] * 32
    a_hair = antialias_envelope(hair, oversample=oversample, kind="area", support_px=3.0)
    a_lobe = antialias_envelope(lobe, oversample=oversample, kind="area", support_px=3.0)
    assert max(a_hair) < 0.55
    assert max(a_lobe) > 0.75


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


def test_scroll_timing_delta_is_constant() -> None:
    fps = 60.0
    window = 5.0
    width = 1400
    oversample = 4
    expected = width / (window * fps)
    rows = iter_scroll_timing(
        16, fps=fps, window_seconds=window, width=width, oversample=oversample
    )
    header = "frame  timestamp  scroll_phase  frac  expected_dpx  env_pos"
    table = "\n".join([header, *(row.as_row() for row in rows)])
    print(table)
    assert abs(rows[0].expected_delta_px - expected) < 1e-12
    for prev, cur in pairwise(rows):
        actual_px = cur.scroll_phase - prev.scroll_phase
        actual_env = cur.envelope_position - prev.envelope_position
        assert abs(actual_px - expected) < 1e-9
        assert abs(actual_env - expected * oversample) < 1e-9
        assert abs((cur.timestamp - prev.timestamp) - 1.0 / fps) < 1e-12


def test_scroll_four_point_six_six_phase_cycle() -> None:
    """1400 px / 5 s / 60 fps = 14/3 px/frame; frac cycles 0, 2/3, 1/3."""
    expected = 1400.0 / (5.0 * 60.0)
    assert abs(expected - 14.0 / 3.0) < 1e-12
    rows = iter_scroll_timing(9, fps=60.0, window_seconds=5.0, width=1400, oversample=4)
    for prev, cur in pairwise(rows):
        assert abs((cur.scroll_phase - prev.scroll_phase) - expected) < 1e-12
    fracs = [row.fractional_phase for row in rows]
    assert abs(fracs[0] - 0.0) < 1e-9
    assert abs(fracs[1] - 2.0 / 3.0) < 1e-9
    assert abs(fracs[2] - 1.0 / 3.0) < 1e-9
    assert abs(fracs[3] - 0.0) < 1e-9


def test_fractional_hop_uses_absolute_bin_edges(tmp_path: Path) -> None:
    path = tmp_path / "ten.wav"
    _write_mono_s16(path, [1000] * 10)
    assert len(rms_bins_from_wav(path, 5.0)) == 2
    assert len(rms_bins_from_wav(path, 3.5)) == 3


def test_normalize_raises_typical_peaks_without_using_silence() -> None:
    bins = [0.0] * 10 + [0.2, 0.2, 0.25]
    out = normalize_bins(bins, percentile=100)
    assert out[-1] == 1.0
    assert out[0] == 0.0


def test_smooth_bins_is_identity_when_sigma_zero() -> None:
    bins = [0.1, 0.8, 0.2]
    assert smooth_bins(bins, sigma=0.0) == bins


def test_smooth_bins_attenuates_a_one_bin_spike() -> None:
    bins = [0.1] * 40 + [1.0] + [0.1] * 40
    out = smooth_bins(bins, sigma=6.0)
    assert max(out) < 0.45
    assert out[40] < bins[40]


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


def test_window_from_origin_zero_matches_window_at_column() -> None:
    bins = [0.1 * i for i in range(20)]
    direct = window_at_column(bins, end_exclusive=11, width=8)
    shifted = window_from_origin(bins, global_end_exclusive=11, width=8, origin=0.0)
    assert shifted == direct


def test_window_from_origin_shifts_lookup() -> None:
    bins = [float(i) for i in range(10)]
    got = window_from_origin(bins, global_end_exclusive=8, width=4, origin=2.0)
    assert got == [2.0, 3.0, 4.0, 5.0]


def test_bin_peak_ignores_silence() -> None:
    assert bin_peak([0.0] * 10 + [0.2, 0.4], percentile=100) == 0.4
    assert bin_peak([0.0] * 8) == 0.0


def test_normalize_uses_supplied_peak() -> None:
    out = normalize_bins([0.1, 0.2], percentile=100, peak=0.4)
    assert abs(out[1] - 0.5) < 1e-12


def test_envelope_preroll_includes_window_and_fir_pad() -> None:
    kernel = motion_lpf_kernel(kind="sinc", oversample=4, cutoff_cyc_px=0.09)
    context = envelope_context_bins(
        oversample=4,
        aa_kind="area",
        aa_support=1.0,
        lpf_kind="sinc",
        lpf_cutoff=0.09,
    )
    assert context >= len(kernel) // 2
    preroll, postroll = envelope_preroll_seconds(
        window_seconds=5.0,
        width=1400,
        oversample=4,
        context_bins=context,
        extra_px=26,
    )
    assert preroll > 5.0
    assert postroll > 0.0
    assert abs(preroll - (5.0 + postroll)) < 1e-12


def test_process_envelope_bins_is_identity_for_open_settings() -> None:
    bins = [0.0, 0.25, 0.5, 0.25, 0.0]
    out = process_envelope_bins(bins, scale="linear")
    assert out == bins


def test_published_bin_slice_uses_origin() -> None:
    bins = [float(i) for i in range(20)]
    got = published_bin_slice(
        bins,
        start_seconds=1.0,
        end_seconds=2.0,
        origin_seconds=0.5,
        bins_per_second=4.0,
    )
    assert got == [2.0, 3.0, 4.0, 5.0]


def test_rms_full_scale_is_near_one(tmp_path: Path) -> None:
    path = tmp_path / "full.wav"
    _write_mono_s16(path, [32767] * 1600)
    bins = rms_bins_from_wav(path, hop=800)
    assert all(v > 0.99 for v in bins)
