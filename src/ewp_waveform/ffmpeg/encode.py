"""Encode RGBA frame streams with FFmpeg (glow + ProRes/PNG)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ewp_waveform.ffmpeg.process import require_tool, run_argv, run_argv_stdin

GLOW_SIGMA = {"none": 0.0, "low": 4.0, "medium": 8.0, "high": 16.0}


class EncodeError(RuntimeError):
    pass


def glow_sigma(level: str, enabled: bool) -> float:
    if not enabled or level == "none":
        return 0.0
    return GLOW_SIGMA.get(level, 8.0)


def shutter_box_size(shutter_px: float) -> int:
    """Odd avgblur sizeX for a shutter length in output pixels. 0 disables."""
    if shutter_px < 0.75:
        return 0
    size = max(1, round(shutter_px))
    if size % 2 == 0:
        size += 1
    return max(3, size)


def _glow_crop_graph(
    glow: float,
    width: int,
    height: int,
    overscan: int,
    supersample: int = 1,
    shutter_px: float = 0.0,
) -> str:
    """Area-downsample, optional shutter blur, then glow from that mask, then crop."""
    padded_w = width + 2 * overscan
    padded_h = height + 2 * overscan
    chain: list[str] = []
    if supersample > 1:
        chain.append(f"scale={padded_w}:{padded_h}:flags=area")
    box = shutter_box_size(shutter_px)
    if box >= 3:
        chain.append(f"avgblur=sizeX={box}:sizeY=1")
    pre = ",".join(chain)
    crop = f"crop={width}:{height}:{overscan}:{overscan}"
    if glow > 0:
        head = f"{pre}," if pre else ""
        body = (
            f"{head}split=2[base][g];[g]gblur=sigma="
            f"{glow}:steps=3[gb];[gb][base]overlay=format=auto:shortest=1,format=rgba"
        )
        if overscan > 0:
            return f"[0:v]{body},{crop}[out]"
        return f"[0:v]{body}[out]"
    rest = ["format=rgba"]
    if overscan > 0:
        rest.append(crop)
    if pre:
        return f"[0:v]{pre},{','.join(rest)}[out]"
    return f"[0:v]{','.join(rest)}[out]"


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
) -> None:
    if png_dir is None and prores_path is None:
        msg = "encode_rgba_stream requires png_dir and/or prores_path"
        raise ValueError(msg)
    ffmpeg = require_tool("ffmpeg")
    ss = max(1, int(supersample))
    in_w = (width + 2 * overscan) * ss
    in_h = height + 2 * overscan
    graph = _glow_crop_graph(glow, width, height, overscan, ss, shutter_px)
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
        "[out]",
        "-fps_mode",
        "cfr",
        "-r",
        str(fps),
    ]
    if ffmpeg_threads > 0:
        argv.extend(["-threads", str(ffmpeg_threads)])
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
        argv.extend(["-c:v", "png", str(png_dir / "frame_%06d.png")])
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
) -> list[str]:
    ss = max(1, int(supersample))
    core = _glow_crop_graph(glow, width, height, overscan, ss, shutter_px)
    graph = core.replace("[out]", "split=2[png][mov]", 1)
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


def encode_spectrum_showfreqs(
    source: Path,
    dest: Path,
    *,
    width: int,
    height: int,
    fps: float,
    color: str,
    glow: float,
    ffmpeg_threads: int = 0,
) -> None:
    """Experimental fixed-axis path. Not the product look."""
    ffmpeg = require_tool("ffmpeg")
    hex_color = color.removeprefix("#")
    wave = (
        f"showfreqs=s={width}x{height // 2}:mode=line:fscale=log:ascale=sqrt:"
        f"colors=0x{hex_color}:win_size=2048:averaging=1:rate={fps}"
    )
    alpha = (
        "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='max(r(X,Y)\\,max(g(X,Y)\\,b(X,Y)))'"
    )
    if glow > 0:
        glow_graph = (
            f",split=2[base][g];[g]gblur=sigma={glow}:steps=3[gb];"
            "[gb][base]overlay=format=auto:shortest=1,format=rgba"
        )
    else:
        glow_graph = ""
    graph = f"{wave},{alpha},split=2[top][bot];[bot]vflip[bf];[top][bf]vstack{glow_graph}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        graph,
        "-an",
        "-fps_mode",
        "cfr",
        "-r",
        str(fps),
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        str(dest),
    ]
    if ffmpeg_threads > 0:
        argv.extend(["-threads", str(ffmpeg_threads)])
    completed = run_argv(argv)
    if completed.returncode != 0:
        raise EncodeError(completed.stderr.strip() or "showfreqs encode failed")
