from __future__ import annotations

import struct
import subprocess
import wave
from pathlib import Path

from ewp_waveform.application.service import render
from ewp_waveform.identity import sha256_file


def _tone_wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> None:
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


def test_scroll_render_writes_prores_and_preserves_source(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    before = sha256_file(src)
    results = render(
        src,
        output_dir=tmp_path / "out",
        formats=["prores4444"],
        preset_name="iuris-default",
        force=True,
    )
    assert results
    job = results[0]["job"]
    assert isinstance(job, dict)
    assert job["status"] == "SUCCEEDED"
    outputs = results[0]["outputs"]
    assert isinstance(outputs, list)
    mov = Path(str(outputs[0]["path"]))
    assert mov.is_file()
    assert sha256_file(src) == before
    probed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt",
            "-of",
            "default=noprint_wrappers=1",
            str(mov),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "codec_name=prores" in probed.stdout
    assert "yuva" in probed.stdout
