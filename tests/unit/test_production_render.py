from __future__ import annotations

import json
import sys
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
    assert actual.pop("workdirs") == {
        **committed.pop("workdirs"),
        "root": (media / "work").as_posix(),
    }
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


@pytest.mark.parametrize(
    "returncode,error,stdout,stderr,expected",
    [
        (3, None, "E_INPUT_UNSUPPORTED: primary missing", "", "primary missing"),
        (5, None, "", "encoder failed", "encoder failed"),
        (0, "timeout after 1s", "progress", "", "timeout after 1s"),
        (None, "launch failed", "", "", "launch failed"),
        (2, None, "", "", "no command diagnostics"),
    ],
)
def test_failed_command_reports_exit_and_useful_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    returncode: int | None,
    error: str | None,
    stdout: str,
    stderr: str,
    expected: str,
) -> None:
    # Simulated supervisor results; no interpreter/tool acquisition or render.
    source = tmp_path / "another mono.wav"
    source.write_bytes(b"failure diagnostic fixture; not decoded")
    output = tmp_path / "new"
    monkeypatch.setattr(production, "check_budget", lambda *args: {})
    monkeypatch.setattr(
        production,
        "run_command",
        lambda *args, **kwargs: {
            "returncode": returncode,
            "error": error,
            "stdout": stdout,
            "stderr": stderr,
            "shutdown_verified": True,
        },
    )
    assert (
        production.main(
            ["--audio", str(source), "--python", sys.executable, "--output-root", str(output)]
        )
        == 2
    )
    failure = json.loads((output / "logs/failure.json").read_text())["error"]
    assert f"returncode={returncode}" in failure
    assert expected in failure
    assert "see " in failure and "runtime" in failure
    assert failure in capsys.readouterr().err


@pytest.mark.parametrize(
    "platform,audio,expected,output",
    [
        (
            "nt",
            r"D:\test-waveform\s0e00\s0e00-Damian.wav",
            r"D:\test-waveform\s0e00\s0e00-Damian.wav",
            r"E:\render output\fresh",
        ),
        (
            "nt",
            "D:/test-waveform/s0e00/s0e00-Damian.wav",
            "D:/test-waveform/s0e00/s0e00-Damian.wav",
            "E:/render output/fresh",
        ),
        (
            "nt",
            r"E:\other episode\s9e17-Other mono.wav",
            r"E:\other episode\s9e17-Other mono.wav",
            r"F:\other output\fresh",
        ),
        (
            "posix",
            r"E:\other episode\s9e17-Other mono.wav",
            "/mnt/e/other episode/s9e17-Other mono.wav",
            "/mnt/f/render output/fresh",
        ),
        (
            "posix",
            "/mnt/d/other episode/s9e17-Other mono.wav",
            "/mnt/d/other episode/s9e17-Other mono.wav",
            "/mnt/f/render output/fresh",
        ),
    ],
)
def test_launcher_argv_through_typer_and_resolved_service_platform_simulation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    audio: str,
    expected: str,
    output: str,
) -> None:
    from typer.testing import CliRunner

    from ewp_waveform import cli, paths
    from ewp_waveform.application import service
    from ewp_waveform.config.models import PerformanceProfile, VisualPreset
    from ewp_waveform.domain.models import PlannedJob, SourceMedia

    # Only the path-policy branch is simulated. Native host config loading and
    # Typer/service resolution remain real; foreign filesystem/media I/O does not.
    monkeypatch.setattr(paths, "os", SimpleNamespace(name=platform))
    discovered: list[Path] = []
    selected: list[str] = []
    host_source = tmp_path / "s9e17-Other mono.wav"

    def discover(input_path: Path, **kwargs: Any) -> list[Path]:
        discovered.append(input_path)
        assert input_path == Path(expected)
        assert kwargs == {"recursive": False, "follow_symlinks": False}
        return [host_source]

    def probe(path: Path) -> SourceMedia:
        assert path == host_source
        return SourceMedia(
            path=path,
            duration_seconds=0.1,
            sample_rate=48000,
            channels=1,
            codec="pcm_s16le",
            format_name="wav",
            size_bytes=9644,
        )

    class ReachedRenderer(RuntimeError):
        pass

    def render_job(
        job: PlannedJob,
        media: SourceMedia,
        preset: VisualPreset,
        performance: PerformanceProfile,
        **kwargs: Any,
    ) -> Any:
        assert job.path == host_source and media.channels == 1
        assert preset.model_dump() == load_preset(str(production.PRESET)).model_dump()
        assert performance.model_dump() == load_performance(str(performance_path)).model_dump()
        assert preset.signal["visual_noise"] == 0.35 and preset.signal["noise_seed"] == 1729
        assert preset.waveform.color_mode == "custom"
        assert preset.waveform.reflection_opacity == 0.45
        assert performance.processing["jobs"] == 1
        assert performance.processing["ribbon_finish_lut"] is True
        assert kwargs["formats"] == ["prores4444"]
        assert kwargs["output_dir"] == Path(output) / "output"
        assert kwargs["force"] is False
        assert kwargs["start"] is None and kwargs["duration"] is None
        selected.append(preset.name)
        # Stop before renderer/publication: do not synthesize a successful render.
        raise ReachedRenderer

    monkeypatch.setattr(service, "discover_paths", discover)
    monkeypatch.setattr(service, "probe_media", probe)
    monkeypatch.setattr(service, "render_job", render_job)
    performance_path = tmp_path / "performance.toml"
    performance_path.write_text(production.performance_text(tmp_path), encoding="utf-8")
    argv = production.cli_command(Path(sys.executable), Path(audio), Path(output), performance_path)
    observed = CliRunner().invoke(cli.app, argv[3:])
    assert isinstance(observed.exception, ReachedRenderer), observed.output or repr(
        observed.exception
    )
    assert discovered == [Path(expected)]
    assert selected == ["iuris-ribbon-refined-production"]
