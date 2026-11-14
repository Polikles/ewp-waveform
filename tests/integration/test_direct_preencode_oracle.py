"""Tiny actual FFV1 pre-encode byte oracle, not a full/direct-run proof."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from ewp_waveform.ffmpeg.encode import encode_rgba_stream
from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding
from ewp_waveform.ffmpeg.experiment_suite_validation import decoded
from ewp_waveform.ffmpeg.ribbon import ribbon_graph


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_ffv1_matches_bounded_finished_preencode_rgba(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    width, height, count = 18, 16, 6
    finish = (0.45, True, 1.0, 0.96, 0.55)
    source = [
        bytes(
            (x * 31 + y * 17 + frame * 11) % 256 if 2 <= x < 16 and 2 <= y < 14 else 0
            for y in range(height)
            for x in range(width)
        )
        for frame in range(count)
    ]
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
    # Same masks and finishing graph, but raw RGBA sink BEFORE any lossy/lossless
    # codec. All six tiny frames are bounded in memory; no raw file is persisted.
    oracle = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-s",
            "18x16",
            "-r",
            "60",
            "-i",
            "pipe:0",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-frames:v",
            str(count),
            "-c:v",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        input=b"".join(source),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert oracle.stderr == b""
    assert len(oracle.stdout) == count * width * height * 4
    output = tmp_path / "native.mkv"
    log = tmp_path / "commands.jsonl"
    encode_rgba_stream(
        iter(source),
        png_dir=None,
        prores_path=output,
        width=width,
        height=height,
        fps=60,
        glow=0,
        pix_fmt="gray",
        color="#C7E6EC",
        n_frames=count,
        ribbon_finish=finish,
        experiment=SuiteEncoding("FFV1-DIRECT", log),
    )
    with decoded(ffmpeg, output, log, width * height * 4) as blocks:
        actual = b"".join(blocks)
    assert actual == oracle.stdout  # Includes hidden RGB and fractional alpha.
    assert any(0 < a < 255 for a in actual[3::4])
    assert 0 in actual[3::4]
    (tmp_path / "bounded-oracle.txt").write_text(
        f"frames={count}\nrgba_sha256={hashlib.sha256(actual).hexdigest()}\n"
        "scope=tiny software FFV1 finishing/encode/decode proof, not native Windows "
        "or an unmeasured production direct invocation\n"
    )
