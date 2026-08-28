from ewp_waveform.application.service import capabilities
from ewp_waveform.domain.diagnostics import CapabilityLevel


def test_particles_unsupported() -> None:
    items = {item.name: item for item in capabilities()}
    assert items["effect:particles"].level == CapabilityLevel.UNSUPPORTED
    assert items["domain:time+playhead"].level == CapabilityLevel.UNSUPPORTED
    assert items["domain:frequency+fixed-axis"].level == CapabilityLevel.EXPERIMENTAL
    assert items["style:mirrored"].level == CapabilityLevel.LIMITED
