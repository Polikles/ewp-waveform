"""Real tiny CPU-Torch/ProRes tail, order, cadence and silence; not native CUDA."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.portable_experiments_worker import validate_batch_tail
from ewp_waveform.application.torch_experiment import _torch_stream
from ewp_waveform.ffmpeg.encode import encode_rgba_stream
from ewp_waveform.ffmpeg.experiment_suite_validation import inspect
from ewp_waveform.ffmpeg.torch_finish import FinishSpec, TorchFinisher


@pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or not shutil.which("ffmpeg"),
    reason="optional CPU Torch/FFmpeg required; native CUDA remains target-only",
)
def test_actual_cpu_torch_odd_tail_order_timestamps_and_no_audio(tmp_path: Path) -> None:
    spec = FinishSpec(width=16, height=16, overscan=0, sigma=0, reflection=1, horizon=False)
    alphas = [0, 1, 37, 255, 19]
    frames = [np.full(spec.input_shape, alpha, dtype=np.uint8).tobytes() for alpha in alphas]
    worker = TorchFinisher(
        spec, "cpu", output_mode="device-rgba", batch_size=2, timing_mode="ordinary"
    )
    counters: dict[str, Any] = {"finishing_wall_seconds": 0.0, "batch_calls": [], "frame_calls": []}
    output = tmp_path / "five-frame.mov"
    encode_rgba_stream(
        _torch_stream(frames, worker, "gray", counters),
        width=16,
        height=16,
        fps=60,
        glow=0,
        png_dir=None,
        prores_path=output,
        ffmpeg_threads=1,
    )
    batch = validate_batch_tail(counters, 5, 2)
    assert batch["final_batch_first_frame"] == 4 and batch["final_batch_frames"] == 1
    checked = inspect(
        "ffmpeg",
        "ffprobe",
        output,
        width=16,
        height=16,
        frames=5,
        log=tmp_path / "commands.jsonl",
        require_silent=True,
    )
    assert checked["passed"] and checked["silent"] and checked["audio_streams"] == 0
    assert checked["max_pts_error_seconds"] == "0"
    assert checked["frame_grid_seconds"] == "1/12"
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        check=True,
        capture_output=True,
    ).stdout
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(5, 16, 16, 4)
    assert np.max(np.abs(pixels[:, 0, 0, 3].astype(np.int16) - np.array(alphas))) <= 1
    assert worker.evidence()["device"] == "cpu" and not worker.cuda
    with_audio = tmp_path / "invalid-with-audio.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(output),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "pcm_s16le",
            "-t",
            "0.083333333",
            str(with_audio),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="silent single-video"):
        inspect(
            "ffmpeg",
            "ffprobe",
            with_audio,
            width=16,
            height=16,
            frames=5,
            log=tmp_path / "audio-refusal.jsonl",
            require_silent=True,
        )
    (tmp_path / "proof.json").write_text(
        json.dumps({"cpu_torch_only": True, "batch": batch, "validation": checked}, indent=2)
    )
