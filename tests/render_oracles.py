"""Deterministic non-media oracles for renderer equivalence tests."""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

from ewp_waveform.ffmpeg.probe import probe_video
from ewp_waveform.ffmpeg.process import require_tool

_ABSOLUTE_PATH = "<absolute-path>"
_TIMESTAMP_KEYS = {"started_at", "completed_at"}


def png_frames(directory: Path) -> list[Path]:
    """Return a complete, contiguously numbered PNG sequence."""
    frames = sorted(directory.glob("frame_*.png"))
    assert frames, f"no PNG frames in {directory}"
    expected = [f"frame_{index:06d}.png" for index in range(1, len(frames) + 1)]
    assert [frame.name for frame in frames] == expected
    return frames


def assert_png_sequences_equal(
    left: Path,
    right: Path,
    *,
    boundary_frames: set[int] | None = None,
) -> None:
    """Compare every encoded PNG byte, including requested boundary neighborhoods."""
    left_frames = png_frames(left)
    right_frames = png_frames(right)
    assert [frame.name for frame in left_frames] == [frame.name for frame in right_frames]
    for left_frame, right_frame in zip(left_frames, right_frames, strict=True):
        assert left_frame.read_bytes() == right_frame.read_bytes(), left_frame.name

    for boundary in boundary_frames or set():
        for index in range(boundary - 1, boundary + 2):
            assert 0 <= index < len(left_frames), (
                f"boundary neighborhood {index} is outside {len(left_frames)} frames"
            )
            assert left_frames[index].read_bytes() == right_frames[index].read_bytes()


def decoded_prores_frames(path: Path, *, width: int, height: int) -> list[bytes]:
    """Decode ProRes to canonical RGBA frames; container bytes are intentionally ignored."""
    ffmpeg = require_tool("ffmpeg")
    completed = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    frame_bytes = width * height * 4
    assert len(completed.stdout) % frame_bytes == 0
    return [
        completed.stdout[offset : offset + frame_bytes]
        for offset in range(0, len(completed.stdout), frame_bytes)
    ]


def assert_decoded_prores_equal(
    left: Path,
    right: Path,
    *,
    width: int,
    height: int,
) -> None:
    """Require exact equality of every decoded RGBA frame."""
    left_frames = decoded_prores_frames(left, width=width, height=height)
    right_frames = decoded_prores_frames(right, width=width, height=height)
    assert left_frames
    assert left_frames == right_frames


def assert_prores_contract(
    path: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frame_count: int,
) -> None:
    """Check codec, alpha, geometry, timing, count, duration, and drift."""
    info = probe_video(path)
    assert info.codec_name == "prores"
    assert info.pix_fmt.startswith("yuva"), f"alpha channel missing from {info.pix_fmt}"
    assert (info.width, info.height) == (width, height)
    assert Fraction(info.avg_frame_rate) == Fraction(fps, 1)
    assert info.nb_frames == frame_count
    expected_duration = Fraction(frame_count, fps)
    duration = Fraction(str(info.duration_seconds))
    assert abs(duration - expected_duration) <= Fraction(1, fps)
    decoded = decoded_prores_frames(path, width=width, height=height)
    assert len(decoded) == frame_count


def semantic_result(payload: dict[str, object]) -> dict[str, object]:
    """Remove only nondeterministic timestamps, elapsed timings, and absolute paths."""

    def normalize(value: object, *, parent: str | None = None) -> object:
        if isinstance(value, dict):
            normalized: dict[str, object] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                if parent == "timestamps" and key in _TIMESTAMP_KEYS | {"duration_seconds"}:
                    continue
                if parent == "performance" and key == "seconds":
                    continue
                normalized[key] = normalize(item, parent=key)
            return normalized
        if isinstance(value, list):
            return [normalize(item, parent=parent) for item in value]
        if isinstance(value, str) and Path(value).is_absolute():
            return _ABSOLUTE_PATH
        return value

    result = normalize(payload)
    assert isinstance(result, dict)
    return result


def assert_semantic_results_equal(
    left: dict[str, object],
    right: dict[str, object],
) -> None:
    """Compare deterministic result semantics after the narrow exclusions above."""
    assert semantic_result(left) == semantic_result(right)
