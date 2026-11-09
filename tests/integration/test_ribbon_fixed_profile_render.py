from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application import render as render_module
from ewp_waveform.application.results import result_payload_errors
from ewp_waveform.application.service import plan_jobs, render
from ewp_waveform.ffmpeg.process import require_tool
from ewp_waveform.identity import sha256_file
from ewp_waveform.paths import builtin_presets_dir
from tests.integration.test_render import NO_CHUNKS, _job_status, _write
from tests.render_oracles import (
    assert_decoded_prores_equal,
    assert_png_sequences_equal,
    assert_prores_contract,
    decoded_prores_frames,
    png_frames,
)


def _source(path: Path, *, silent: bool = False) -> None:
    rate = 8000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        data = bytearray()
        for i in range(6400):
            t = i / rate
            active = not silent and 0.2 <= t < 0.65
            value = int(10000 * math.sin(2 * math.pi * 440 * t)) if active else 0
            data.extend(struct.pack("<h", value))
        wav.writeframes(data)


def _preset(tmp_path: Path) -> Path:
    text = (builtin_presets_dir() / "iuris-ribbon-fixed.toml").read_text()
    text = text.replace("width = 1400", "width = 96")
    text = text.replace("height = 280", "height = 160").replace("fps = 60", "fps = 10")
    return _write(tmp_path / "ribbon.toml", text)


def _output(payload: dict[str, object], kind: str) -> Path:
    outputs = payload["outputs"]
    assert isinstance(outputs, list)
    paths = [Path(str(item["path"])) for item in outputs if isinstance(item, dict)]
    return next(path for path in paths if (path.suffix == ".mov") == (kind == "mov"))


def _signature(payload: dict[str, object]) -> str:
    job = payload["job"]
    assert isinstance(job, dict)
    return str(job["render_signature"])


def _recipe(payload: dict[str, object]) -> dict[str, Any]:
    config = payload["resolved_visual_config"]
    assert isinstance(config, dict)
    recipe = config["fixed_axis_recipe"]
    assert isinstance(recipe, dict)
    return recipe


