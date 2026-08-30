from __future__ import annotations

import struct
import wave
from pathlib import Path

from ewp_waveform.application.benchmark import run_benchmark
from ewp_waveform.application.service import benchmark_dry_run


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
