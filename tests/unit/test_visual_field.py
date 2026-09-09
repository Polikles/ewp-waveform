from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.visual.mapping import CENTER_OUT_SLOTS, CenterOutMapping, center_out_weights
from ewp_waveform.visual.ribbon import field_to_columns, render_ribbon_frame


def test_analysis_frame_is_audio_domain_only() -> None:
    frame = AnalysisFrame.from_bands([0.1, 0.5, 0.2])
    assert frame.bands == (0.1, 0.5, 0.2)
    assert frame.overall_level == 0.5


def test_center_out_mapping_is_static_and_odd_width() -> None:
    mapping = CenterOutMapping(n_slots=65, n_bands=64)
    assert mapping.n_slots == CENTER_OUT_SLOTS
    assert mapping.n_slots % 2 == 1
    assert mapping.center == 32
    frame = AnalysisFrame.from_bands([0.2] * 64)
    assert mapping.apply(frame) == mapping.apply(frame)
    assert mapping.weights == center_out_weights(65, 64)


def test_center_out_has_one_center_peak_not_a_split() -> None:
    bands = [0.0] * 64
    bands[0] = 1.0
    field = CenterOutMapping().apply(AnalysisFrame.from_bands(bands))
    amps = field.amplitude
    peak_at = amps.index(max(amps))
    assert peak_at == 32
    assert amps[32] > amps[31]
    assert amps[32] > amps[33]
    assert amps[31] > amps[30]
    assert amps[33] > amps[34]


def test_left_and_right_are_not_mirrors() -> None:
    bands = [0.0] * 64
    bands[1] = 1.0
    bands[2] = 0.2
    amps = CenterOutMapping().apply(AnalysisFrame.from_bands(bands)).amplitude
    center = 32
    assert amps[center + 1] > amps[center - 1]
    mirrored = tuple(reversed(amps))
    assert amps != mirrored


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
