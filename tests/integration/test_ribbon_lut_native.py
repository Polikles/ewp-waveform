"""Real FFmpeg byte oracles, not renderer performance or visual acceptance."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ewp_waveform.ffmpeg.ribbon import ribbon_graph
from ewp_waveform.ffmpeg.ribbon_lut import (
    GeqSampling,
    PreparedRibbonLut,
    prepare_ribbon_lut,
    probe_geq_sampling,
    ribbon_lut_argv,
)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
pytestmark = pytest.mark.skipif(shutil.which(FFMPEG) is None, reason="FFmpeg required")


def _run(argv: list[str], source: bytes) -> bytes:
    result = subprocess.run(argv, input=source, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b"", result.stderr.decode(errors="replace")
    return result.stdout


def _command(width: int, height: int, graph: str, fmt: str = "gray") -> list[str]:
    return [
        FFMPEG,
        "-hide_banner",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        fmt,
        "-s",
        f"{width}x{height}",
        "-r",
        "60",
        "-i",
        "pipe:0",
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-fps_mode",
        "passthrough",
        "-threads:v",
        "1",
        "-c:v",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def _legacy_expression(
    width: int, height: int, finish: tuple[float, bool, float, float, float]
) -> str:
    # Frozen original arithmetic, independently of candidate classes/substitution.
    reflection, enabled, thickness, extent, opacity = finish
    left, right = width * (1 - extent) / 2, width * (1 + extent) / 2
    cy = height // 2 + 0.5
    top, bottom = cy - thickness / 2, cy + thickness / 2
    line = "0"
    if enabled and extent > 0 and opacity > 0:
        line = (
            f"({opacity}*clip(min(X+1,{right})-max(X,{left}),0,1)"
            f"*clip(min(Y+1,{bottom})-max(Y,{top}),0,1))"
        )
    body = f"lum(X,Y)*if(gt(Y,{height // 2}),{reflection},1)"
    return f"255*{line}+({body})*(1-{line})"


@pytest.fixture(scope="module")
def sampling() -> GeqSampling:
    return probe_geq_sampling(FFMPEG)


def test_actual_default_geq_edges_select_identity_or_smear(sampling: GeqSampling) -> None:
    source = bytes(range(30))
    base = [
        FFMPEG,
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        "6x5",
        "-i",
        "pipe:0",
        "-vf",
    ]
    tail = ["-threads:v", "1", "-c:v", "rawvideo", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"]
    geq = _run([*base, "geq=lum='lum(X,Y)'", *tail], source)
    smear = _run([*base, "fillborders=right=1:bottom=1:mode=smear", *tail], source)
    assert smear != source  # Nonuniform final row, final column AND corner witness.
    assert geq == (source if sampling.mode == "identity" else smear)
    assert geq != (smear if sampling.mode == "identity" else source)


# Every class sees ALL 256 incoming code values, not just a few random pixels.
# Deliberately include exact/next-to-half truncation boundaries, odd/even centers,
# nonbinary fractional extents, edge lines, horizon off/zero and tiny supported edges.
CASES = [
    (18, 16, (0.45, True, 1.0, 0.96, 0.55)),
    (19, 17, (0.45, True, 2.5, 0.73, 0.6)),
    (18, 17, (0.5, True, 0.25, 0.73, 0.6)),
    (19, 16, (0.0, True, 2.0, 1.0, 1.0)),
    (18, 16, (1.0, True, 16.0, 1.0, 0.6)),
    (19, 17, (1.0, True, 34.0, 0.73, 1.0)),
    (18, 16, (0.45, False, 2.5, 0.73, 0.6)),
    (19, 17, (0.45, True, 2.5, 0.0, 0.6)),
    (18, 16, (0.45, True, 2.5, 0.73, 0.0)),
    (19, 17, (0.45, True, 0.0, 0.73, 0.6)),
    (18, 17, (0.45, True, 3.0, 0.01, 0.01)),
    (19, 16, (0.00392156862745098, True, 2.0, 0.93, 0.5019607843137255)),
    (3, 3, (0.45, True, 1.3, 0.73, 0.6)),
    (3, 5, (0.0, True, 12.0, 1.0, 0.6)),
    (4, 3, (1.0, False, 1.0, 1.0, 1.0)),
]


@pytest.mark.parametrize("width,height,finish", CASES)
def test_all_codes_and_spatial_edges_exact_rgba(
    tmp_path: Path,
    sampling: GeqSampling,
    width: int,
    height: int,
    finish: tuple[float, bool, float, float, float],
) -> None:
    graph = ribbon_graph(
        width=width,
        height=height,
        finish=finish,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=0,
    )
    prepared = prepare_ribbon_lut(
        tmp_path / "classes.pgm",
        width=width,
        height=height,
        finish=finish,
        sampling=sampling,
    )
    all_codes = np.broadcast_to(np.arange(256, dtype=np.uint8)[:, None, None], (256, height, width))
    y, x = np.indices((height, width))
    spatial = ((37 * x + 71 * y) % 256).astype(np.uint8)
    # Last row/column differ from their penultimate neighbors, including corner.
    source = all_codes.tobytes() + spatial.tobytes() + np.zeros_like(spatial).tobytes()
    legacy = graph.replace(prepared.geq_expression, _legacy_expression(width, height, finish))
    baseline = _run(_command(width, height, legacy), source)
    # Uncapped output: repeatlast must preserve all primary frames AND end at its EOF.
    candidate = _run(ribbon_lut_argv(_command(width, height, graph), prepared), source)
    assert len(baseline) == len(candidate) == 258 * width * height * 4
    assert baseline == candidate
    rgba = np.frombuffer(candidate, dtype=np.uint8).reshape(258, height, width, 4)
    assert np.all(rgba[..., :3][rgba[..., 3] > 0] == (199, 230, 236))
    assert not rgba[..., :3][rgba[..., 3] == 0].any()
    assert 1 <= prepared.class_count <= 256
    assert prepared.preparation_seconds >= 0


@pytest.mark.parametrize(
    "fmt,ss,pad,glow,color",
    [
        ("gray", 2, 3, 2.0, "#2F474F"),
        ("rgba", 1, 0, 0.0, "#F2C558"),
        ("rgba", 2, 3, 2.0, "#2F474F"),
    ],
)
def test_same_original_aa_blur_blend_crop_color_and_last_frame(
    tmp_path: Path,
    sampling: GeqSampling,
    fmt: str,
    ss: int,
    pad: int,
    glow: float,
    color: str,
) -> None:
    width, height = 19, 17
    finish = (0.45, True, 2.5, 0.73, 0.6)
    w, h = (width + 2 * pad) * ss, height + 2 * pad
    y, x = np.indices((h, w))
    gray = np.stack([((37 * x + 71 * y + i * 13) % 256).astype(np.uint8) for i in range(7)])
    gray[-1] = 0  # The final silent frame still has the independent horizon.
    source = gray.tobytes()
    if fmt == "rgba":
        rgba = np.zeros((7, h, w, 4), dtype=np.uint8)
        rgba[..., :3] = (11, 73, 219)
        rgba[..., 3] = gray
        source = rgba.tobytes()
    graph = ribbon_graph(
        width=width,
        height=height,
        finish=finish,
        overscan=pad,
        supersample=ss,
        pix_fmt=fmt,
        color=color,
        glow=glow,
    )
    prepared = prepare_ribbon_lut(
        tmp_path / "classes.pgm",
        width=width,
        height=height,
        finish=finish,
        sampling=sampling,
    )
    command = _command(w, h, graph, fmt)
    transformed = ribbon_lut_argv(command, prepared)
    baseline = _run(command, source)
    candidate = _run(transformed, source)
    assert len(candidate) == 7 * width * height * 4
    assert candidate == baseline
    before = graph.split(",geq=", 1)[0]
    after = transformed[transformed.index("-filter_complex") + 1]
    assert after.startswith(before)
    assert graph.split("',split=", 1)[1] == after.split(":repeatlast=1,format=gray,split=", 1)[1]


def test_metadata_and_static_full_canvas_mask(tmp_path: Path, sampling: GeqSampling) -> None:
    prepared = prepare_ribbon_lut(
        tmp_path / "classes.pgm",
        width=1920,
        height=1080,
        finish=(0.45, True, 1.0, 0.96, 0.55),
        sampling=sampling,
    )
    raw = prepared.mask_path.read_bytes()
    header = b"P5\n1920 1080\n255\n"
    assert raw.startswith(header)
    assert len(raw) == len(header) + 1920 * 1080
    assert len(set(raw[len(header) :])) == prepared.class_count
    assert prepared.record()["canvas_height"] == 1080
    assert prepared.class_count <= 6


@pytest.mark.parametrize("width,height", [(0, 16), (1, 16), (16, 2), (True, 16)])
def test_refuse_tiny_before_writing(
    tmp_path: Path,
    sampling: GeqSampling,
    width: int,
    height: int,
) -> None:
    path = tmp_path / "not-created.pgm"
    with pytest.raises(ValueError, match="canvas"):
        prepare_ribbon_lut(
            path,
            width=width,
            height=height,
            finish=(0.45, True, 1.0, 0.96, 0.55),
            sampling=sampling,
        )
    assert not path.exists()


@pytest.fixture
def small(tmp_path: Path, sampling: GeqSampling) -> PreparedRibbonLut:
    return prepare_ribbon_lut(
        tmp_path / "classes.pgm",
        width=18,
        height=16,
        finish=(0.45, True, 1.0, 0.96, 0.55),
        sampling=sampling,
    )


def test_refuse_overwrite_and_unknown_argv(small: PreparedRibbonLut) -> None:
    with pytest.raises(FileExistsError):
        prepare_ribbon_lut(
            small.mask_path,
            width=small.width,
            height=small.height,
            finish=small.finish,
            sampling=small.sampling,
        )
    graph = ribbon_graph(
        width=18,
        height=16,
        finish=small.finish,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=0,
    )
    command = _command(18, 16, graph)
    for bad in (
        [*command, "-map", "0:v"],
        [*command, "-i", "other.pgm"],
        ["other-ffmpeg", *command[1:]],
        [arg.replace("0.45", "0.46") for arg in command],
        [arg.replace("[vout]", "[unknown]") for arg in command],
        [arg.replace("18x16", "19x16") for arg in command],
        [arg.replace("[0:v]format=gray", "[0:v]format=gray,hflip") for arg in command],
        [arg.replace("-filter_complex", "-vf") for arg in command],
        [*command[: command.index("-map")], "-map"],
    ):
        with pytest.raises(ValueError):
            ribbon_lut_argv(bad, small)
    converted = ribbon_lut_argv(command, small)
    assert command.count("-i") == 1  # Input argv not mutated.
    assert converted.count("-i") == 2
    assert converted[-12:] == command[-12:]  # Encoder/thread/output suffix unchanged.
