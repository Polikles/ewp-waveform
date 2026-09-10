from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.visual.mapping import CENTER_OUT_SLOTS, CenterOutMapping
from ewp_waveform.visual.ribbon import field_to_columns, render_ribbon_frame


def test_analysis_frame_is_audio_domain_only() -> None:
    frame = AnalysisFrame.from_bands([0.1, 0.5, 0.2])
    assert frame.bands == (0.1, 0.5, 0.2)
    assert frame.overall_level is not None
    expected = (0.1**2 + 0.5**2 + 0.2**2) / 3.0
    assert abs(frame.overall_level - expected**0.5) < 1e-12


def test_center_out_mapping_is_static_and_odd_width() -> None:
    mapping = CenterOutMapping(n_slots=65, n_bands=64)
    assert mapping.n_slots == CENTER_OUT_SLOTS
    assert mapping.n_slots % 2 == 1
    assert mapping.center == 32
    frame = AnalysisFrame.from_bands([0.2] * 64)
    assert mapping.apply(frame) == mapping.apply(frame)
    assert mapping.core_radius == 5
    assert mapping.visual_gain[32] == 1.0
    assert mapping.visual_gain[32] > mapping.visual_gain[31] > mapping.visual_gain[29]


def test_center_out_has_one_center_peak_not_a_split() -> None:
    bands = [0.15] * 64
    bands[0] = 0.6
    bands[1] = 1.0
    bands[2] = 1.0
    mapping = CenterOutMapping()
    amps = mapping.apply(AnalysisFrame.from_bands(bands)).amplitude
    center = mapping.center
    peak_at = amps.index(max(amps))
    assert peak_at == center
    for offset in range(mapping.core_radius):
        assert amps[center - offset] > amps[center - offset - 1]
        assert amps[center + offset] > amps[center + offset + 1]
    for offset in range(1, mapping.core_radius + 1):
        assert abs(amps[center - offset] - amps[center + offset]) < 1e-12
        expected = mapping.visual_gain[center - offset]
        assert abs(amps[center - offset] / amps[center] - expected) < 1e-9
    lo = center - mapping.core_radius
    hi = center + mapping.core_radius
    side_peak = max(amps[i] for i in range(len(amps)) if i < lo or i > hi)
    assert side_peak <= mapping.side_to_center * amps[center] + 1e-12


def test_left_and_right_are_not_mirrors() -> None:
    bands = [0.05] * 64
    bands[10] = 1.0
    bands[40] = 0.2
    mapping = CenterOutMapping()
    amps = mapping.apply(AnalysisFrame.from_bands(bands)).amplitude
    assert amps != tuple(reversed(amps))
    assert amps[mapping.center] == max(amps)


def test_visual_field_width_is_independent_of_band_count() -> None:
    mapping = CenterOutMapping(n_slots=21, n_bands=8)
    field = mapping.apply(AnalysisFrame.from_bands([0.1] * 8))
    assert field.n_slots == 21
    assert len(field.amplitude) != 8


def test_ribbon_renderer_consumes_only_a_visual_field() -> None:
    field = CenterOutMapping(n_slots=17, n_bands=8).apply(AnalysisFrame.from_bands([0.4] * 8))
    columns = field_to_columns(field, 40)
    assert len(columns) == 40
    frame = render_ribbon_frame(
        field,
        width=40,
        height=24,
        color="#C7E6EC",
        amplitude=1.0,
        center_line=True,
        supersample=1,
    )
    assert len(frame) == 40 * 24 * 4
