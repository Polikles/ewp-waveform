"""Encode RGBA frame streams with FFmpeg (glow + ProRes/PNG)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ewp_waveform.ffmpeg.process import require_tool, run_argv_stdin

GLOW_SIGMA = {"none": 0.0, "low": 4.0, "medium": 8.0, "high": 16.0}


class EncodeError(RuntimeError):
    pass


def glow_sigma(level: str, enabled: bool) -> float:
    if not enabled or level == "none":
        return 0.0
    return GLOW_SIGMA.get(level, 8.0)


def shutter_sigma(shutter_px: float) -> float:
    """Horizontal gblur sigma for a shutter length in output pixels. 0 disables."""
    if shutter_px < 0.35:
        return 0.0
    return shutter_px / 2.355


def _glow_crop_graph(
    glow: float,
    width: int,
    height: int,
    overscan: int,
    supersample: int = 1,
    shutter_px: float = 0.0,
    shutter_mix: float = 0.25,
) -> str:
    """Downsample, optional hybrid temporal mix, glow under a sharp-ish base, crop.

    Visible base is ``(1-mix)*sharp + mix*shutter`` so the edge stays crisp.
    Glow is generated from that stabilized mask and composited underneath.
    """
    padded_w = width + 2 * overscan
    padded_h = height + 2 * overscan
    mix = min(max(shutter_mix, 0.0), 1.0)
    sharp_w = 1.0 - mix
    sigma = shutter_sigma(shutter_px)
    use_taa = sigma > 0.0 and mix > 0.0
    scale = f"scale={padded_w}:{padded_h}:flags=area" if supersample > 1 else "format=rgba"
    crop = f",crop={width}:{height}:{overscan}:{overscan}" if overscan > 0 else ""
    if use_taa:
        taa = (
            f"{scale},split=2[sharp][taa];"
            f"[taa]gblur=sigma={sigma:.4f}:sigmaV=0.01:steps=1[taab];"
            f"[sharp][taab]blend=all_expr='A*{sharp_w:.4f}+B*{mix:.4f}'"
            ":shortest=1,format=rgba"
        )
        if glow > 0:
            return (
                f"[0:v]{taa},split=2[base][g];[g]gblur=sigma="
                f"{glow}:steps=3[gb];[gb][base]overlay=format=auto:shortest=1,"
                f"format=rgba{crop}[vout]"
            )
        return f"[0:v]{taa}{crop}[vout]"
    if glow > 0:
        return (
            f"[0:v]{scale},split=2[base][g];[g]gblur=sigma="
            f"{glow}:steps=3[gb];[gb][base]overlay=format=auto:shortest=1,"
            f"format=rgba{crop}[vout]"
        )
    return f"[0:v]{scale}{crop}[vout]"


def encode_rgba_stream(
    frames: Iterable[bytes],
    *,
    width: int,
    height: int,
    fps: float,
    glow: float,
    png_dir: Path | None,
    prores_path: Path | None,
    ffmpeg_threads: int = 0,
    overscan: int = 0,
    supersample: int = 1,
    shutter_px: float = 0.0,
    shutter_mix: float = 0.25,
    png_start_number: int = 1,
) -> None:
    if png_dir is None and prores_path is None:
        msg = "encode_rgba_stream requires png_dir and/or prores_path"
        raise ValueError(msg)
    ffmpeg = require_tool("ffmpeg")
    ss = max(1, int(supersample))
    in_w = (width + 2 * overscan) * ss
    in_h = height + 2 * overscan
    graph = _glow_crop_graph(glow, width, height, overscan, ss, shutter_px, shutter_mix)
    argv: list[str] = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{in_w}x{in_h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-fps_mode",
        "cfr",
        "-r",
        str(fps),
    ]
    if ffmpeg_threads > 0:
        argv.extend(["-threads", str(ffmpeg_threads)])
    png_start = max(1, png_start_number)
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        argv.extend(
            [
                "-start_number",
                str(png_start),
                "-c:v",
                "png",
                str(png_dir / "frame_%06d.png"),
            ]
        )
    if prores_path is not None:
        prores_path.parent.mkdir(parents=True, exist_ok=True)
        if png_dir is not None:
            # Two outputs: filter_complex default maps to first; add a split.
            argv = _dual_output_argv(
                ffmpeg=ffmpeg,
                width=width,
                height=height,
                fps=fps,
                glow=glow,
                png_dir=png_dir,
                prores_path=prores_path,
                ffmpeg_threads=ffmpeg_threads,
                overscan=overscan,
                supersample=ss,
                shutter_px=shutter_px,
                shutter_mix=shutter_mix,
                png_start_number=png_start,
            )
            completed = run_argv_stdin(argv, frames)
            if completed.returncode != 0:
                msg = completed.stderr.decode("utf-8", errors="replace")
                raise EncodeError(msg.strip() or "ffmpeg encode failed")
            return
        argv.extend(
            [
                "-c:v",
                "prores_ks",
                "-profile:v",
                "4444",
                "-pix_fmt",
                "yuva444p10le",
                str(prores_path),
            ]
        )
    completed = run_argv_stdin(argv, frames)
    if completed.returncode != 0:
        msg = completed.stderr.decode("utf-8", errors="replace")
        raise EncodeError(msg.strip() or "ffmpeg encode failed")


def _dual_output_argv(
    *,
    ffmpeg: Path,
    width: int,
    height: int,
    fps: float,
    glow: float,
    png_dir: Path,
    prores_path: Path,
    ffmpeg_threads: int,
    overscan: int = 0,
    supersample: int = 1,
    shutter_px: float = 0.0,
    shutter_mix: float = 0.25,
    png_start_number: int = 1,
) -> list[str]:
    ss = max(1, int(supersample))
    core = _glow_crop_graph(glow, width, height, overscan, ss, shutter_px, shutter_mix)
    graph = core.replace("[vout]", ",split=2[png][mov]", 1)
    in_w = (width + 2 * overscan) * ss
    in_h = height + 2 * overscan
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{in_w}x{in_h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-filter_complex",
        graph,
        "-map",
        "[png]",
        "-start_number",
        str(max(1, png_start_number)),
        "-c:v",
        "png",
        str(png_dir / "frame_%06d.png"),
        "-map",
        "[mov]",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        str(prores_path),
    ]
    if ffmpeg_threads > 0:
        argv[1:1] = ["-threads", str(ffmpeg_threads)]
    return argv
