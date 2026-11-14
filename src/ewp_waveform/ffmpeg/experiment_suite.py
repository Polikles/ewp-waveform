"""Explicit WSL finishing/encoding adapters; production defaults are unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ewp_waveform.ffmpeg.ribbon_lut import PreparedRibbonLut


def record_command(path: Path, argv: list[str], *, phase: str) -> None:
    from ewp_waveform.ffmpeg.experiments import record_command as record

    record(path, argv, phase=phase)


PIN = "946fcce07b6dcd0331c8cc609192aeff5e1924f8"
ADAPTERS = ("CPU-CONTROL", "TRANSFER", "BLUR", "PRORES-MATCHED", "PRORES-GPU")


@dataclass(frozen=True)
class SuiteEncoding:
    candidate: str
    command_log: Path
    device: str = "RTX 3090"
    expect_device_regex: str = r"RTX\s*3090"
    crop: None = None
    encoder_threads: int | None = None
    filter_threads: int | None = None
    async_depth: int | None = None
    ribbon_lut: PreparedRibbonLut | None = None

    def __post_init__(self) -> None:
        if self.candidate not in (*ADAPTERS, "FFV1-DIRECT"):
            raise ValueError("unknown suite encoding adapter")
        if self.ribbon_lut is not None and self.candidate not in ("CPU-CONTROL", "FFV1-DIRECT"):
            raise ValueError("LUT finishing is a separate CPU-only experiment")
        for name in ("encoder_threads", "filter_threads"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value <= 32):
                raise ValueError(f"{name} must be an integer in 0..32 or None")
        if self.async_depth is not None and (
            type(self.async_depth) is not int
            or not 1 <= self.async_depth <= 8
            or self.candidate != "PRORES-GPU"
        ):
            raise ValueError("async_depth requires PRORES-GPU and an integer in 1..8")
        if not re.fullmatch(r"[A-Za-z0-9 ._-]+", self.device):
            raise ValueError("device must be a name substring or numeric index")
        re.compile(self.expect_device_regex)

    def identity(self) -> dict[str, Any]:
        return {
            "revision": 1,
            "candidate": self.candidate,
            "device": self.device,
            "expect_device_regex": self.expect_device_regex,
            "blur_sigma": 16,
            "blur_size": 97 if self.candidate == "BLUR" else None,
            "alpha_bits": 16
            if self.candidate in ("PRORES-MATCHED", "PRORES-GPU")
            else "stock-default",
            "loglevel": "verbose",
            "encoder_threads": self.encoder_threads,
            "filter_complex_threads": self.filter_threads,
            "async_depth": (self.async_depth or 1) if self.candidate == "PRORES-GPU" else None,
            "thread_scope": "requested FFmpeg options, not observed runtime thread counts",
            "ribbon_lut": self.ribbon_lut.record() if self.ribbon_lut else None,
        }

    @property
    def gpu(self) -> bool:
        return self.candidate in ("TRANSFER", "BLUR", "PRORES-GPU")


def halo_filter(glow: float, candidate: str | None = None) -> str:
    cpu = f"gblur=sigma={glow}:steps=3"
    if candidate not in ("TRANSFER", "BLUR"):
        return cpu
    if glow != 16:
        raise ValueError("frozen mono Vulkan comparison requires sigma16")
    transfer = "format=gray,hwupload,"
    download = "hwdownload,format=gray"
    if candidate == "TRANSFER":
        return transfer + download + "," + cpu
    return transfer + "gblur_vulkan=sigma=16:sigmaV=16:size=97:sizeV=97:planes=1," + download


def device_args(device: str) -> list[str]:
    # Vulkan name selection is explicit; never silently select device zero.
    return ["-init_hw_device", f"vulkan=vk:{device}", "-filter_hw_device", "vk"]


def selected_device(stderr: str, expected: str) -> str:
    # One parser for qualification and actual service/codec execution. FFmpeg
    # versions emit either "Using device:" or "Device N selected:".
    from ewp_waveform.ffmpeg.backend_qualification import selected_device as parse

    return parse(stderr, expected)


def service_argv(argv: list[str], spec: SuiteEncoding) -> list[str]:
    out = list(argv)
    if (
        out.count("-c:v") != 1
        or out[out.index("-c:v") + 1] != "prores_ks"
        or out.count("-filter_complex") != 1
    ):
        raise ValueError("suite requires single-output production ProRes")
    gi = out.index("-filter_complex") + 1
    graph = out[gi]
    if graph.count("[vout]") != 1 or not graph.endswith("[vout]"):
        raise ValueError("unknown production finishing boundary")
    if spec.candidate in ("PRORES-MATCHED", "PRORES-GPU"):
        graph = graph[:-6] + ",format=yuva444p10le"
        if spec.gpu:
            graph += ",hwupload"
            out[out.index("-c:v") + 1] = "prores_ks_vulkan"
            # Last pix_fmt is the output, not the raw input.
            pi = len(out) - 1 - out[::-1].index("-pix_fmt")
            out[pi + 1] = "vulkan"
        out[gi] = graph + "[vout]"
        out[-1:-1] = ["-alpha_bits", "16"] + (
            ["-async_depth", str(spec.async_depth or 1)] if spec.gpu else []
        )
    if spec.candidate == "FFV1-DIRECT":
        # Only the explicit fixed-pipeline experiment may publish native MKV.
        # There is no prior MOV master or fixture decode in this path.
        if Path(out[-1]).suffix.lower() != ".mkv":
            raise ValueError("direct FFV1 requires native .mkv output")
        ci = out.index("-c:v")
        if out[ci:-1] != ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]:
            raise ValueError("unknown production single-output codec boundary")
        out[ci:-1] = codec_options("ffv1", False)
    if spec.encoder_threads is not None:
        if "-threads" in out:
            raise ValueError("separate encoder threads cannot override legacy -threads")
        out[-1:-1] = ["-threads:v", str(spec.encoder_threads)]
    if spec.filter_threads is not None:
        # This route uses a complex graph, not a simple -vf graph.
        out[1:1] = ["-filter_complex_threads", str(spec.filter_threads)]
    if spec.gpu:
        out[1:1] = device_args(spec.device)
    key = "-loglevel" if "-loglevel" in out else "-v"
    out[out.index(key) + 1] = "verbose"
    if spec.ribbon_lut is not None:
        from ewp_waveform.ffmpeg.ribbon_lut import ribbon_lut_argv

        out = ribbon_lut_argv(out, spec.ribbon_lut)
    record_command(spec.command_log, out, phase="suite-service-encode")
    return out


def raw_input(
    ffmpeg: str, fmt: str, width: int, height: int, *, gpu: bool = False, device: str = "RTX 3090"
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-n",
        "-v",
        "verbose" if gpu else "error",
        "-xerror",
        *(device_args(device) if gpu else []),
        "-f",
        "rawvideo",
        "-pixel_format",
        fmt,
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        "60/1",
        "-i",
        "pipe:0",
        "-an",
    ]


def raw_output(argv: list[str], graph: str, fmt: str, frames: int = 2) -> list[str]:
    return [
        *argv,
        "-vf",
        graph,
        "-frames:v",
        str(frames),
        "-c:v",
        "rawvideo",
        "-pix_fmt",
        fmt,
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def codec_options(codec: str, gpu: bool) -> list[str]:
    if codec == "prores":
        return [
            "-c:v",
            "prores_ks_vulkan" if gpu else "prores_ks",
            "-profile:v",
            "4444",
            "-alpha_bits",
            "16",
            "-pix_fmt",
            "vulkan" if gpu else "yuva444p10le",
            *(["-async_depth", "1"] if gpu else []),
            "-f",
            "mov",
        ]
    if codec != "ffv1":
        raise ValueError("unsupported suite codec")
    return [
        "-c:v",
        "ffv1_vulkan" if gpu else "ffv1",
        "-level",
        "3",
        "-g",
        "1",
        "-coder",
        "1",
        "-context",
        "0",
        "-slices",
        "4",
        "-pix_fmt",
        "vulkan" if gpu else "bgra",
        *(["-async_depth", "1"] if gpu else []),
        "-f",
        "matroska",
    ]


def codec_argv(
    ffmpeg: str, source: Path, output: Path, *, gpu: bool, device: str, frames: int
) -> list[str]:
    """One compressed common fixture, streamed decode+conversion+encode timer."""
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-n",
        "-v",
        "verbose",
        "-xerror",
        *(device_args(device) if gpu else []),
        "-hwaccel",
        "none",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "format=bgra" + (",hwupload" if gpu else ""),
        "-frames:v",
        str(frames),
        "-fps_mode",
        "cfr",
        "-r",
        "60/1",
        *codec_options("ffv1", gpu),
        str(output),
    ]


def finish_compressed(
    frames: Any,
    output: Path,
    *,
    ffmpeg: str,
    command_log: Path,
    width: int,
    height: int,
    fps: float,
    glow: float,
    overscan: int = 0,
    supersample: int = 1,
    pix_fmt: str = "rgba",
    color: str | None = None,
    n_frames: int | None = None,
    ribbon_finish: tuple[float, bool, float, float, float] | None = None,
    **unused: Any,
) -> None:
    """Production pre-encode finishing -> lossless compressed RGBA oracle; no raw file."""
    from ewp_waveform.ffmpeg.encode import _glow_crop_graph
    from ewp_waveform.ffmpeg.process import run_argv_stdin

    if ribbon_finish is None or n_frames is None:
        raise ValueError("fixture requires real bounded ribbon finishing")
    graph = _glow_crop_graph(
        glow,
        width,
        height,
        overscan,
        supersample,
        pix_fmt=pix_fmt,
        color=color,
        fps=fps,
        n_frames=n_frames,
        ribbon_finish=ribbon_finish,
    )
    argv = [
        ffmpeg,
        "-nostdin",
        "-n",
        "-v",
        "error",
        "-xerror",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-s",
        f"{(width + 2 * overscan) * supersample}x{height + 2 * overscan}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-an",
        "-frames:v",
        str(n_frames),
        *codec_options("ffv1", False),
        str(output),
    ]
    record_command(command_log, argv, phase="production-finish-compressed-fixture")
    result = run_argv_stdin(argv, frames)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr.decode(errors="replace"))
