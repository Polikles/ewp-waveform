from __future__ import annotations

import json
import struct
import subprocess
import wave
from pathlib import Path

from ewp_waveform.application.service import render
from ewp_waveform.identity import sha256_file

TINY_PRESET = """
schema_version = 1
name = "tiny-scroll"
description = "Fast fixture for SKIP/chunk tests."

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

TINY_CHUNKS = """
schema_version = 1
name = "tiny-chunks"

[processing]
chunk_seconds = 0.25
jobs = 1
ffmpeg_threads = 1

[workdirs]
persistent = false
keep_on_success = false
keep_on_failure = true
"""

NO_CHUNKS = """
schema_version = 1
name = "tiny-one-chunk"

[processing]
chunk_seconds = 60
jobs = 1
ffmpeg_threads = 1

[workdirs]
persistent = false
keep_on_success = false
keep_on_failure = true
"""


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


def _write(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


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
    validation = results[0]["validation"]
    assert isinstance(validation, dict)
    assert validation["passed"] is True


def _job_status(payload: dict[str, object]) -> str:
    job = payload["job"]
    assert isinstance(job, dict)
    status = job["status"]
    assert isinstance(status, str)
    return status


def _first_output(payload: dict[str, object]) -> Path:
    outputs = payload["outputs"]
    assert isinstance(outputs, list)
    assert outputs
    entry = outputs[0]
    assert isinstance(entry, dict)
    return Path(str(entry["path"]))


def test_equivalent_job_is_skipped_and_lists_outputs(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Skip.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    out = tmp_path / "out"
    first = render(
        src,
        output_dir=out,
        formats=["prores4444"],
        preset_name=str(preset),
        force=False,
    )
    assert _job_status(first[0]) == "SUCCEEDED"
    mov = _first_output(first[0])
    assert mov.is_file()
    before = mov.stat().st_mtime_ns
    second = render(
        src,
        output_dir=out,
        formats=["prores4444"],
        preset_name=str(preset),
        force=False,
    )
    assert _job_status(second[0]) == "SKIPPED"
    assert _first_output(second[0]) == mov
    assert mov.stat().st_mtime_ns == before
    validation = second[0]["validation"]
    assert isinstance(validation, dict)
    assert validation["passed"] is True


def test_empty_dest_is_not_skipped(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Empty.wav"
    _tone_wav(src, seconds=0.4, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    first = render(
        src,
        output_dir=tmp_path / "out",
        formats=["prores4444"],
        preset_name=str(preset),
        force=False,
    )
    mov = _first_output(first[0])
    mov.write_bytes(b"")
    second = render(
        src,
        output_dir=tmp_path / "out",
        formats=["prores4444"],
        preset_name=str(preset),
        force=False,
    )
    assert _job_status(second[0]) == "SUCCEEDED"
    assert mov.is_file()
    assert mov.stat().st_size > 0


def test_chunked_png_matches_unchunked_at_join(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Chunk.wav"
    _tone_wav(src, seconds=0.6, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    one = _write(tmp_path / "one.toml", NO_CHUNKS)
    many = _write(tmp_path / "many.toml", TINY_CHUNKS)
    unchunked = render(
        src,
        output_dir=tmp_path / "one",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(one),
        force=True,
    )
    chunked = render(
        src,
        output_dir=tmp_path / "many",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(many),
        force=True,
    )
    assert _job_status(unchunked[0]) == "SUCCEEDED"
    assert _job_status(chunked[0]) == "SUCCEEDED"
    analysis = chunked[0]["analysis"]
    assert isinstance(analysis, dict)
    assert int(analysis["chunk_count"]) >= 2
    one_dir = _first_output(unchunked[0])
    many_dir = _first_output(chunked[0])
    one_frames = sorted(one_dir.glob("frame_*.png"))
    many_frames = sorted(many_dir.glob("frame_*.png"))
    assert [path.name for path in one_frames] == [path.name for path in many_frames]
    assert one_frames
    join = one_frames[len(one_frames) // 2]
    for name in (one_frames[0].name, join.name, one_frames[-1].name):
        assert (one_dir / name).read_bytes() == (many_dir / name).read_bytes()


def _chunks_perf(root: Path) -> str:
    return f"""
schema_version = 1
name = "tiny-chunks-resume"

[processing]
chunk_seconds = 0.25
jobs = 1
ffmpeg_threads = 1

[workdirs]
persistent = true
root = "{root}"
keep_on_success = false
keep_on_failure = true
"""


def _warning_codes(payload: dict[str, object]) -> list[str]:
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    codes: list[str] = []
    for item in warnings:
        assert isinstance(item, dict)
        codes.append(str(item["code"]))
    return codes


def test_resume_reuses_validated_chunks(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Resume.wav"
    _tone_wav(src, seconds=0.6, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    performance = _write(tmp_path / "perf.toml", _chunks_perf(tmp_path / "work"))
    interrupted = render(
        src,
        output_dir=tmp_path / "out",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(performance),
        fail_after_chunk=0,
    )
    assert _job_status(interrupted[0]) == "FAILED"
    execution = interrupted[0]["execution"]
    assert isinstance(execution, dict)
    workdir = Path(str(execution["workdir"]))
    assert (workdir / "checkpoint.json").is_file()
    assert (workdir / "png" / "frame_000001.png").is_file()
    first_png = (workdir / "png" / "frame_000001.png").read_bytes()
    resumed = render(
        src,
        output_dir=tmp_path / "out",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(performance),
    )
    assert _job_status(resumed[0]) == "SUCCEEDED"
    assert "W_JOB_RESUMED" in _warning_codes(resumed[0])
    history = resumed[0]["resume_history"]
    assert isinstance(history, list)
    assert history
    assert isinstance(history[0], dict)
    assert history[0]["reused_chunks"] == [0]
    dest = _first_output(resumed[0])
    assert (dest / "frame_000001.png").read_bytes() == first_png
    reference = render(
        src,
        output_dir=tmp_path / "ref",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(performance),
        force=True,
    )
    assert _job_status(reference[0]) == "SUCCEEDED"
    ref_dir = _first_output(reference[0])
    for name in ("frame_000001.png", "frame_000004.png"):
        assert (dest / name).read_bytes() == (ref_dir / name).read_bytes()


def test_stale_checkpoint_is_not_reused(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Stale.wav"
    _tone_wav(src, seconds=0.6, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    performance = _write(tmp_path / "perf.toml", _chunks_perf(tmp_path / "work"))
    interrupted = render(
        src,
        output_dir=tmp_path / "out",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(performance),
        fail_after_chunk=0,
    )
    execution = interrupted[0]["execution"]
    assert isinstance(execution, dict)
    workdir = Path(str(execution["workdir"]))
    checkpoint = workdir / "checkpoint.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["render_signature"] = "0" * 64
    checkpoint.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    first_png = workdir / "png" / "frame_000001.png"
    first_png.write_bytes(b"stale")
    resumed = render(
        src,
        output_dir=tmp_path / "out",
        formats=["png"],
        preset_name=str(preset),
        performance_name=str(performance),
    )
    assert _job_status(resumed[0]) == "SUCCEEDED"
    assert "W_JOB_RESUMED" not in _warning_codes(resumed[0])
    dest = _first_output(resumed[0])
    assert (dest / "frame_000001.png").read_bytes() != b"stale"
