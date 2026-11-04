from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ewp_waveform.application.benchmark import _planned_job, load_and_expand, run_benchmark
from ewp_waveform.application.render import render_job
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_performance
from ewp_waveform.ffmpeg.probe import probe_media
from ewp_waveform.identity import sha256_file
from tests.integration.test_benchmark import TINY_PRESET
from tests.integration.test_render import TINY_SPECTRUM
from tests.render_oracles import (
    assert_decoded_prores_equal,
    assert_png_sequences_equal,
    assert_prores_contract,
    png_frames,
)


def _fixture(tmp_path: Path, mode: str, bounds: str) -> tuple[Path, Path]:
    source = tmp_path / "s0e00-Offset.wav"
    rate = 8000
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        # Silence then a sustained tone: an ignored offset cannot pass by matching duration.
        wav.writeframes(
            b"".join(
                struct.pack(
                    "<h", 0 if i < 3200 else round(15000 * math.sin(2 * math.pi * 800 * i / rate))
                )
                for i in range(rate)
            )
        )
    preset = tmp_path / "tiny.toml"
    preset.write_text(TINY_PRESET if mode == "scroll" else TINY_SPECTRUM, encoding="utf-8")
    manifest = tmp_path / "interval.toml"
    manifest.write_text(
        f'schema_version = 1\nname = "interval"\n[[inputs]]\npath = "{source}"\n{bounds}'
        f'[[variants]]\nname = "v"\npreset_file = "{preset}"\n'
        '[benchmark]\nrenderers = ["ffmpeg"]\nformats = ["png", "prores4444"]\n'
        'performance_profiles = ["balanced"]\ndry_run_estimates = true\n',
        encoding="utf-8",
    )
    return source, manifest


@pytest.mark.parametrize("mode", ["scroll", "fixed-axis"])
def test_actual_benchmark_cli_interval_matches_production_and_honors_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source, manifest = _fixture(tmp_path, mode, "start = 0.4\nduration = 0.35\n")
    before = (sha256_file(source), source.stat().st_mtime_ns)
    cache = tmp_path / "cache"
    monkeypatch.setenv("EWP_ANALYSIS_CACHE", str(cache))
    out = tmp_path / "benchmark"
    runner = CliRunner()
    dry = runner.invoke(app, ["benchmark", "dry-run", str(manifest), "--output-dir", str(out)])
    assert dry.exit_code == 0, dry.output
    assert "source_duration_seconds=1.0" in dry.output
    assert "requested_start_seconds=0.4" in dry.output
    assert "requested_duration_seconds=0.35" in dry.output
    assert "effective=[0.4,0.75)" in dry.output
    assert "effective_audio_seconds=0.35" in dry.output
    assert not out.exists()
    assert not cache.exists()
    result = runner.invoke(app, ["benchmark", "run", str(manifest), "--output-dir", str(out)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out / "interval_benchmark.json").read_text())
    record = summary["cells"][0]
    assert record["actual_status"] == "SUCCEEDED"
    assert record["throughput_available"] is True
    assert record["source_duration_seconds"] == 1.0
    assert record["requested_start_seconds"] == 0.4
    assert record["requested_duration_seconds"] == 0.35
    assert record["planned_clip_start_seconds"] == record["clip_start_seconds"] == 0.4
    assert record["planned_effective_audio_seconds"] == record["effective_audio_seconds"] == 0.35
    assert record["validated_output_frames"] == 4
    assert record["validated_output_frames_by_format"] == {"png": 4, "prores4444": 4}
    assert record["real_time_factor"] == pytest.approx(record["wall_seconds"] / 0.35)
    assert record["output_duration_seconds"] == pytest.approx(0.4)
    paths = {item["format"]: Path(item["path"]) for item in record["outputs"]}
    assert len(png_frames(paths["png"])) == 4
    assert_prores_contract(paths["prores4444"], width=80, height=32, fps=10, frame_count=4)
    _, planned = load_and_expand(manifest, output_dir=Path(summary["run_dir"]))
    assert planned[0].action == "SKIP"
    assert planned[0].png_path == paths["png"]
    assert planned[0].mov_path == paths["prores4444"]
    # Existing output at this exact ordinal/root is reusable only for the same interval.
    manifest.write_text(manifest.read_text().replace("start = 0.4", "start = 0.45"))
    _, changed = load_and_expand(manifest, output_dir=Path(summary["run_dir"]))
    assert changed[0].action == "PROCESS"
    assert changed[0].png_path != paths["png"]
    assert changed[0].mov_path != paths["prores4444"]
    cell = planned[0]
    performance = load_performance("balanced").model_copy(deep=True)
    performance.workdirs["root"] = str(tmp_path / "production-work")
    payload = render_job(
        _planned_job(source, cell.preset),
        probe_media(source),
        cell.preset,
        performance,
        output_dir=tmp_path / "production",
        formats=cell.formats,
        force=False,
        start=0.4,
        duration=0.35,
    )
    assert payload["job"]["status"] == "SUCCEEDED"
    reference = {item["format"]: Path(item["path"]) for item in payload["outputs"]}
    assert_png_sequences_equal(paths["png"], reference["png"])
    assert_decoded_prores_equal(paths["prores4444"], reference["prores4444"], width=80, height=32)
    assert record["job_id"] == payload["job"]["job_id"]
    # An equally short render from zero is silent; require an actual content difference.
    performance.workdirs["root"] = str(tmp_path / "zero-work")
    zero = render_job(
        _planned_job(source, cell.preset),
        probe_media(source),
        cell.preset,
        performance,
        output_dir=tmp_path / "zero",
        formats=["png"],
        force=False,
        start=0,
        duration=0.35,
    )
    assert zero["job"]["status"] == "SUCCEEDED"
    zero_frames = png_frames(Path(zero["outputs"][0]["path"]))
    assert any(
        a.read_bytes() != b.read_bytes()
        for a, b in zip(png_frames(paths["png"]), zero_frames, strict=True)
    )
    assert before == (sha256_file(source), source.stat().st_mtime_ns)


