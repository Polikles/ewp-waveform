from pathlib import Path

from ewp_waveform.application.plan import classify_action
from ewp_waveform.application.render import planned_destinations
from ewp_waveform.config.load import load_preset
from ewp_waveform.domain.diagnostics import CapabilityLevel
from ewp_waveform.domain.models import PlannedJob, TimeMode, VisualizationDomain
from ewp_waveform.identity import sha256_file


def _job(path: Path) -> PlannedJob:
    return PlannedJob(
        path=path,
        project_id="s0e00",
        track_id="Test",
        preset="iuris-default",
        domain=VisualizationDomain.TIME,
        time_mode=TimeMode.SCROLL,
        style="mirrored",
        fps=60.0,
        capability=CapabilityLevel.LIMITED,
    )


def test_planned_destinations_include_short_signature(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    src.write_bytes(b"not-a-wav-but-hashed")
    preset = load_preset("iuris-default")
    sig, mov, png = planned_destinations(
        _job(src),
        preset,
        source_sha256=sha256_file(src),
        output_dir=tmp_path / "out",
        formats=["prores4444"],
    )
    assert mov is not None
    assert png is None
    assert sig
    assert sig[:12] in mov.name


def test_classify_action_skips_complete_mov(tmp_path: Path) -> None:
    dest = tmp_path / "out.mov"
    dest.write_bytes(b"not-empty")
    action, path, png = classify_action(mov_path=dest, png_path=None, force=False)
    assert action == "SKIP"
    assert path == dest
    assert png is None


def test_classify_action_force_versions(tmp_path: Path) -> None:
    dest = tmp_path / "out.mov"
    dest.write_bytes(b"not-empty")
    action, path, _png = classify_action(mov_path=dest, png_path=None, force=True)
    assert action == "PROCESS"
    assert path == tmp_path / "out_v002.mov"
