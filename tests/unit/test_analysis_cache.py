from pathlib import Path

from ewp_waveform.analysis.cache import (
    analysis_cache_digest,
    analysis_cache_payload,
    load_analysis_cache,
    store_analysis_cache,
)
from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.analysis.spectrum import FrequencySpan


def _payload(
    *,
    source_sha256: str = "abc",
    n_bands: int = 64,
    tilt_db_per_octave: float = 3.0,
    signal: dict[str, object] | None = None,
) -> dict[str, object]:
    return analysis_cache_payload(
        source_sha256=source_sha256,
        clip_start=25.0,
        clip_duration=8.0,
        fps=60.0,
        n_frames=480,
        n_bands=n_bands,
        scale="sqrt",
        tilt_db_per_octave=tilt_db_per_octave,
        compress=0.75,
        signal=signal if signal is not None else {"frequency": {"range": "auto"}},
    )


def test_cache_key_ignores_visual_mapping_keys() -> None:
    payload = _payload()
    assert "ribbon_supersample" not in payload
    assert "glow" not in payload
    assert "spectrum_layout" not in payload
    assert analysis_cache_digest(payload) == analysis_cache_digest(_payload())


def test_analysis_settings_change_the_cache_key() -> None:
    base = analysis_cache_digest(_payload())
    assert analysis_cache_digest(_payload(n_bands=32)) != base
    assert analysis_cache_digest(_payload(tilt_db_per_octave=0.0)) != base
    assert analysis_cache_digest(_payload(source_sha256="other")) != base
    explicit = _payload(signal={"frequency": {"range": "auto", "fmin_hz": 80.0, "fmax_hz": 8000.0}})
    assert analysis_cache_digest(explicit) != base


def test_round_trip_sequence(tmp_path: Path) -> None:
    sequence = AnalysisSequence(
        frames=(
            AnalysisFrame.from_bands([0.1, 0.2, 0.3]),
            AnalysisFrame.from_bands([0.4, 0.5, 0.6]),
        )
    )
    span = FrequencySpan(80.0, 8000.0, "auto")
    digest = "deadbeef"
    store_analysis_cache(digest, sequence, span, directory=tmp_path)
    loaded = load_analysis_cache(digest, directory=tmp_path)
    assert loaded is not None
    got, got_span = loaded
    assert len(got) == 2
    assert got[0].bands == sequence[0].bands
    assert got_span == span
    assert load_analysis_cache("missing", directory=tmp_path) is None
