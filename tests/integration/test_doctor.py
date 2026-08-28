from ewp_waveform.application.service import doctor


def test_doctor_passes_on_reference_ffmpeg() -> None:
    assert doctor() == []
