"""Strict streaming software validation and separately timed viewing artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from typing import Any

from ewp_waveform.ffmpeg.experiments import (
    frame_metrics,
    inspect_view,
    record_command,
    run_captured,
    viewing_argv,
)


def decode_argv(
    ffmpeg: str,
    path: Path,
    fmt: str = "rgba",
    *,
    frames: int | None = None,
) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-err_detect",
        "explode",
        "-hwaccel",
        "none",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "rawvideo",
        "-pix_fmt",
        fmt,
        *(["-frames:v", str(frames)] if frames is not None else []),
        "-f",
        "rawvideo",
        "pipe:1",
    ]


@contextmanager
def decoded(
    ffmpeg: str,
    path: Path,
    log: Path,
    size: int,
    fmt: str = "rgba",
    *,
    frames: int | None = None,
) -> Iterator[Iterator[bytes]]:
    argv = decode_argv(ffmpeg, path, fmt, frames=frames)
    record_command(
        log,
        argv,
        phase=(
            "strict-reference-prefix-software-decode"
            if frames is not None
            else "strict-complete-software-decode"
        ),
    )
    # Diagnostics are retained on disk, avoiding pipe deadlock and unbounded capture.
    errors = log.parent / (path.name + "." + fmt + ".decode.stderr")
    with errors.open("ab") as err:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        stdout = proc.stdout

        def blocks() -> Iterator[bytes]:
            while True:
                block = bytearray()
                while len(block) < size:
                    part = stdout.read(size - len(block))
                    if not part:
                        break
                    block.extend(part)
                if not block:
                    return
                if len(block) != size:
                    raise ValueError("short decoded frame")
                yield bytes(block)

        try:
            yield blocks()
            if proc.wait(timeout=60) or errors.stat().st_size:
                raise ValueError("strict complete decode failed/diagnostics")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()


def check_grid(
    data: dict[str, Any],
    *,
    width: int,
    height: int,
    frames: int,
    fps: str = "60/1",
    codec: str = "prores",
) -> dict[str, Any]:
    streams = data["streams"]
    if len(streams) != 1:
        raise ValueError("exactly one video stream required")
    info, grid = streams[0], data["frames"]
    tb, rate = Fraction(info["time_base"]), Fraction(fps)
    if (
        tb <= 0
        or tb >= 1 / rate
        or (info["width"], info["height"]) != (width, height)
        or info["codec_name"] != codec
        or Fraction(info["avg_frame_rate"]) != rate
        or len(grid) != frames
    ):
        raise ValueError("codec/geometry/frame count/FPS/timebase mismatch")
    if codec == "prores" and (
        info.get("profile") != "4444" or not info.get("pix_fmt", "").startswith("yuva444p")
    ):
        raise ValueError("ProRes4444 alpha layout required")
    if codec == "ffv1" and info.get("pix_fmt") not in ("bgra", "rgba", "gbrap", "gbrap16le"):
        raise ValueError("lossless RGB-alpha layout required")
    errors = [
        abs(Fraction(f["best_effort_timestamp"]) * tb - Fraction(i) / rate)
        for i, f in enumerate(grid)
    ]
    if any(error > tb / 2 for error in errors):
        raise ValueError("nonzero origin, dropped/duplicated/reordered PTS")
    # Matroska uses a millisecond time base; nearest CFR grid is intentional.
    return {
        "stream": info,
        "frames": frames,
        "fps": fps,
        "time_base": str(tb),
        "max_pts_error_seconds": str(max(errors, default=Fraction(0))),
        "frame_grid_seconds": str(Fraction(frames) / rate),
    }


def inspect(
    ffmpeg: str,
    ffprobe: str,
    path: Path,
    *,
    width: int,
    height: int,
    frames: int,
    log: Path,
    codec: str = "prores",
    reference: Path | None = None,
    lossless: bool = False,
    reference_prefix_frames: int | None = None,
) -> dict[str, Any]:
    if reference_prefix_frames is not None and (
        type(reference_prefix_frames) is not int
        or reference_prefix_frames != frames
        or frames <= 0
        or reference is None
    ):
        raise ValueError("explicit reference prefix must match positive output frame count")
    start = time.perf_counter()
    argv = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,profile,pix_fmt,width,height,avg_frame_rate,time_base:"
        "frame=best_effort_timestamp",
        "-of",
        "json",
        str(path),
    ]
    result = run_captured(argv, log, phase="complete-frame-metadata")
    if result.stderr.strip():
        raise ValueError("probe diagnostics")
    out = check_grid(
        json.loads(result.stdout), width=width, height=height, frames=frames, codec=codec
    )
    digest, alpha_digest = hashlib.sha256(), hashlib.sha256()
    minimum, maximum, count = 255, 0, 0
    metrics: dict[str, int] = {}
    temporal = 0
    previous: bytes | None = None

    def consume(blocks: Iterator[bytes], originals: Iterator[bytes] | None) -> None:
        nonlocal minimum, maximum, count, previous, temporal
        for block in blocks:
            digest.update(block)
            alpha = block[3::4]
            alpha_digest.update(alpha)
            minimum, maximum = min(minimum, min(alpha)), max(maximum, max(alpha))
            if previous is not None:
                # Integral temporal alpha delta, not an appearance threshold.
                import numpy as np

                temporal += int(
                    abs(
                        np.frombuffer(alpha, dtype=np.uint8).astype(np.int16)
                        - np.frombuffer(previous, dtype=np.uint8)
                    ).sum()
                )
            previous = alpha
            count += 1
            if originals is not None:
                original = next(originals, None)
                if original is None:
                    raise ValueError("reference ended early")
                if lossless and original != block:
                    raise ValueError("lossless shared-buffer RGBA mismatch (includes hidden RGB)")
                for key, value in frame_metrics(original, block, width, height).items():
                    metrics[key] = metrics.get(key, 0) + value
        if originals is not None and next(originals, None) is not None:
            raise ValueError("reference has extra frames")

    with decoded(ffmpeg, path, log, width * height * 4) as blocks:
        if reference is not None:
            with decoded(
                ffmpeg,
                reference,
                log,
                width * height * 4,
                frames=reference_prefix_frames,
            ) as originals:
                consume(blocks, originals)
        else:
            consume(blocks, None)
    if count != frames or minimum != 0 or maximum == 0:
        raise ValueError("content alpha or decoded frame count invalid")
    return {
        **out,
        "passed": True,
        "decoded_rgba_sha256": digest.hexdigest(),
        "decoded_alpha_sha256": alpha_digest.hexdigest(),
        "alpha_min": minimum,
        "alpha_max": maximum,
        "alpha_association_contract": "straight",
        "lossless_against_preencode": lossless and reference is not None,
        "reference_prefix_frames": reference_prefix_frames,
        "edge_halo_composite_integer_metrics": metrics,
        "temporal_alpha_absolute_delta_sum": temporal,
        "validation_seconds": time.perf_counter() - start,
        "visual": "PENDING",
        "studio": "PENDING",
    }


def view_argv(
    ffmpeg: str,
    source: Path,
    output: Path,
    *,
    width: int,
    height: int,
    frames: int,
    background: str,
) -> list[str]:
    if background != "checker":
        argv = viewing_argv(
            ffmpeg,
            source,
            output,
            width=width,
            height=height,
            frames=frames,
            fps="60/1",
            background=background,
        )
        # Native Matroska timestamps are nearest-millisecond representations of
        # the validated CFR grid. Canonicalize each frame's timestamp, not its
        # content or count, before framesync; otherwise shortest can drop the
        # final foreground frame when 83ms precedes the background's 5/60s tick.
        index = argv.index("-filter_complex") + 1
        graph = argv[index]
        if graph.count("[bg][0:v]") != 1:
            raise ValueError("unknown straight-alpha viewing boundary")
        argv[index] = "[0:v]settb=1/60,setpts=N[fg];" + graph.replace("[bg][0:v]", "[bg][fg]")
        return argv
    graph = (
        f"nullsrc=s={width}x{height}:r=60,format=rgba,"
        "geq=r='if(mod(floor(X/16)+floor(Y/16),2),224,48)':"
        "g='if(mod(floor(X/16)+floor(Y/16),2),224,48)':"
        "b='if(mod(floor(X/16)+floor(Y/16),2),224,48)':a=255[bg];"
        "[0:v]settb=1/60,setpts=N,format=rgba[fg];"
        "[bg][fg]overlay=alpha=straight:format=auto:shortest=1,format=yuv420p[v]"
    )
    return [
        ffmpeg,
        "-nostdin",
        "-n",
        "-v",
        "error",
        "-xerror",
        "-i",
        str(source),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-an",
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]


def make_views(
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    output: Path,
    *,
    width: int,
    height: int,
    frames: int,
    log: Path,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if source.suffix == ".mkv":
        proxy = output / "comparison-PROXY.mov"
        t = time.perf_counter()
        argv = viewing_argv(
            ffmpeg,
            source,
            proxy,
            width=width,
            height=height,
            frames=frames,
            fps="60/1",
            background="#081018",
            proxy=True,
        )
        run_captured(argv, log, phase="comparison-proxy")
        cost = time.perf_counter() - t
        valid = inspect(ffmpeg, ffprobe, proxy, width=width, height=height, frames=frames, log=log)
        artifacts.append(
            {
                "path": str(proxy),
                "role": "COMPARISON_PROXY_NOT_NATIVE_FFV1",
                "generation_seconds": cost,
                "validation": valid,
            }
        )
    else:
        artifacts.append({"path": str(source), "role": "COMPARISON_MOV_SAME_MASTER"})
    for name, bg in (("dark", "#081018"), ("light", "#F0F0F0"), ("checker", "checker")):
        path = output / (name + "-OPAQUE.mp4")
        t = time.perf_counter()
        run_captured(
            view_argv(
                ffmpeg, source, path, width=width, height=height, frames=frames, background=bg
            ),
            log,
            phase="view-" + name,
        )
        cost = time.perf_counter() - t
        valid = inspect_view(
            ffmpeg,
            ffprobe,
            path,
            width=width,
            height=height,
            frames=frames,
            fps="60/1",
            command_log=log,
        )
        artifacts.append(
            {
                "path": str(path),
                "role": "OPAQUE_VIEW_" + name.upper(),
                "generation_seconds": cost,
                "validation": valid,
            }
        )
    return artifacts
