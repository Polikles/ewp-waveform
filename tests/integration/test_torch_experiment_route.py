"""Actual production raster seam and independent CPU ProRes outputs; no Torch required."""

from __future__ import annotations

import hashlib
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from ewp_waveform.application.torch_experiment import render_experiment


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg executables required"
)
def test_original_raster_numpy_ffmpeg_comparison(tmp_path: Path) -> None:
    source = tmp_path / "original.wav"
    rate = 24000
    samples = [int(10000 * math.sin(2 * math.pi * 330 * i / rate)) for i in range(12000)]
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 2, rate, len(samples), "NONE", "not compressed"))
        stream.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    overrides = {
        "reflection_opacity": 0.0,
        "center_line": False,
        "visual_noise": 0.35,
        "noise_seed": 1729,
    }
    baseline = render_experiment(
        source=source,
        start=0.1,
        duration=0.1,
        output=tmp_path / "ffmpeg" / "baseline.mov",
        backend="ffmpeg",
        visual_overrides=overrides,
    )
    result = render_experiment(
        source=source,
        start=0.1,
        duration=0.1,
        output=tmp_path / "numpy" / "fir.mov",
        backend="numpy",
        reference=Path(baseline["output"]),
        preview=tmp_path / "checker.mp4",
        visual_overrides=overrides,
    )
    assert result["status"] == baseline["status"] == "SUCCEEDED"
    assert result["original_raster_sha256"] == baseline["original_raster_sha256"]
    assert result["bounds"]["frames"] == baseline["bounds"]["frames"] == 6
    assert result["bounds"]["effective_start"] == 0.1
    assert result["analysis"]["encode_workers"] == 1
    assert result["spec"]["supersample"] == 2
    assert result["spec"]["overscan"] == 50
    assert result["spec"]["sigma"] == 16
    assert result["spec"]["reflection"] == 0.0
    assert result["spec"]["horizon"] is False
    assert result["visual_overrides"] == overrides
    assert result["effective_preset"] == baseline["effective_preset"]
    assert result["encoder_envelope_wall_seconds"] > 0
    assert result["exclusive_encoding_wall_seconds"] is None
    assert result["validation"]["passed"]
    assert result["validation"]["alpha_min"] == 0
    assert result["validation"]["alpha_max"] > 141  # Not just the independent idle horizon.
    assert result["validation"]["edge_halo_composite_integer_metrics"]["union_count"] > 0
    assert result["raster_feed"]["frames"] == 6
    assert len(result["raster_feed"]["frame_calls"]) == 6
    assert result["external_cold_process_wall_seconds"] is None
    assert Path(result["preview"]).is_file()
    assert result["visual_acceptance"] == result["nle_acceptance"] == "PENDING"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError, match="fresh"):
        render_experiment(
            source=source, start=0.1, duration=0.1, output=tmp_path / "numpy" / "again.mov"
        )
