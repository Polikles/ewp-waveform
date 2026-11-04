from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import benchmark
from ewp_waveform.application.benchmark import _planned_job, run_benchmark
from ewp_waveform.application.evidence import render_measurements
from ewp_waveform.application.render import render_job
from ewp_waveform.application.service import benchmark_dry_run
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.ffmpeg.probe import probe_media
from tests.render_oracles import assert_png_sequences_equal


def _tone_wav(path: Path, seconds: float = 0.4, rate: int = 8000) -> None:
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            amp = 12000 if i > n // 2 else 0
            frames.extend(struct.pack("<h", amp))
        wav.writeframes(bytes(frames))


TINY_PRESET = """
schema_version = 1
name = "tiny-bench-preset"

[canvas]
width = 80
height = 32
fps = 10

[waveform]
style = "mirrored"
domain = "time"
time_mode = "scroll"
window_seconds = 0.2
color = "#C7E6EC"
amplitude = 1.0
stroke_width = 2.0
center_line = false

[signal]
scale = "sqrt"
smoothing = 0.0
envelope_oversample = 1
envelope_aa = "none"
envelope_motion_lpf = "none"
shutter_degrees = 0

[signal.normalization]
mode = "auto"
soft_clip = true

[effects.glow]
enabled = false
level = "none"
"""


