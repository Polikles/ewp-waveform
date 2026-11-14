"""Real tiny FFmpeg graph fixtures and original-audio production pipeline smoke."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from ewp_waveform.application.working_area_experiment import render_working_area
from ewp_waveform.ffmpeg.experiments import Crop
from ewp_waveform.ffmpeg.ribbon import ribbon_graph
from ewp_waveform.ffmpeg.working_area import WorkingArea, difference_metrics, working_area_graph

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="actual FFmpeg pair required"
)


def _finish(
    mask: np.ndarray,
    *,
    area: WorkingArea,
    control: str,
    pad: int,
    ss: int,
    sigma: float,
    finish: tuple[float, bool, float, float, float],
) -> np.ndarray:
    graph = working_area_graph(
        area=area,
        control=control,
        overscan=pad,
        supersample=ss,
        glow=sigma,
        color="#F2C558",
        finish=finish,
    )
    c = area.crop
    argv = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        f"{(c.canvas_width + 2 * pad) * ss}x{c.canvas_height + 2 * pad}",
        "-r",
        "60",
        "-i",
        "-",
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-pix_fmt",
        "rgba",
        "-f",
        "rawvideo",
        "-",
    ]
    result = subprocess.run(argv, input=mask.tobytes(), capture_output=True, timeout=30, check=True)
    assert not result.stderr
    w, h = (c.canvas_width, c.canvas_height) if control == "CPU-BASE" else (c.width, c.height)
    assert len(result.stdout) == len(mask) * w * h * 4  # final frame, no fps padding/drop
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(len(mask), h, w, 4)


@pytest.mark.parametrize(
    "crop,pad,ss",
    [
        (Crop(3, 7, 16, 8, 24, 20), 6, 2),
        (Crop(1, 0, 20, 6, 24, 20), 6, 1),
        (Crop(0, 14, 24, 6, 24, 20), 0, 2),
        (Crop(0, 3, 2, 2, 2, 8), 4, 2),
        (Crop(0, 0, 2, 2, 2, 2), 4, 2),
    ],
)
@pytest.mark.parametrize("sigma", [0.0, 1.0])
def test_actual_gray_aa_edges_transforms_fractional_alpha_and_last_frame(
    crop: Crop, pad: int, ss: int, sigma: float
) -> None:
    area = WorkingArea(crop, 3)
    shape = (3, crop.canvas_height + 2 * pad, (crop.canvas_width + 2 * pad) * ss)
    mask = np.zeros(shape, dtype=np.uint8)
    mask[0, pad : pad + crop.canvas_height, pad * ss : (pad + crop.canvas_width) * ss] = 127
    mask[1, :, ::2] = 253  # includes physical canvas/overscan edges and subpixel AA
    mask[2, pad + crop.canvas_height // 2, :] = 255  # distinguish the final frame
    finish = (0.37, True, 1.25, 0.73, 0.55)
    full = _finish(mask, area=area, control="CPU-BASE", pad=pad, ss=ss, sigma=sigma, finish=finish)
    cropped = _finish(
        mask, area=area, control="CROP-OUT", pad=pad, ss=ss, sigma=sigma, finish=finish
    )
    early = _finish(
        mask, area=area, control="EARLY-AREA", pad=pad, ss=ss, sigma=sigma, finish=finish
    )
    assert np.array_equal(
        cropped, full[:, crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    )
    if sigma == 0:
        assert np.array_equal(early, cropped)  # exact coordinate/reflection/horizon oracle
    assert np.any((early[:, :, :, 3] > 0) & (early[:, :, :, 3] < 255))
    assert not np.array_equal(early[0], early[2])
    assert np.all(early[:, :, :, :3][early[:, :, :, 3] == 0] == 0)
    assert working_area_graph(
        area=area,
        control="CPU-BASE",
        overscan=pad,
        supersample=ss,
        glow=sigma,
        color="#F2C558",
        finish=finish,
    ) == ribbon_graph(
        width=crop.canvas_width,
        height=crop.canvas_height,
        overscan=pad,
        supersample=ss,
        pix_fmt="gray",
        color="#F2C558",
        glow=sigma,
        finish=finish,
    )


@pytest.mark.parametrize("horizon", [False, True])
def test_actual_silent_masks_preserve_fractional_horizon(horizon: bool) -> None:
    area = WorkingArea(Crop(3, 7, 16, 8, 24, 20), 3)
    mask = np.zeros((2, 32, 72), dtype=np.uint8)
    finish = (0.0, horizon, 1.25, 0.73, 0.55)
    full = _finish(mask, area=area, control="CPU-BASE", pad=6, ss=2, sigma=1, finish=finish)
    early = _finish(mask, area=area, control="EARLY-AREA", pad=6, ss=2, sigma=1, finish=finish)
    assert np.array_equal(early, full[:, 7:15, 3:19])
    if horizon:
        assert np.any((early[:, :, :, 3] > 0) & (early[:, :, :, 3] < 255))
    else:
        assert not np.any(early)


def test_real_recursive_boundary_difference_is_not_fake_equivalence() -> None:
    crop = Crop(0, 12, 24, 8, 24, 32)
    area = WorkingArea(crop, 6)
    mask = np.random.default_rng(1729).integers(0, 256, size=(3, 48, 40), dtype=np.uint8)
    finish = (0.33, False, 1.0, 1.0, 0.5)
    full = _finish(mask, area=area, control="CPU-BASE", pad=8, ss=1, sigma=2, finish=finish)
    early = _finish(mask, area=area, control="EARLY-AREA", pad=8, ss=1, sigma=2, finish=finish)
    metrics = [
        difference_metrics(a.tobytes(), b.tobytes(), crop=crop)
        for a, b in zip(full, early, strict=True)
    ]
    assert max(m["inside_alpha_max_error"] for m in metrics) > 0
    assert all(m["outside_crop_alpha_sum"] > 0 for m in metrics)
    assert "recursive blur boundaries" in area.record(8, 2, "EARLY-AREA")["intentional_differences"]


def test_tiny_original_audio_all_controls_and_refusal(tmp_path: Path) -> None:
    source = tmp_path / "original.wav"
    rate = 24000
    samples = [int(10000 * math.sin(2 * math.pi * 330 * i / rate)) for i in range(6000)]
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 2, rate, len(samples), "NONE", "not compressed"))
        stream.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    area = WorkingArea(Crop(100, 60, 1200, 160, 1400, 280), 48)
    results = []
    reference = tmp_path / "validation-only-full-canvas.rgba"
    for control in ("CPU-BASE", "CROP-OUT", "EARLY-AREA"):
        result = render_working_area(
            source=source,
            start=0.05,
            duration=0.05,
            output=tmp_path / control / "out.mov",
            area=area,
            control=control,
            validation_reference_rgba=reference if reference.exists() else None,
        )
        assert result["status"] == "SUCCEEDED"
        assert result["bounds"]["frames"] == result["validation"]["frames"] == 3
        assert result["bounds"]["effective_start"] == 0.05
        assert result["analysis"]["encode_workers"] == 1
        assert result["analysis_cache"] == "disabled"
        assert result["validation"]["alpha_max"] > 0
        assert result["validation"]["alpha_min"] == 0
        assert result["production_promotion"] is False
        commands = [
            json.loads(line)
            for line in (tmp_path / control / "commands.jsonl").read_text().splitlines()
        ]
        enc = next(
            c for c in commands if c.get("phase") == "compact-area-production-raster-encode"
        )["argv"]
        assert enc[enc.index("-s") + 1] == "3000x380"  # full original gray mask, NOT compact input
        if control == "CPU-BASE":
            assert result["validation"]["comparison_available"] is False
            assert result["validation"]["alpha_union_mae"] is None
            decoded = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    "-i",
                    result["output"],
                    "-pix_fmt",
                    "rgba",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            assert not decoded.stderr
            reference.write_bytes(decoded.stdout)
        else:
            assert result["validation"]["comparison_available"] is True
            assert result["validation"]["union_pixels"] > 0
        results.append(result)
    assert len({r["original_raster_sha256"] for r in results}) == 1
    assert len({json.dumps(r["effective_preset"], sort_keys=True) for r in results}) == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    refused = tmp_path / "refused" / "out.mov"
    with pytest.raises(ValueError, match="margin"):
        render_working_area(
            source=source,
            start=0,
            duration=0.05,
            output=refused,
            area=WorkingArea(area.crop, 1),
            control="EARLY-AREA",
        )
    assert not refused.parent.exists()
    with pytest.raises(ValueError, match="fresh"):
        render_working_area(
            source=source,
            start=0,
            duration=0.05,
            output=tmp_path / "CPU-BASE" / "again.mov",
            area=area,
            control="CPU-BASE",
        )
