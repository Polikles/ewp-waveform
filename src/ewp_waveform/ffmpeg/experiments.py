"""Explicit, CPU-first experiment adapters. No default renderer selection changes.

Command construction, finishing, codec negotiation and media inspection stay here.
A parent experiment process owns deadlines/process trees and disk admission.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from ewp_waveform.ffmpeg.encode import _glow_crop_graph
from ewp_waveform.ffmpeg.process import run_argv_stdin

CPU_ADAPTERS = ("CPU-BASE", "CROP-OUT", "PRORES-Q4", "ENC-FFV1")
GPU_ADAPTERS = ("GPU-TRANSFER", "GPU-BLUR", "GPU-PRORES", "GPU-FFV1")


@dataclass(frozen=True)
class Crop:
    """Frozen final-pixel rectangle, not a replacement virtual canvas."""

    x: int
    y: int
    width: int
    height: int
    canvas_width: int
    canvas_height: int

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(type(v) is not int for v in values.values()):
            raise ValueError("crop coordinates must be integers")
        if (
            min(self.x, self.y) < 0
            or min(self.width, self.height) < 2
            or self.x + self.width > self.canvas_width
            or self.y + self.height > self.canvas_height
        ):
            raise ValueError("crop outside original canvas")
        if self.width % 2 or self.height % 2:
            raise ValueError("even crop dimensions required")

    def record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "horizon_original_y": self.canvas_height // 2 + 0.5,
            "horizon_output_y": self.canvas_height // 2 + 0.5 - self.y,
            "horizon_coordinate_convention": "pixel-edge center; production row height//2",
            "reflection_split_row": self.canvas_height // 2,
            "alpha_association": "straight",
            "frozen_for_whole_clip": True,
        }


@dataclass(frozen=True)
class EncodeExperiment:
    candidate: str
    crop: Crop | None = None
    command_log: Path | None = None

    def __post_init__(self) -> None:
        if self.candidate not in CPU_ADAPTERS:
            raise ValueError("unsupported experiment adapter (no CPU fallback)")
        if (self.candidate == "CROP-OUT") != (self.crop is not None):
            raise ValueError("CROP-OUT requires exactly one frozen crop")


def record_command(path: Path | None, argv: list[str], *, phase: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": phase, "argv": argv}, sort_keys=True) + "\n")
            stream.flush()


def experiment_argv(argv: list[str], spec: EncodeExperiment) -> list[str]:
    """Transform only a single-output production ProRes command; fail closed."""
    out = list(argv)
    if out.count("-c:v") != 1 or out[out.index("-c:v") + 1] != "prores_ks":
        raise ValueError("experiment requires single-output prores_ks")
    if spec.candidate == "PRORES-Q4":
        out[-1:-1] = ["-qscale:v", "4"]
    elif spec.candidate == "CROP-OUT":
        assert spec.crop is not None
        c = spec.crop
        index = out.index("-filter_complex") + 1
        graph = out[index]
        if graph.count("[vout]") != 1 or not graph.endswith("[vout]"):
            raise ValueError("unrecognized production finishing boundary")
        out[index] = graph[:-6] + f",crop={c.width}:{c.height}:{c.x}:{c.y}:exact=1[vout]"
    elif spec.candidate == "ENC-FFV1":
        raise ValueError("FFV1 is fixture-only until native Studio prerequisite passes")
    record_command(spec.command_log, out, phase="application-encode")
    return out


def codec_settings(candidate: str, crop: Crop) -> dict[str, Any]:
    if candidate not in CPU_ADAPTERS:
        raise ValueError("adapter is not implemented; no fallback")
    return {
        "export_bounds": crop.record() if candidate == "CROP-OUT" else "original-canvas",
        "encoder": "ffv1" if candidate == "ENC-FFV1" else "prores_ks",
        "pixel_layout": "bgra" if candidate == "ENC-FFV1" else "yuva444p10le",
        "container": "matroska" if candidate == "ENC-FFV1" else "mov",
        "rate_control": "qscale-4" if candidate == "PRORES-Q4" else "existing-default",
    }


def check_effective_diff(
    control: dict[str, Any], candidate: dict[str, Any], name: str
) -> dict[str, Any]:
    allowed = {
        "CPU-BASE": set(),
        "CROP-OUT": {"export_bounds"},
        "PRORES-Q4": {"rate_control"},
        "ENC-FFV1": {"encoder", "pixel_layout", "container"},
    }[name]
    changed = {
        key for key in control.keys() | candidate.keys() if control.get(key) != candidate.get(key)
    }
    if changed != allowed:
        raise ValueError(f"effective setting differences {sorted(changed)} != {sorted(allowed)}")
    return {
        key: {"control": control.get(key), "candidate": candidate.get(key)}
        for key in sorted(changed)
    }


def codec_argv(
    ffmpeg: str,
    fixture: Path,
    output: Path,
    *,
    width: int,
    height: int,
    fps: str,
    candidate: str,
    crop: Crop,
    threads: int = 0,
) -> list[str]:
    settings = codec_settings(candidate, crop)
    graph = "[0:v]format=rgba[vout]"
    argv = [
        ffmpeg,
        "-nostdin",
        "-n",
        "-v",
        "error",
        "-xerror",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgba",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        fps,
        "-i",
        str(fixture),
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-an",
        "-fps_mode",
        "cfr",
        "-r",
        fps,
    ]
    if threads > 0:
        argv += ["-threads", str(threads)]
    if candidate == "ENC-FFV1":
        return [
            *argv,
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "bgra",
            "-f",
            "matroska",
            str(output),
        ]
    argv += [
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        str(settings["pixel_layout"]),
        str(output),
    ]
    return experiment_argv(
        argv, EncodeExperiment(candidate, crop if candidate == "CROP-OUT" else None)
    )


def check_command_diff(control: list[str], candidate: list[str], name: str) -> None:
    """Enforce effective argv differences, not merely manifest intent.

    Input/output identities may differ between isolated attempts. Every other
    token must equal the control plus the adapter's declared transformation.
    """
    expected = list(control)
    expected[expected.index("-i") + 1] = candidate[candidate.index("-i") + 1]
    expected[-1] = candidate[-1]
    if name == "ENC-FFV1":
        index = expected.index("-c:v")
        expected[index:] = [
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "bgra",
            "-f",
            "matroska",
            candidate[-1],
        ]
    else:
        crop = None
        if name == "CROP-OUT":
            graph = candidate[candidate.index("-filter_complex") + 1]
            suffix = graph.split(",crop=")[-1].removesuffix(":exact=1[vout]")
            w, h, x, y = map(int, suffix.split(":"))
            # The settings validator separately authenticates original canvas.
            crop = Crop(x, y, w, h, x + w, y + h)
        expected = experiment_argv(expected, EncodeExperiment(name, crop))
    if expected != candidate:
        raise ValueError("undeclared effective FFmpeg argv change")


def finish_fixture(
    frames: Iterable[bytes], destination: Path, *, ffmpeg: str, command_log: Path, **kwargs: Any
) -> None:
    """Production finish graph to canonical RGBA8, before any ProRes encode."""
    width, height = kwargs["width"], kwargs["height"]
    pad, ss = kwargs.get("overscan", 0), kwargs.get("supersample", 1)
    graph = _glow_crop_graph(
        kwargs["glow"],
        width,
        height,
        pad,
        ss,
        kwargs.get("shutter_px", 0.0),
        kwargs.get("shutter_mix", 0.25),
        pix_fmt=kwargs.get("pix_fmt", "rgba"),
        color=kwargs.get("color"),
        fps=kwargs["fps"],
        n_frames=kwargs.get("n_frames"),
        ribbon_finish=kwargs.get("ribbon_finish"),
    )
    argv = [
        ffmpeg,
        "-n",
        "-v",
        "error",
        "-xerror",
        "-f",
        "rawvideo",
        "-pix_fmt",
        kwargs.get("pix_fmt", "rgba"),
        "-s",
        f"{(width + 2 * pad) * ss}x{height + 2 * pad}",
        "-r",
        str(kwargs["fps"]),
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
        str(destination),
    ]
    record_command(command_log, argv, phase="fixture-production-finish")
    result = run_argv_stdin(argv, frames)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr.decode(errors="replace"))


def freeze_crop(raw: Path, *, width: int, height: int, frames: int, margin: int) -> Crop:
    """Union every nonzero alpha sample, including halo; align only outwards."""
    if type(margin) is not int or margin < 0:
        raise ValueError("margin must be a nonnegative integer")
    left, top, right, bottom = width, height, -1, -1
    size = width * height * 4
    with raw.open("rb") as stream:
        for _ in range(frames):
            frame = stream.read(size)
            if len(frame) != size:
                raise ValueError("incomplete pre-encode fixture")
            alpha = np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 4)[:, :, 3]
            ys, xs = np.nonzero(alpha)
            if xs.size:
                left, right = min(left, int(xs.min())), max(right, int(xs.max()))
                top, bottom = min(top, int(ys.min())), max(bottom, int(ys.max()))
        if stream.read(1):
            raise ValueError("extra fixture bytes")
    if right < 0:
        return Crop(0, 0, width, height, width, height)
    x, y = max(0, left - margin) // 2 * 2, max(0, top - margin) // 2 * 2
    end_x = min(width, ((right + 1 + margin + 1) // 2) * 2)
    end_y = min(height, ((bottom + 1 + margin + 1) // 2) * 2)
    return Crop(x, y, end_x - x, end_y - y, width, height)


def inspect_master(
    ffmpeg: str,
    ffprobe: str,
    path: Path,
    *,
    width: int,
    height: int,
    fps: str,
    frames: int,
    candidate: str,
    command_log: Path,
    reference: Path | None = None,
    crop: Crop | None = None,
) -> dict[str, Any]:
    """Complete strict decode, exact rational grid and streaming padded comparison."""
    started = time.perf_counter()
    probe = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_streams",
        "-show_format",
        "-show_frames",
        "-show_entries",
        "stream=width,height,codec_name,profile,pix_fmt,avg_frame_rate,time_base:frame=pts:format=duration",
        "-of",
        "json",
        str(path),
    ]
    record_command(command_log, probe, phase="validation-probe")
    result = run_captured(probe, command_log, phase="validation-probe-result", timeout=60)
    if result.stderr.strip():
        raise ValueError("probe diagnostics: " + result.stderr.decode(errors="replace"))
    data = json.loads(result.stdout)
    info = data["streams"][0]
    grid = data["frames"]
    if (info["width"], info["height"]) != (width, height):
        raise ValueError("wrong output dimensions")
    if Fraction(info["avg_frame_rate"]) != Fraction(fps) or len(grid) != frames:
        raise ValueError("wrong output cadence/count")
    timebase = Fraction(info["time_base"])
    pts_errors = [
        abs(Fraction(item["pts"]) * timebase - Fraction(i) / Fraction(fps))
        for i, item in enumerate(grid)
    ]
    # Matroska's default millisecond timebase cannot represent 30/60fps exactly.
    # Accept only nearest-tick rational quantization, never a missing/shifted frame.
    if (
        timebase <= 0
        or timebase >= 1 / Fraction(fps)
        or any(error > timebase / 2 for error in pts_errors)
    ):
        raise ValueError("wrong rational timestamp grid")
    observed_duration = Fraction(data["format"]["duration"])
    expected_duration = Fraction(frames) / Fraction(fps)
    if observed_duration <= 0 or abs(observed_duration - expected_duration) > timebase + Fraction(
        1, 1000000
    ):
        raise ValueError("wrong observed container duration")
    if candidate == "ENC-FFV1":
        valid = info["codec_name"] == "ffv1" and info["pix_fmt"] in {"bgra", "gbrap"}
    else:
        valid = (
            info["codec_name"] == "prores"
            and info["profile"] in {"4444", "XQ"}
            and info["pix_fmt"].startswith("yuva444p")
        )
    if not valid:
        raise ValueError("wrong encoder/profile or alpha layout")
    argv = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-err_detect",
        "explode",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-pix_fmt",
        "rgba",
        "-f",
        "rawvideo",
        "-",
    ]
    record_command(command_log, argv, phase="validation-complete-decode")
    digest = hashlib.sha256()
    alpha_min, alpha_max, count = 255, 0, 0
    union_count = alpha_error = rgb_error = edge_error = halo_error = edge_n = halo_n = 0
    composites = {"081018": 0, "F0F0F0": 0, "checkerboard": 0}
    ref = reference.open("rb") if reference else None
    # stderr on a file prevents deadlock; this is text, never media.
    with command_log.with_suffix(".decode-stderr.txt").open("wb") as errors:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors)
        assert proc.stdout is not None
        try:
            while True:
                size = width * height * 4
                block = bytearray()
                while len(block) < size:
                    part = proc.stdout.read(size - len(block))
                    if not part:
                        break
                    block.extend(part)
                if not block:
                    break
                if len(block) != size:
                    raise ValueError("short decoded frame")
                digest.update(block)
                decoded = np.frombuffer(block, dtype=np.uint8).reshape(height, width, 4)
                alpha = decoded[:, :, 3]
                alpha_min = min(alpha_min, int(alpha.min()))
                alpha_max = max(alpha_max, int(alpha.max()))
                count += 1
                if ref:
                    cw = crop.canvas_width if crop else width
                    ch = crop.canvas_height if crop else height
                    original = ref.read(cw * ch * 4)
                    if len(original) != cw * ch * 4:
                        raise ValueError("short canonical reference")
                    padded = np.zeros((ch, cw, 4), dtype=np.uint8)
                    x, y = (crop.x, crop.y) if crop else (0, 0)
                    padded[y : y + height, x : x + width] = decoded
                    metrics = frame_metrics(original, padded.tobytes(), cw, ch)
                    union_count += metrics["union_count"]
                    alpha_error += metrics["alpha_error"]
                    rgb_error += metrics["rgb_error"]
                    edge_error += metrics["edge_error"]
                    edge_n += metrics["edge_n"]
                    halo_error += metrics["halo_error"]
                    halo_n += metrics["halo_n"]
                    for key in composites:
                        composites[key] += metrics[key]
            if proc.wait(timeout=60):
                raise ValueError("complete strict decode failed")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            if ref:
                ref.close()
    if command_log.with_suffix(".decode-stderr.txt").stat().st_size or count != frames:
        raise ValueError("decode diagnostics/count mismatch")
    if alpha_min == alpha_max or alpha_min != 0 or alpha_max == 0:
        raise ValueError("content alpha missing (transparent and active samples required)")
    return {
        "passed": True,
        "frames": count,
        "duration_seconds": float(observed_duration),
        "expected_frame_grid_seconds": str(expected_duration),
        "pts_timebase": str(timebase),
        "maximum_pts_quantization_error": str(max(pts_errors, default=Fraction(0))),
        "fps": fps,
        "stream": info,
        "decoded_rgba_sha256": digest.hexdigest(),
        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
        "alpha_association_contract": "straight",
        "union_pixels": union_count,
        "alpha_union_mae": alpha_error / max(1, union_count),
        "rgb_union_mae": rgb_error / max(1, 3 * union_count),
        "edge_alpha_mae": edge_error / max(1, edge_n),
        "halo_alpha_mae": halo_error / max(1, halo_n),
        "composite_union_mae": {
            k: v / max(1, 3 * union_count * 255) for k, v in composites.items()
        },
        "validation_seconds": time.perf_counter() - started,
        "visual_review": "PENDING",
        "nle_review": "PENDING",
    }


def gpu_probe_argv(ffmpeg: str, adapter: str, output: Path) -> list[str]:
    """Separate future WSL envelope only; never substitute a CPU implementation."""
    if adapter not in GPU_ADAPTERS:
        raise ValueError("unknown GPU adapter")
    graph = "format=rgba,hwupload"
    if adapter == "GPU-BLUR":
        graph += ",gblur_vulkan=sigma=4"
    if adapter in {"GPU-TRANSFER", "GPU-BLUR"}:
        graph += ",hwdownload,format=rgba"
        codec = ["-c:v", "ffv1", "-pix_fmt", "bgra", "-f", "matroska"]
    elif adapter == "GPU-PRORES":
        codec = ["-c:v", "prores_ks_vulkan", "-profile:v", "4444", "-f", "mov"]
    else:
        codec = ["-c:v", "ffv1_vulkan", "-f", "matroska"]
    return [
        ffmpeg,
        "-nostdin",
        "-n",
        "-v",
        "error",
        "-xerror",
        "-init_hw_device",
        "vulkan=vk",
        "-filter_hw_device",
        "vk",
        "-f",
        "lavfi",
        "-i",
        "color=c=black@0:s=16x16:r=30,format=rgba,drawbox=x=4:y=4:w=8:h=8:color=white@0.5:t=fill:replace=1",
        "-vf",
        graph,
        "-frames:v",
        "2",
        *codec,
        str(output),
    ]


def frame_metrics(original: bytes, padded: bytes, width: int, height: int) -> dict[str, int]:
    """Exact integer scalar semantics, vectorized per frame, bounded memory.

    int32 covers products/differences; int64 reductions avoid overflow. Never
    include fully transparent RGB in ROI or round compositing before summation.
    """
    if original == padded:
        # Byte equality proves every error/composite term zero, including hidden
        # RGB. Retain the exact original ROI denominators without full int32 RGB
        # conversions, checker allocation or three redundant composite passes.
        aa = np.frombuffer(original, dtype=np.uint8).reshape(height, width, 4)[:, :, 3]
        return {
            "union_count": int(np.count_nonzero(aa)),
            "alpha_error": 0,
            "rgb_error": 0,
            "edge_error": 0,
            "edge_n": int(np.count_nonzero((aa > 0) & (aa < 255))),
            "halo_error": 0,
            "halo_n": int(np.count_nonzero((aa > 0) & (aa < 32))),
            "081018": 0,
            "F0F0F0": 0,
            "checkerboard": 0,
        }
    a = np.frombuffer(original, dtype=np.uint8).reshape(height, width, 4).astype(np.int32)
    b = np.frombuffer(padded, dtype=np.uint8).reshape(height, width, 4).astype(np.int32)
    aa, ba = a[:, :, 3], b[:, :, 3]
    union = (aa != 0) | (ba != 0)
    delta = np.abs(aa - ba)
    edge, halo = (aa > 0) & (aa < 255), (aa > 0) & (aa < 32)

    def total(values: Any) -> int:
        return int(np.sum(values, dtype=np.int64))

    out = {
        "union_count": int(np.count_nonzero(union)),
        "alpha_error": total(delta[union]),
        "rgb_error": total(np.abs(a[:, :, :3] - b[:, :, :3])[union]),
        "edge_error": total(delta[edge]),
        "edge_n": int(np.count_nonzero(edge)),
        "halo_error": total(delta[halo]),
        "halo_n": int(np.count_nonzero(halo)),
    }
    yy, xx = np.indices((height, width))
    checker = np.where((xx // 16 + yy // 16) % 2, 224, 48)[:, :, None]
    foreground = a[:, :, :3] * aa[:, :, None] - b[:, :, :3] * ba[:, :, None]
    for key, bg in (
        ("081018", np.array([8, 16, 24])),
        ("F0F0F0", np.array([240, 240, 240])),
        ("checkerboard", checker),
    ):
        out[key] = total(np.abs(foreground + bg * (ba - aa)[:, :, None])[union])
    return out


def run_captured(
    argv: list[str], log: Path, *, phase: str, timeout: int | None = None
) -> subprocess.CompletedProcess[bytes]:
    record_command(log, argv, phase=phase)
    try:
        result = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:

        def diagnostic(value: bytes | str | None) -> str | None:
            return value.decode(errors="replace") if isinstance(value, bytes) else value

        with log.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "phase": phase + "-outcome",
                        "argv": argv,
                        "status": "TIMEOUT",
                        "returncode": None,
                        "timeout_seconds": exc.timeout,
                        "stdout": diagnostic(exc.stdout),
                        "stderr": diagnostic(exc.stderr),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            stream.flush()
        raise
    with log.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "phase": phase + "-outcome",
                    "argv": argv,
                    "returncode": result.returncode,
                    "stdout": result.stdout.decode(errors="replace"),
                    "stderr": result.stderr.decode(errors="replace"),
                },
                sort_keys=True,
            )
            + "\n"
        )
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, argv, result.stdout, result.stderr)
    return result


def viewing_argv(
    ffmpeg: str,
    source: Path,
    output: Path,
    *,
    width: int,
    height: int,
    fps: str,
    frames: int,
    background: str,
    crop: Crop | None = None,
    proxy: bool = False,
) -> list[str]:
    """Post-timing derivative; explicit straight-alpha overlay, no audio shift."""
    import re

    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise ValueError("literal RGB viewing background required")
    prefix = [ffmpeg, "-nostdin", "-n", "-v", "error", "-xerror", "-i", str(source)]
    if proxy:
        return [
            *prefix,
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4444",
            "-pix_fmt",
            "yuva444p10le",
            "-frames:v",
            str(frames),
            str(output),
        ]
    x, y = (crop.x, crop.y) if crop else (0, 0)
    graph = (
        f"color=c=0x{background[1:]}:s={width}x{height}:r={fps},format=rgba[bg];"
        f"[bg][0:v]overlay=x={x}:y={y}:alpha=straight:shortest=1,format=yuv420p[v]"
    )
    return [
        *prefix,
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-frames:v",
        str(frames),
        "-movflags",
        "+faststart",
        str(output),
    ]


def inspect_view(
    ffmpeg: str,
    ffprobe: str,
    path: Path,
    *,
    width: int,
    height: int,
    fps: str,
    frames: int,
    command_log: Path,
) -> dict[str, Any]:
    """Validate H.264 view cadence, duration, dimensions and complete decode."""
    result = run_captured(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-show_frames",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        command_log,
        phase="view-probe",
        timeout=60,
    )
    data = json.loads(result.stdout)
    info, grid = data["streams"][0], data["frames"]
    tb = Fraction(info["time_base"])
    if (
        (info["width"], info["height"]) != (width, height)
        or info["codec_name"] != "h264"
        or info["pix_fmt"] != "yuv420p"
        or Fraction(info["avg_frame_rate"]) != Fraction(fps)
        or len(grid) != frames
        or tb <= 0
        or tb >= 1 / Fraction(fps)
        or any(
            abs(Fraction(f["best_effort_timestamp"]) * tb - Fraction(i) / Fraction(fps)) > tb / 2
            for i, f in enumerate(grid)
        )
        or abs(Fraction(data["format"]["duration"]) - Fraction(frames) / Fraction(fps))
        > tb + Fraction(1, 1000000)
    ):
        raise ValueError("invalid viewing MP4 stream/grid")
    decoded = run_captured(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ],
        command_log,
        phase="view-complete-decode",
        timeout=60,
    )
    if result.stderr.strip() or decoded.stderr.strip():
        raise ValueError("view validation diagnostics")
    return {
        "passed": True,
        "frames": frames,
        "stream": info,
        "duration_seconds": float(data["format"]["duration"]),
    }
