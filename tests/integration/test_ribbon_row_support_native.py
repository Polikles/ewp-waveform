"""Tiny exact oracles against the pre-guard geq expression, not timing tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from ewp_waveform.config.load import load_preset
from ewp_waveform.config.ribbon import apply_public_appearance
from ewp_waveform.ffmpeg.encode import _glow_crop_graph

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe required",
)


@dataclass(frozen=True)
class Case:
    height: int
    rgba: bool
    glow: float
    ss: int
    pad: int
    mode: str
    finish: tuple[float, bool, float, float, float]


# Pairwise boundary coverage, deliberately not a Cartesian performance matrix.
CASES = [
    Case(16, False, 0, 1, 0, "dark-background", (0.45, True, 1.0, 0.96, 0.55)),
    Case(17, True, 2, 2, 3, "light-background", (0.45, True, 1.0, 0.96, 0.55)),
    Case(17, False, 0, 2, 0, "light-background", (0.0, True, 0.25, 0.73, 0.6)),
    Case(16, True, 2, 1, 3, "dark-background", (1.0, True, 2.0, 1.0, 1.0)),
    Case(16, False, 2, 2, 3, "dark-background", (0.45, True, 2.5, 0.73, 0.6)),
    Case(17, True, 0, 1, 0, "light-background", (0.45, True, 3.0, 0.01, 0.01)),
    Case(17, False, 2, 1, 3, "light-background", (0.0, False, 2.5, 0.73, 0.6)),
    Case(16, True, 0, 2, 0, "dark-background", (1.0, True, 2.5, 0.0, 0.6)),
    Case(17, False, 0, 1, 0, "dark-background", (0.45, True, 2.5, 0.73, 0.0)),
    Case(16, True, 2, 2, 3, "light-background", (0.45, True, 0.0, 0.73, 0.6)),
    Case(16, False, 0, 1, 0, "light-background", (0.0, True, 16.0, 1.0, 0.6)),
    Case(17, True, 2, 1, 3, "dark-background", (1.0, True, 34.0, 0.73, 1.0)),
]


def _legacy_expression(width: int, case: Case) -> str:
    # Frozen pre-optimization arithmetic, independent of candidate support bounds.
    reflection, enabled, thickness, extent, opacity = case.finish
    left, right = width * (1 - extent) / 2, width * (1 + extent) / 2
    cy = case.height // 2 + 0.5
    top, bottom = cy - thickness / 2, cy + thickness / 2
    line = "0"
    if enabled and extent > 0 and opacity > 0:
        line = (
            f"({opacity}*clip(min(X+1,{right})-max(X,{left}),0,1)"
            f"*clip(min(Y+1,{bottom})-max(Y,{top}),0,1))"
        )
    body = f"lum(X,Y)*if(gt(Y,{case.height // 2}),{reflection},1)"
    return f"255*{line}+({body})*(1-{line})"


def _run(argv: list[str], data: bytes | None = None) -> bytes:
    result = subprocess.run(argv, input=data, capture_output=True, check=True, timeout=30)
    assert not result.stderr, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.mark.parametrize("case", CASES, ids=[f"boundary-{i}" for i in range(len(CASES))])
def test_exact_canonical_encoder_input_and_native_decoded_alpha(
    tmp_path: Path,
    case: Case,
) -> None:
    width = 18
    w, h = (width + 2 * case.pad) * case.ss, case.height + 2 * case.pad
    y, x = np.indices((h, w))
    mask = ((x * 37 + y * 71) % 256).astype(np.uint8)
    mask[0, :6] = (0, 1, 127, 128, 254, 255)
    # Nonuniform last row/column detect changes to geq's default lum interpolation.
    frames = np.stack((mask, np.zeros_like(mask)))
    data = frames.tobytes()
    if case.rgba:
        pixels = np.empty((2, h, w, 4), dtype=np.uint8)
        pixels[..., :3] = (11, 73, 219)  # Incoming RGB must not color alpha finishing.
        pixels[..., 3] = frames
        data = pixels.tobytes()
    preset = apply_public_appearance(
        load_preset("iuris-ribbon-refined"),
        background_mode=case.mode,
        color_mode="auto",
    )
    graph = _glow_crop_graph(
        case.glow,
        width,
        case.height,
        case.pad,
        case.ss,
        pix_fmt="rgba" if case.rgba else "gray",
        color=preset.waveform.color,
        ribbon_finish=case.finish,
    )
    prefix, rest = graph.split("geq=lum='", 1)
    _, suffix = rest.split("'", 1)
    legacy = prefix + "geq=lum='" + _legacy_expression(width, case) + "'" + suffix
    outputs: list[tuple[bytes, bytes, bytes]] = []
    for name, selected in (("legacy", legacy), ("candidate", graph)):
        rgba = tmp_path / f"{name}.rgba"
        native = tmp_path / f"{name}.yuva444p10le"
        mov = tmp_path / f"{name}.mov"
        selected += ";[vout]split=3[canonical][native][encode]"
        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba" if case.rgba else "gray",
                "-s",
                f"{w}x{h}",
                "-r",
                "60",
                "-i",
                "-",
                "-filter_complex",
                selected,
                "-map",
                "[canonical]",
                "-frames:v",
                "2",
                "-threads",
                "1",
                "-c:v",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "-f",
                "rawvideo",
                str(rgba),
                "-map",
                "[native]",
                "-frames:v",
                "2",
                "-threads",
                "1",
                "-c:v",
                "rawvideo",
                "-pix_fmt",
                "yuva444p10le",
                "-f",
                "rawvideo",
                str(native),
                "-map",
                "[encode]",
                "-fps_mode",
                "cfr",
                "-r",
                "60",
                "-frames:v",
                "2",
                "-threads",
                "1",
                "-c:v",
                "prores_ks",
                "-profile:v",
                "4444",
                "-pix_fmt",
                "yuva444p10le",
                str(mov),
            ],
            data,
        )
        info = json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,pix_fmt,nb_frames,width,height,r_frame_rate",
                    "-of",
                    "json",
                    str(mov),
                ]
            )
        )["streams"][0]
        assert info == {
            "codec_name": "prores",
            "width": width,
            "height": case.height,
            "pix_fmt": "yuva444p12le",
            "r_frame_rate": "60/1",
            "nb_frames": "2",
        }
        decoded = _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(mov),
                "-map",
                "0:v:0",
                "-c:v",
                "rawvideo",
                "-pix_fmt",
                "yuva444p12le",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        buffers = (rgba.read_bytes(), native.read_bytes(), decoded)
        assert len(buffers[0]) == 2 * width * case.height * 4
        assert len(buffers[1]) == len(decoded) == 2 * width * case.height * 8
        outputs.append(buffers)
    assert outputs[0] == outputs[1]  # Actual byte comparisons of all four native planes.
    canonical = np.frombuffer(outputs[1][0], np.uint8).reshape(2, case.height, width, 4)
    alpha = canonical[..., 3]
    assert alpha.any() and np.any(alpha < 255)
    rgb = (199, 230, 236) if case.mode == "dark-background" else (47, 71, 79)
    assert np.all(canonical[..., :3][alpha > 0] == rgb)
    assert not canonical[..., :3][alpha == 0].any()
    native_alpha = np.frombuffer(outputs[1][2], "<u2").reshape(2, 4, case.height, width)[:, 3]
    assert np.any(native_alpha > 0) and np.any(native_alpha < 4095)
