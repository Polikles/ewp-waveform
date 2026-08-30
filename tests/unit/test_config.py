from ewp_waveform.config.load import load_application_config, load_performance, load_preset


def test_builtin_iuris_default_is_time_scroll_mirrored() -> None:
    preset = load_preset("iuris-default")
    assert preset.name == "iuris-default"
    assert preset.waveform.style == "mirrored"
    assert preset.waveform.domain == "time"
    assert preset.waveform.time_mode == "scroll"
    assert preset.canvas.fps == 60
    assert preset.waveform.window_seconds == 5.0
    assert preset.waveform.amplitude == 1.0
    assert preset.waveform.stroke_width == 6.0
    assert preset.signal.get("envelope_oversample") == 4
    smoothing = preset.signal.get("smoothing")
    assert smoothing == 0
    assert preset.signal.get("envelope_aa") == "area"
    support = preset.signal.get("envelope_aa_support")
    assert support == 1 or support == 1.0
    shutter = preset.signal.get("shutter_degrees")
    assert shutter == 0 or shutter == 0.0
    assert preset.signal.get("envelope_motion_lpf") == "sinc"


def test_builtin_iuris_spectrum_is_frequency_domain() -> None:
    preset = load_preset("iuris-spectrum")
    assert preset.waveform.domain == "frequency"
    assert preset.waveform.style == "mirrored"
    freq = preset.signal.get("frequency")
    assert isinstance(freq, dict)
    assert freq.get("range") == "auto"


def test_default_application_config() -> None:
    cfg = load_application_config()
    assert cfg.defaults.preset == "iuris-default"
    assert cfg.input.recursive is False
    assert cfg.input.grouping.separator == "-"


def test_balanced_performance_loads() -> None:
    profile = load_performance("balanced")
    assert profile.name == "balanced"
