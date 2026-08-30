from ewp_waveform.application.service import capabilities
from ewp_waveform.domain.diagnostics import CapabilityLevel
from ewp_waveform.ffmpeg.doctor import REQUIRED_ENCODERS, REQUIRED_FILTERS


def test_particles_unsupported() -> None:
    items = {item.name: item for item in capabilities()}
    assert items["effect:particles"].level == CapabilityLevel.UNSUPPORTED
    assert items["domain:time+playhead"].level == CapabilityLevel.UNSUPPORTED
    assert items["domain:frequency+fixed-axis"].level == CapabilityLevel.EXPERIMENTAL
    assert items["style:mirrored"].level == CapabilityLevel.LIMITED


def test_doctor_requires_encode_path_not_stock_showwaves() -> None:
    assert REQUIRED_ENCODERS == ("prores_ks", "png")
    assert REQUIRED_FILTERS == ("gblur", "overlay", "scale")
    assert "showwaves" not in REQUIRED_FILTERS
    assert "showfreqs" not in REQUIRED_FILTERS
