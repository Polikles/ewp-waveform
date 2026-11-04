from __future__ import annotations

import importlib
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from ewp_waveform.application.render import _validate_mov, _validate_png
from ewp_waveform.application.service import render
from ewp_waveform.ffmpeg.probe import probe_video
from tests.integration.test_render import TINY_PRESET, TINY_SPECTRUM, _tone_wav, _write

render_module = importlib.import_module("ewp_waveform.application.render")


def _images(directory: Path, *, size: str = "80x32", pix_fmt: str = "rgba") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=red:s={size}:r=10,format={pix_fmt}",
            "-frames:v",
            "3",
            "-threads",
            "1",
            str(directory / "frame_%06d.png"),
        ],
        check=True,
        capture_output=True,
    )


def _movie(
    path: Path,
    *,
    size: str = "80x32",
    rate: int = 10,
    count: int = 3,
    codec: str = "prores_ks",
    profile: str = "4",
    pix_fmt: str = "yuva444p10le",
) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=red:s={size}:r={rate},format={pix_fmt}",
            "-frames:v",
            str(count),
            "-c:v",
            codec,
            "-profile:v",
            profile,
            "-threads",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _png_passes(path: Path) -> bool:
    return bool(_validate_png(path, expected_frames=3, width=80, height=32)["passed"])


def _mov_passes(path: Path) -> bool:
    return bool(_validate_mov(path, expected_frames=3, width=80, height=32, fps=10)["passed"])


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "malformed",
        "truncated",
        "gap",
        "wrong-size",
        "rgb",
        "directory",
    ],
)
def test_production_png_rejects_invalid_later_frame(tmp_path: Path, damage: str) -> None:
    directory = tmp_path / "png"
    _images(directory)
    assert _png_passes(directory)
    frame = directory / "frame_000002.png"
    if damage == "missing":
        frame.unlink()
    elif damage == "empty":
        frame.write_bytes(b"")
    elif damage == "malformed":
        frame.write_bytes(b"this is not a PNG")
    elif damage == "truncated":
        data = frame.read_bytes()
        frame.write_bytes(data[: len(data) // 2])
    elif damage == "gap":
        frame.rename(directory / "frame_000004.png")
    elif damage in {"wrong-size", "rgb"}:
        other = tmp_path / "other"
        _images(
            other,
            size="40x16" if damage == "wrong-size" else "80x32",
            pix_fmt="rgb24" if damage == "rgb" else "rgba",
        )
        shutil.copyfile(other / "frame_000001.png", frame)
    else:
        frame.unlink()
        frame.mkdir()
    assert not _png_passes(directory)


def test_production_png_missing_directory(tmp_path: Path) -> None:
    assert not _png_passes(tmp_path / "missing")


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "truncated",
        "malformed",
        "wrong-size",
        "wrong-fps",
        "wrong-count",
        "no-alpha",
        "wrong-codec",
    ],
)
def test_production_mov_rejects_incompatible_output(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "asset.mov"
    _movie(path)
    assert _mov_passes(path)
    if damage == "missing":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    elif damage == "truncated":
        path.write_bytes(path.read_bytes()[:64])
    elif damage == "malformed":
        path.write_bytes(b"not a movie")
    elif damage == "wrong-size":
        _movie(path, size="40x16")
    elif damage == "wrong-fps":
        _movie(path, rate=5)
    elif damage == "wrong-count":
        _movie(path, count=6)
    elif damage == "no-alpha":
        _movie(path, profile="3", pix_fmt="yuv422p10le")
    else:
        _movie(path, codec="mpeg4", profile="0", pix_fmt="yuv420p")
    assert not _mov_passes(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("avg_frame_rate", "0/0"),
        ("avg_frame_rate", ""),
        ("nb_frames", None),
        ("duration_seconds", 0.0),
        ("duration_seconds", float("nan")),
        ("duration_seconds", 2.0),
        ("profile", "HQ"),
    ],
)
def test_mov_missing_or_inconsistent_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    path = tmp_path / "asset.mov"
    _movie(path)
    info = probe_video(path)
    altered = replace(info, **{field: value})
    monkeypatch.setattr(render_module, "probe_video", lambda _: altered)
    assert not _mov_passes(path)


@pytest.mark.parametrize("fmt", ["png", "prores4444"])
@pytest.mark.parametrize("frequency", [False, True])
def test_valid_outputs_reuse_and_invalid_destinations_do_not_skip(
    tmp_path: Path,
    fmt: str,
    frequency: bool,
) -> None:
    src = tmp_path / "s0e00-Validation.wav"
    _tone_wav(src, seconds=0.3, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_SPECTRUM if frequency else TINY_PRESET)
    out = tmp_path / "out"
    first = render(src, output_dir=out, formats=[fmt], preset_name=str(preset))[0]
    assert first["job"]["status"] == "SUCCEEDED"
    asset = Path(str(first["outputs"][0]["path"]))
    before = (
        {p: p.stat().st_mtime_ns for p in asset.iterdir()}
        if asset.is_dir()
        else {
            asset: asset.stat().st_mtime_ns,
        }
    )
    second = render(src, output_dir=out, formats=[fmt], preset_name=str(preset))[0]
    assert second["job"]["status"] == "SKIPPED"
    assert second["validation"]["passed"] is True
    assert {p: p.stat().st_mtime_ns for p in before} == before
    if fmt == "png":
        (asset / "frame_000002.png").write_bytes(b"bad PNG")
    else:
        _movie(asset, rate=5)
    third = render(src, output_dir=out, formats=[fmt], preset_name=str(preset))[0]
    assert third["job"]["status"] == "SUCCEEDED"
    assert third["validation"]["passed"] is True
    fourth = render(src, output_dir=out, formats=[fmt], preset_name=str(preset))[0]
    assert fourth["job"]["status"] == "SKIPPED"


@pytest.mark.parametrize("frequency", [False, True])
@pytest.mark.parametrize("damage", ["missing-png", "bad-png", "bad-mov"])
def test_invalid_work_output_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frequency: bool,
    damage: str,
) -> None:
    src = tmp_path / "s0e00-Validation.wav"
    _tone_wav(src, seconds=0.3, rate=48000)
    preset = _write(tmp_path / "tiny.toml", TINY_SPECTRUM if frequency else TINY_PRESET)
    original = render_module.encode_rgba_stream

    def damaged_encode(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        if damage == "bad-mov":
            path = kwargs["prores_path"]
            assert isinstance(path, Path)
            _movie(path, rate=5)
        else:
            directory = kwargs["png_dir"]
            assert isinstance(directory, Path)
            if damage == "missing-png":
                shutil.rmtree(directory)
            else:
                (directory / "frame_000002.png").write_bytes(b"bad PNG")

    monkeypatch.setattr(render_module, "encode_rgba_stream", damaged_encode)
    fmt = "prores4444" if damage == "bad-mov" else "png"
    result = render(src, output_dir=tmp_path / "out", formats=[fmt], preset_name=str(preset))[0]
    assert result["job"]["status"] == "FAILED"
    assert result["validation"]["passed"] is False
    assert result["outputs"] == []
    assert any(item["code"] == "E_OUTPUT_VALIDATION" for item in result["warnings"])