def _png_rgba(directory: Path) -> bytes:
    return subprocess.run(
        [
            str(require_tool("ffmpeg")),
            "-v",
            "error",
            "-i",
            str(directory / "frame_%06d.png"),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout


def test_ribbon_profile_planning_render_skip_alpha_and_source_immutability(tmp_path: Path) -> None:
    source = tmp_path / "s0e00-Ribbon.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    preset = _preset(tmp_path)
    performance = _write(tmp_path / "single.toml", NO_CHUNKS)
    common: dict[str, Any] = {
        "preset_name": str(preset),
        "performance_name": str(performance),
        "output_dir": tmp_path / "out",
        "formats": ["png", "prores4444"],
        "start": 0.1,
        "duration": 0.6,
    }
    _, _, _, plans, _ = plan_jobs(source, **common)
    assert not (tmp_path / "out").exists()
    _, _, _, shifted_plans, _ = plan_jobs(source, **{**common, "start": 0.2})
    assert shifted_plans[0].render_signature != plans[0].render_signature
    payload = render(source, **common)[0]
    assert _job_status(payload) == "SUCCEEDED"
    assert plans[0].render_signature == _signature(payload)
    assert _recipe(payload)["profile"] == "filled-ribbon-v1"
    assert _recipe(payload)["field_geometry"] == "ribbon"
    frames = png_frames(_output(payload, "png"))
    assert len(frames) == 6
    rgba = np.frombuffer(_png_rgba(_output(payload, "png")), dtype=np.uint8).reshape(6, 160, 96, 4)
    alpha = rgba[:, :, :, 3]
    assert np.any(alpha == 0), "alpha-capable metadata alone is insufficient"
    assert np.any(alpha > 0)
    assert np.any((alpha > 0) & (alpha < 255)), "soft contour/glow coverage is missing"
    assert np.max(np.count_nonzero(alpha > 32, axis=(1, 2))) > np.min(
        np.count_nonzero(alpha > 32, axis=(1, 2))
    ), "activity did not animate vertically"
    mov = _output(payload, "mov")
    assert_prores_contract(mov, width=96, height=160, fps=10, frame_count=6)
    mov_alpha = b"".join(frame[3::4] for frame in decoded_prores_frames(mov, width=96, height=160))
    assert min(mov_alpha) == 0 and max(mov_alpha) > 0
    repeated = render(source, **common)[0]
    assert _job_status(repeated) == "SKIPPED"
    assert _recipe(repeated) == _recipe(payload)
    assert _signature(repeated) == _signature(payload)
    for result in (payload, repeated):
        assert result_payload_errors(result) == []
    assert (sha256_file(source), source.stat().st_mtime_ns) == before


def test_ribbon_high_glow_mask_and_rgba_paths_are_equivalent(tmp_path: Path) -> None:
    source = tmp_path / "s0e00-RibbonPaths.wav"
    _source(source)
    preset = _preset(tmp_path)
    performance = _write(tmp_path / "single.toml", NO_CHUNKS)
    common: dict[str, Any] = {
        "preset_name": str(preset),
        "performance_name": str(performance),
        "formats": ["png"],
        "start": 0.2,
        "duration": 0.4,
    }
    mask = render(source, **common, output_dir=tmp_path / "mask", render_path="mask_fast")[0]
    rgba = render(source, **common, output_dir=tmp_path / "rgba", render_path="rgba_2d")[0]
    assert _job_status(mask) == _job_status(rgba) == "SUCCEEDED"
    assert _signature(mask) == _signature(rgba)
    assert_png_sequences_equal(_output(mask, "png"), _output(rgba, "png"))


def test_ribbon_worker_partition_keeps_canonical_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "s0e00-RibbonWorkers.wav"
    _source(source)
    preset = _preset(tmp_path)
    one = _write(tmp_path / "one.toml", NO_CHUNKS)
    two = _write(tmp_path / "two.toml", NO_CHUNKS.replace("jobs = 1", "jobs = 2"))
    # Exercise the maintained production pool with tiny media, never a long render.
    monkeypatch.setattr(render_module, "_FIELD_POOL_MIN_FRAMES", 1)
    common: dict[str, Any] = {"preset_name": str(preset), "formats": ["png", "prores4444"]}
    single = render(source, **common, performance_name=str(one), output_dir=tmp_path / "one")[0]
    pooled = render(source, **common, performance_name=str(two), output_dir=tmp_path / "two")[0]
    assert _job_status(single) == _job_status(pooled) == "SUCCEEDED"
    assert _signature(single) == _signature(pooled)
    analysis = pooled["analysis"]
    assert isinstance(analysis, dict) and analysis["encode_workers"] == 2
    assert_png_sequences_equal(_output(single, "png"), _output(pooled, "png"), boundary_frames={4})
    assert_decoded_prores_equal(
        _output(single, "mov"), _output(pooled, "mov"), width=96, height=160
    )


def test_silent_ribbon_keeps_transparent_background_and_only_centerline(tmp_path: Path) -> None:
    source = tmp_path / "s0e00-RibbonSilence.wav"
    _source(source, silent=True)
    preset = _preset(tmp_path)
    performance = _write(tmp_path / "single.toml", NO_CHUNKS)
    payload = render(
        source,
        preset_name=str(preset),
        performance_name=str(performance),
        formats=["png"],
        output_dir=tmp_path / "silent",
    )[0]
    assert _job_status(payload) == "SUCCEEDED"
    rgba = np.frombuffer(_png_rgba(_output(payload, "png")), dtype=np.uint8).reshape(8, 160, 96, 4)
    assert all(np.array_equal(rgba[0], frame) for frame in rgba)
    assert np.any(rgba[:, :, :, 3] == 0)
    assert np.any(rgba[:, :, :, 3] > 0), "the selected centerline disappeared"
    strong = rgba[0, :, :, 3] > 128
    assert np.count_nonzero(np.any(strong, axis=1)) <= 2
