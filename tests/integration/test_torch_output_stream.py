"""Five 16x16 CPU frames through real ProRes; not production/CUDA qualification."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.torch_experiment import _torch_stream
from ewp_waveform.ffmpeg.encode import encode_rgba_stream
from ewp_waveform.ffmpeg.torch_finish import FinishSpec, TorchFinisher


@pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or not shutil.which("ffmpeg"),
    reason="optional Torch and FFmpeg required",
)
@pytest.mark.parametrize("output_mode", ["host-reuse", "device-rgba", "device-alpha8"])
def test_tiny_cpu_batched_prores_matches_control(output_mode: str, tmp_path: Path) -> None:
    spec = FinishSpec(width=16, height=16, overscan=0, sigma=0, reflection=1, horizon=False)
    frames = [
        np.full(spec.input_shape, alpha, dtype=np.uint8).tobytes() for alpha in (0, 1, 37, 255, 19)
    ]
    decoded: list[bytes] = []
    for mode in ("host-reference", output_mode):
        output = tmp_path / f"{mode}.mov"
        worker = TorchFinisher(spec, "cpu", output_mode=mode, batch_size=2, timing_mode="ordinary")
        counters: dict[str, Any] = {
            "finishing_wall_seconds": 0.0,
            "batch_calls": [],
            "frame_calls": [],
        }
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
        assert output.is_file()
        assert [row["frames"] for row in counters["batch_calls"]] == [2, 2, 1]
        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "1",
                "-i",
                str(output),
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert len(raw) == 5 * spec.width * spec.height * 4
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(5, spec.height, spec.width, 4)
        expected_alpha = np.asarray([0, 1, 37, 255, 19], dtype=np.int16)
        assert np.max(np.abs(pixels[:, 0, 0, 3].astype(np.int16) - expected_alpha)) <= 1
        decoded.append(raw)
    assert decoded[0] == decoded[1]
