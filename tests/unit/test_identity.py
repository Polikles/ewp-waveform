from ewp_waveform.config.load import load_preset
from ewp_waveform.identity import render_signature


def test_preview_clip_is_not_the_full_file_identity() -> None:
    preset = load_preset("iuris-default")
    full = render_signature(source_sha256="abc", preset=preset, fps=60.0)
    preview = render_signature(
        source_sha256="abc", preset=preset, fps=60.0, clip_start=0.0, clip_duration=8.0
    )
    assert full != preview
    again = render_signature(source_sha256="abc", preset=preset, fps=60.0)
    assert again == full
