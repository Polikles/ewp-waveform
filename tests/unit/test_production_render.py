from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application import production_render as production
from ewp_waveform.application.portable_experiments_state import identity
from ewp_waveform.config.load import load_application_config, load_performance, load_preset


def test_committed_production_look_and_serial_lut_are_explicit() -> None:
    visual = load_preset(str(production.PRESET))
    assert visual.canvas.model_dump() == {"width": 1400, "height": 280, "fps": 60}
    assert visual.waveform.model_dump() == {
        "style": "filled",
        "color": "#C7E6EC",
        "amplitude": 0.82,
        "stroke_width": 1.0,
        "center_line": True,
        "reflection_opacity": 0.45,
        "center_line_extent": 0.96,
        "center_line_opacity": 0.55,
        "background_mode": "dark-background",
        "color_mode": "custom",
        "domain": "frequency",
        "time_mode": None,
        "window_seconds": 5.0,
    }
    assert visual.signal == {
        "fixed_axis_profile": "filled-ribbon-v2",
        "detail_level": "balanced",
        "scale": "sqrt",
        "smoothing": 0.06,
        "visual_noise": 0.35,
        "idle_activity": 0.0,
        "noise_rate": 0.8,
        "noise_seed": 1729,
        "normalization": {"mode": "auto", "soft_clip": True},
        "frequency": {"range": "auto"},
    }
    assert visual.effects["glow"] == {"enabled": True, "level": "high", "color": "#C7E6EC"}
    perf = load_performance(str(production.PERFORMANCE))
    assert perf.processing == {
        "jobs": 1,
        "chunk_seconds": 60,
        "ffmpeg_threads": 0,
        "ribbon_finish_lut": True,
    }
    cfg = load_application_config(production.CONFIG)
    assert cfg.defaults.preset == visual.name
    assert cfg.defaults.performance == perf.name
    assert cfg.output.formats == ["prores4444"]
    # The existing stock preset/defaults have not acquired this artistic noise.
    assert load_preset("iuris-ribbon-refined").signal["visual_noise"] == 0.0


def test_ordinary_full_cli_argv_and_private_performance(tmp_path: Path) -> None:
    media = tmp_path / "root with spaces"
    text = production.performance_text(media)
    actual = tomllib.loads(text)
    committed = tomllib.loads(production.PERFORMANCE.read_text())
    assert actual.pop("workdirs") == {**committed.pop("workdirs"), "root": str(media / "work")}
    assert actual == committed
    argv = production.cli_command(
        Path("python.exe"), Path("track with spaces.wav"), media, media / "performance.toml"
    )
    assert argv[:5] == ["python.exe", "-m", "ewp_waveform", "render", "track with spaces.wav"]
    assert argv[argv.index("--preset") + 1] == str(production.PRESET)
    assert argv[argv.index("--format") + 1] == "prores4444"
    assert not {"--full", "--force", "--start", "--duration", "--cuda"}.intersection(argv)


@pytest.mark.parametrize(
    "option,value",
    [
        ("--reserve-gib", "nan"),
        ("--max-growth-gib", "0"),
        ("--timeout-seconds", "inf"),
    ],
)
def test_invalid_policy_is_readonly(tmp_path: Path, option: str, value: str) -> None:
    output = tmp_path / "unused"
    assert (
        production.main(
            ["--audio", str(tmp_path / "missing.wav"), "--output-root", str(output), option, value]
        )
        == 2
    )
    assert not output.exists()


def test_collision_refuses_without_modification(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"unit fixture; no media tool admitted")
    output = tmp_path / "held"
    output.mkdir()
    marker = output / "held.txt"
    marker.write_text("preserve")
    before = marker.stat().st_mtime_ns
    assert production.main(["--audio", str(source), "--output-root", str(output)]) == 2
    assert sorted(p.name for p in output.iterdir()) == ["held.txt"]
    assert marker.read_text() == "preserve" and marker.stat().st_mtime_ns == before


def test_missing_preparation_never_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"unit fixture; no media tool admitted")
    monkeypatch.setattr(production, "ROOT", tmp_path / "absent-project")
    monkeypatch.setattr(production, "check_budget", lambda *args: {})
    monkeypatch.setattr(production, "prepared_environment", lambda *args: None)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("missing preparation must not launch an installer or worker")

    monkeypatch.setattr(production, "run_command", forbidden)
    output = tmp_path / "new"
    assert production.main(["--audio", str(source), "--output-root", str(output)]) == 2
    assert "no install attempted" in json.loads((output / "logs/failure.json").read_text())["error"]
    assert not (output / "output").exists()


def test_windows_retained_tools_use_existing_lock_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ewp_waveform.ffmpeg import portable_tools

    monkeypatch.setattr(production, "os", SimpleNamespace(name="nt"))
    lock = portable_tools.read_lock()
    base = tmp_path / "tools"
    directory = base / lock["archive_root"]
    binaries = directory / "bin"
    binaries.mkdir(parents=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (binaries / name).write_bytes(b"identity-predicate fixture, not Windows execution")
    observed: list[Path] = []

    def prepared(preparations: Path, managed: Path, problems: list[dict[str, Any]]) -> Path:
        observed.append(managed)
        return base

    def verified(path: Path) -> dict[str, str]:
        assert path == directory
        return {name: str(binaries / (name + ".exe")) for name in ("ffmpeg", "ffprobe")}

    monkeypatch.setattr(production, "prepared_ffmpeg_root", prepared)
    monkeypatch.setattr(portable_tools, "verify_install", verified)
    selected = production.select_tools(None, None, tmp_path, tmp_path / "managed")
    assert selected == (binaries / "ffmpeg.exe", binaries / "ffprobe.exe")
    lock_path = production.ROOT / "src/ewp_waveform/ffmpeg/portable_ffmpeg_lock.json"
    assert observed == [tmp_path / "managed/ffmpeg" / identity(lock_path)["sha256"]]


def test_unpaired_tools_refuse_before_launch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="both --ffmpeg and --ffprobe"):
        production.select_tools(tmp_path / "ffmpeg", None, tmp_path, tmp_path)
