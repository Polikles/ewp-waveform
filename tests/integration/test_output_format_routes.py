from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ewp_waveform.application.service import render
from ewp_waveform.cli import app
from ewp_waveform.identity import sha256_file
from tests.integration.test_render import NO_CHUNKS, TINY_PRESET, _tone_wav, _write


@pytest.mark.parametrize("formats", [["jpeg"], ["png", "jpeg"]])
def test_real_cli_rejects_invalid_format_without_artifacts(
    tmp_path: Path, formats: list[str]
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src, seconds=0.4)
    before = sha256_file(src)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    config = _write(tmp_path / "config.toml", f"[output]\nformats = {json.dumps(formats)}")
    out = tmp_path / "out"
    for command in ("dry-run", "preview", "render"):
        result = CliRunner().invoke(
            app,
            [
                command,
                str(src),
                "--preset",
                str(preset),
                "--config",
                str(config),
                "--output-dir",
                str(out),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "E_CONFIG_INVALID" in result.output
        assert not out.exists()
    assert sha256_file(src) == before
    assert not list(tmp_path.rglob("*results.json"))


def test_repeated_multiple_formats_render_once_per_supported_output(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src, seconds=0.4)
    before = sha256_file(src)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    performance = _write(tmp_path / "performance.toml", NO_CHUNKS)
    payload = render(
        src,
        preset_name=str(preset),
        performance_name=str(performance),
        output_dir=tmp_path / "out",
        formats=["png", "prores4444", "png"],
        force=False,
    )[0]
    job = payload["job"]
    assert isinstance(job, dict)
    assert job["status"] == "SUCCEEDED"
    outputs = payload["outputs"]
    assert isinstance(outputs, list)
    assert sorted(item["format"] for item in outputs) == ["png", "prores4444"]
    assert all(Path(item["path"]).exists() for item in outputs)
    assert sha256_file(src) == before
