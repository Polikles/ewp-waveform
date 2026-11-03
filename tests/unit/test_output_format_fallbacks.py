import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ewp_waveform.application import benchmark, service
from ewp_waveform.application.service import AppError
from ewp_waveform.cli import app
from ewp_waveform.config.models import BenchmarkManifest
from ewp_waveform.domain.models import SourceMedia


@pytest.mark.parametrize("formats", [None, []])
@pytest.mark.parametrize("empty_config", [False, True])
def test_builtin_and_empty_config_keep_prores_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    formats: list[str] | None,
    empty_config: bool,
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    src.write_bytes(b"input")
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
    config = None
    if empty_config:
        config = tmp_path / "empty.toml"
        config.write_text("[output]\nformats = []\n")
    _, _, _, plans, _ = service.plan_jobs(
        src,
        config_path=config,
        formats=formats,
        output_dir=tmp_path / "out",
    )
    assert len(plans) == 1
    assert plans[0].mov_path is not None
    assert plans[0].png_path is None


@pytest.mark.parametrize("entry", ["dry_run", "plan_jobs", "render"])
def test_empty_override_still_validates_config_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    config = tmp_path / "invalid.toml"
    config.write_text('[output]\nformats = ["jpeg"]\n')
    probe = Mock(side_effect=AssertionError("invalid fallback probed source"))
    monkeypatch.setattr(service, "probe_media", probe)
    with pytest.raises(AppError, match="Unsupported output format") as caught:
        getattr(service, entry)(tmp_path / "missing.wav", config_path=config, formats=[])
    assert caught.value.numeric_exit == 2
    probe.assert_not_called()
    assert not (tmp_path / "waveform-output").exists()


@pytest.mark.parametrize("formats", [["jpeg"], ["png", "jpeg"]])
@pytest.mark.parametrize("renderer", ["ffmpeg", "unavailable"])
def test_benchmark_format_validation_precedes_media_or_blocked_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    formats: list[str],
    renderer: str,
) -> None:
    probe = Mock(side_effect=AssertionError("invalid benchmark probed source"))
    digest = Mock(side_effect=AssertionError("invalid benchmark hashed source"))
    monkeypatch.setattr(benchmark, "probe_media", probe)
    monkeypatch.setattr(benchmark, "sha256_file", digest)
    manifest = BenchmarkManifest.model_validate(
        {
            "schema_version": 1,
            "name": "invalid-formats",
            "inputs": [{"path": str(tmp_path / "missing.wav")}],
            "variants": [{"name": "default", "preset": "iuris-default"}],
            "benchmark": {"renderers": [renderer], "formats": formats},
        }
    )
    out = tmp_path / "out"
    with pytest.raises(AppError, match="Unsupported output format"):
        benchmark.expand_benchmark(manifest, manifest_dir=tmp_path, output_dir=out)
    manifest_path = tmp_path / "benchmark.toml"

    manifest_path.write_text(
        'schema_version = 1\nname = "invalid-formats"\n'
        '[[inputs]]\npath = "missing.wav"\n'
        '[[variants]]\nname = "default"\npreset = "iuris-default"\n'
        f"[benchmark]\nrenderers = {json.dumps([renderer])}\nformats = {json.dumps(formats)}\n"
    )
    for command in ("dry-run", "run"):
        result = CliRunner().invoke(
            app,
            [
                "benchmark",
                command,
                str(manifest_path),
                "--output-dir",
                str(out),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "E_CONFIG_INVALID" in result.output
    assert not out.exists()
    probe.assert_not_called()
    digest.assert_not_called()
