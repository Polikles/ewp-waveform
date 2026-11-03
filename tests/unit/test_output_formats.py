from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ewp_waveform.application import service
from ewp_waveform.application.render import planned_destinations, render_job
from ewp_waveform.application.service import AppError
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.diagnostics import DiagnosticCode, ExitCode
from ewp_waveform.domain.models import SourceMedia
from tests.unit.test_plan import _job

render_module = importlib.import_module("ewp_waveform.application.render")
INVALID = [["jpeg"], ["png", "jpeg"], ["jpeg", "prores4444"], ["png", "jpeg", "gif"]]


@pytest.fixture
def no_media_work(monkeypatch: pytest.MonkeyPatch) -> list[Mock]:
    guards = []
    for module, names in (
        (service, ["probe_media", "sha256_file", "_output_space_warning"]),
        (
            render_module,
            ["sha256_file", "decode_mono_wav", "encode_rgba_stream", "resolve_workdir"],
        ),
    ):
        for name in names:
            guard = Mock(side_effect=AssertionError(f"invalid format reached {name}"))
            monkeypatch.setattr(module, name, guard)
            guards.append(guard)
    return guards


def assert_config_error(exc: AppError, formats: list[str]) -> None:
    assert exc.exit_code == ExitCode.CONFIG
    assert exc.numeric_exit == 2
    assert exc.diagnostic is not None
    assert exc.diagnostic.code == DiagnosticCode.E_CONFIG_INVALID
    for token in formats:
        if token not in ("png", "prores4444"):
            assert token in str(exc)


@pytest.mark.parametrize("formats", INVALID)
@pytest.mark.parametrize("entry", ["plan_jobs", "render", "dry_run"])
@pytest.mark.parametrize("from_config", [False, True])
def test_effective_formats_rejected_before_media_work(
    tmp_path: Path, no_media_work: list[Mock], formats: list[str], entry: str, from_config: bool
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    src.write_bytes(b"must not be probed or hashed")
    out = tmp_path / "out"
    config = tmp_path / "config.toml"
    config.write_text(f"[output]\nformats = {json.dumps(formats)}\n")
    call = getattr(service, entry)
    kwargs: dict[str, object] = {"config_path": config} if from_config else {"formats": formats}
    if entry != "dry_run":
        kwargs["output_dir"] = out
    with pytest.raises(AppError) as caught:
        call(src, **kwargs)
    assert_config_error(caught.value, formats)
    assert not out.exists()
    assert not (tmp_path / "waveform-output").exists()
    assert not list(tmp_path.rglob("*results.json"))
    for guard in no_media_work:
        guard.assert_not_called()


@pytest.mark.parametrize("formats", INVALID)
@pytest.mark.parametrize("command", ["dry-run", "preview", "render"])
@pytest.mark.parametrize("from_config", [False, True])
def test_cli_invalid_formats_exit_two_without_success(
    tmp_path: Path, no_media_work: list[Mock], formats: list[str], command: str, from_config: bool
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    src.write_bytes(b"must not be probed or hashed")
    out = tmp_path / "out"
    args = [command, str(src), "--output-dir", str(out)]
    if from_config:
        config = tmp_path / "config.toml"
        config.write_text(f"[output]\nformats = {json.dumps(formats)}\n")
        args += ["--config", str(config)]
    else:
        for token in formats:
            args += ["--format", token]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert "E_CONFIG_INVALID" in result.output
    assert "Unsupported output format" in result.output
    assert "Traceback" not in result.output
    assert "SUCCEEDED" not in result.output
    assert "SKIP" not in result.output
    assert not out.exists()
    assert not list(tmp_path.rglob("*results.json"))
    for guard in no_media_work:
        guard.assert_not_called()


@pytest.mark.parametrize("formats", INVALID)
def test_direct_render_job_rejects_before_hashing(
    tmp_path: Path, no_media_work: list[Mock], formats: list[str]
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    media = SourceMedia(
        path=src,
        duration_seconds=0.4,
        sample_rate=8000,
        channels=1,
        codec="pcm_s16le",
        format_name="wav",
        size_bytes=0,
    )
    out = tmp_path / "out"
    with pytest.raises(AppError) as caught:
        render_job(
            _job(src),
            media,
            load_preset("iuris-default"),
            load_performance("balanced"),
            output_dir=out,
            formats=formats,
            force=False,
        )
    assert_config_error(caught.value, formats)
    assert not out.exists()
    for guard in no_media_work:
        guard.assert_not_called()


@pytest.mark.parametrize("formats", INVALID)
def test_direct_destinations_reject_invalid_formats(tmp_path: Path, formats: list[str]) -> None:
    out = tmp_path / "out"
    with pytest.raises(AppError) as caught:
        planned_destinations(
            _job(tmp_path / "s0e00-Test.wav"),
            load_preset("iuris-default"),
            source_sha256="a" * 64,
            output_dir=out,
            formats=formats,
        )
    assert_config_error(caught.value, formats)
    assert not out.exists()


@pytest.mark.parametrize(
    "formats", [[], ["prores4444"], ["png"], ["png", "png"], ["png", "prores4444", "png"]]
)
def test_valid_selection_preserves_destinations_and_identity(
    tmp_path: Path, formats: list[str]
) -> None:
    job = _job(tmp_path / "s0e00-Test.wav")
    preset = load_preset("iuris-default")
    sig, mov, png = planned_destinations(
        job, preset, formats=formats, source_sha256="a" * 64, output_dir=tmp_path / "out"
    )
    default_sig, _, _ = planned_destinations(
        job, preset, formats=[], source_sha256="a" * 64, output_dir=tmp_path / "out"
    )
    assert sig == default_sig
    assert (mov is not None) == (not formats or "prores4444" in formats)
    assert (png is not None) == ("png" in formats)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("formats", [None, [], ["png"], ["png", "prores4444", "png"]])
def test_effective_defaults_empty_and_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formats: list[str] | None
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    src.write_bytes(b"input")
    config = tmp_path / "config.toml"
    config.write_text('[output]\nformats = ["png"]\n')
    media = SourceMedia(
        path=src,
        duration_seconds=0.4,
        sample_rate=8000,
        channels=1,
        codec="pcm_s16le",
        format_name="wav",
        size_bytes=5,
    )
    monkeypatch.setattr(service, "probe_media", lambda path: media)
    _, _, _, plans, _ = service.plan_jobs(
        src,
        config_path=config,
        output_dir=tmp_path / "out",
        formats=formats,
    )
    assert len(plans) == 1
    assert plans[0].png_path is not None
    assert (plans[0].mov_path is not None) == bool(formats and "prores4444" in formats)
    # A nonempty explicit selection overrides even an unsupported config list.
    config.write_text('[output]\nformats = ["jpeg"]\n')
    _, _, jobs, _ = service.dry_run(src, config_path=config, formats=["png"])
    assert len(jobs) == 1