def test_benchmark_run_tiny_cell(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Bench.wav"
    _tone_wav(src)
    preset = tmp_path / "tiny.toml"
    preset.write_text(TINY_PRESET.strip() + "\n", encoding="utf-8")
    manifest = tmp_path / "bench.toml"
    manifest.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'name = "tiny-bench"',
                "[[inputs]]",
                f'path = "{src}"',
                "[[variants]]",
                'name = "canonical"',
                f'preset_file = "{preset}"',
                "[benchmark]",
                'renderers = ["ffmpeg"]',
                'formats = ["png"]',
                'performance_profiles = ["balanced"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "bench-out"
    _man, cells = benchmark_dry_run(manifest, output_dir=out)
    assert len(cells) == 1
    assert cells[0].action == "PROCESS"
    summary = run_benchmark(manifest, output_dir=out, force=True)
    assert summary["counts"]["succeeded"] == 1
    result = Path(str(summary["result_json"]))
    assert result.is_file()
    cell = summary["cells"][0]
    assert isinstance(cell, dict)
    assert cell["status"] == "SUCCEEDED"
    assert float(cell["wall_seconds"]) >= 0.0
    assert int(cell["output_bytes"]) > 0


def test_benchmark_profiles_and_repeated_runs_are_fresh(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Isolation.wav"
    _tone_wav(src)
    preset = tmp_path / "tiny.toml"
    preset.write_text(TINY_PRESET.strip() + "\n", encoding="utf-8")
    manifest = tmp_path / "matrix.toml"
    manifest.write_text(
        f'schema_version = 1\nname = "matrix"\n[[inputs]]\npath = "{src}"\n'
        f'[[variants]]\nname = "v"\npreset_file = "{preset}"\n'
        '[benchmark]\nrenderers = ["ffmpeg"]\nformats = ["png"]\n'
        'performance_profiles = ["balanced", "maximum"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    first = run_benchmark(manifest, output_dir=out)
    second = run_benchmark(manifest, output_dir=out)
    cells = first["cells"] + second["cells"]
    assert len({cell["output_dir"] for cell in cells}) == 4
    assert len({cell["work_root"] for cell in cells}) == 4
    assert all(cell["actual_status"] == "SUCCEEDED" for cell in cells)
    assert all(cell["throughput_available"] is True for cell in cells)
    assert all(cell["analysis_cache_observed"] is None for cell in cells)
    assert first["run_dir"] != second["run_dir"]
    reference = Path(cells[0]["outputs"][0]["path"])
    for cell in cells[1:]:
        assert cell["job_id"] == cells[0]["job_id"]
        assert_png_sequences_equal(reference, Path(cell["outputs"][0]["path"]))


def test_clipped_render_measurements_use_render_bounds(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Clip.wav"
    _tone_wav(src, seconds=1.0)
    path = tmp_path / "tiny.toml"
    path.write_text(TINY_PRESET.strip() + "\n", encoding="utf-8")
    preset = load_preset(str(path))
    performance = load_performance("balanced").model_copy(deep=True)
    performance.workdirs["root"] = str(tmp_path / "work")
    payload = render_job(
        _planned_job(src, preset),
        probe_media(src),
        preset,
        performance,
        output_dir=tmp_path / "out",
        formats=["png"],
        force=False,
        start=0.1,
        duration=0.25,
    )
    report = render_measurements(payload, planned_action="PROCESS", wall_seconds=2.0, fps=10)
    assert payload["inputs"][0]["duration_seconds"] == 1.0
    assert report["effective_audio_seconds"] == 0.25
    assert report["validated_output_frames"] == round(0.25 * 10)
    assert report["real_time_factor"] == 2.0 / 0.25
    assert report["render_fps"] == round(0.25 * 10) / 2.0


def test_runtime_skip_after_planning_never_reports_throughput(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "s0e00-Reuse.wav"
    _tone_wav(src)
    preset = tmp_path / "tiny.toml"
    preset.write_text(TINY_PRESET.strip() + "\n", encoding="utf-8")
    manifest = tmp_path / "reuse.toml"
    manifest.write_text(
        f'schema_version = 1\nname = "reuse"\n[[inputs]]\npath = "{src}"\n'
        f'[[variants]]\nname = "v"\npreset_file = "{preset}"\n'
        '[benchmark]\nrenderers = ["ffmpeg"]\nformats = ["png"]\n',
        encoding="utf-8",
    )

    def populate_then_render(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Simulate output appearing between the runner's plan and runtime reuse gate.
        first = render_job(*args, **kwargs)
        assert first["job"]["status"] == "SUCCEEDED"
        return render_job(*args, **kwargs)

    monkeypatch.setattr(benchmark, "render_job", populate_then_render)
    summary = run_benchmark(manifest, output_dir=tmp_path / "out")
    cell = summary["cells"][0]
    assert cell["planned_action"] == "PROCESS"
    assert cell["actual_status"] == "SKIPPED"
    assert cell["actual_action"] == "REUSE"
    assert summary["counts"]["throughput_samples"] == 0
    assert cell["render_fps"] is None
    assert cell["real_time_factor"] is None


def test_analysis_cache_cold_warm_is_independent_of_output_work_namespaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.integration.test_render import TINY_SPECTRUM

    src = tmp_path / "s0e00-Cache.wav"
    _tone_wav(src)
    path = tmp_path / "tiny-spectrum.toml"
    path.write_text(TINY_SPECTRUM.strip() + "\n", encoding="utf-8")
    preset = load_preset(str(path))
    outputs: list[Path] = []
    states: list[str] = []
    for index, cache in enumerate(["cache-a", "cache-a", "cache-b"]):
        monkeypatch.setenv("EWP_ANALYSIS_CACHE", str(tmp_path / cache))
        performance = load_performance("balanced").model_copy(deep=True)
        performance.workdirs["root"] = str(tmp_path / f"work-{index}")
        payload = render_job(
            _planned_job(src, preset),
            probe_media(src),
            preset,
            performance,
            output_dir=tmp_path / f"output-{index}",
            formats=["png"],
            force=False,
            spectrum_layout="field_center_out",
        )
        assert payload["job"]["status"] == "SUCCEEDED"
        states.append(payload["performance"]["extras"]["analysis_cache"])
        outputs.append(Path(payload["outputs"][0]["path"]))
        report = render_measurements(payload, planned_action="PROCESS", wall_seconds=1.0, fps=10)
        assert report["throughput_available"] is True
        assert report["raw_feed_pixel_format"] in {"rgba", "gray"}
        assert report["raw_feed_bytes"] > 0
    assert states == ["miss", "hit", "miss"]
    for output in outputs[1:]:
        assert_png_sequences_equal(outputs[0], output)