@pytest.mark.parametrize(
    "bounds,start,requested,effective,frames",
    [
        ("", 0, None, 1, 10),
        ("start = 0.8\nduration = 0.5\n", 0.8, 0.5, 0.2, 2),
        ("start = 0.75\n", 0.75, None, 0.25, 2),
        ("duration = 0.3\n", 0, 0.3, 0.3, 3),
    ],
)
def test_legacy_start_only_duration_only_and_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bounds: str,
    start: float,
    requested: float | None,
    effective: float,
    frames: int,
) -> None:
    _, manifest = _fixture(tmp_path, "scroll", bounds)
    monkeypatch.setenv("EWP_ANALYSIS_CACHE", str(tmp_path / "cache"))
    _, cells = load_and_expand(manifest, output_dir=tmp_path / "dry")
    assert cells[0].effective_start_seconds == start
    assert cells[0].effective_duration_seconds == pytest.approx(effective)
    assert not (tmp_path / "dry").exists()
    summary = run_benchmark(manifest, output_dir=tmp_path / "out")
    record = summary["cells"][0]
    assert record["actual_status"] == "SUCCEEDED"
    assert record["source_duration_seconds"] == 1
    assert record["requested_duration_seconds"] == requested
    assert record["clip_start_seconds"] == start
    assert record["effective_audio_seconds"] == pytest.approx(effective)
    assert record["validated_output_frames"] == frames
    assert record["real_time_factor"] == pytest.approx(record["wall_seconds"] / effective)
    paths = {x["format"]: Path(x["path"]) for x in record["outputs"]}
    _, planned = load_and_expand(manifest, output_dir=Path(summary["run_dir"]))
    assert planned[0].png_path == paths["png"]
    assert planned[0].mov_path == paths["prores4444"]
    assert_prores_contract(paths["prores4444"], width=80, height=32, fps=10, frame_count=frames)


@pytest.mark.parametrize(
    "bounds",
    [
        "start = -1\n",
        "duration = 0\n",
        "duration = -1\n",
        "start = nan\n",
        "start = inf\n",
        "duration = inf\n",
        "duration = nan\n",
        "start = 1.0\n",
        "start = 1.1\n",
        "start = true\n",
        'duration = "8"\n',
        "duraton = 8\n",
    ],
)
@pytest.mark.parametrize("command", ["dry-run", "run"])
def test_invalid_intervals_refuse_before_any_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bounds: str, command: str
) -> None:
    source, manifest = _fixture(tmp_path, "scroll", bounds)
    cache = tmp_path / "cache"
    monkeypatch.setenv("EWP_ANALYSIS_CACHE", str(cache))
    # Mix a valid first input with an invalid later one: no partial execution/allocation.
    text = manifest.read_text()
    manifest.write_text(text.replace("[[inputs]]", f'[[inputs]]\npath = "{source}"\n[[inputs]]', 1))
    out = tmp_path / "out"
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    result = CliRunner().invoke(
        app, ["benchmark", command, str(manifest), "--output-dir", str(out)]
    )
    assert result.exit_code == 2, result.output
    assert not out.exists()
    assert not cache.exists()
    assert before == sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
