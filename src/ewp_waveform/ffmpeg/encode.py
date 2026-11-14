"""Encode RGBA frame streams with FFmpeg (glow + ProRes/PNG)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding
    from ewp_waveform.ffmpeg.experiments import EncodeExperiment

from ewp_waveform.ffmpeg.draw import parse_rgb
from ewp_waveform.ffmpeg.process import require_tool, run_argv_stdin
from ewp_waveform.ffmpeg.ribbon import ribbon_graph

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


def _colorize_gray_prefix(color: str) -> str:
    """Gray coverage -> unassociated RGBA: RGB is the style color only where alpha > 0.

    Transparent pixels stay RGB 0 so players that ignore ProRes alpha do not
    show a solid fill. Geometry stays in the Python raster.
    """
    r, g, b = parse_rgb(color)
    return (
        "[0:v]format=gray,split=2[gmask][gluma];"
        f"[gluma]format=gbrp,lut=c0='if(val\\,{r}\\,0)':c1='if(val\\,{g}\\,0)':"
        f"c2='if(val\\,{b}\\,0)'[rgb];"
        "[rgb][gmask]alphamerge,format=rgba"
    )


def _glow_crop_graph(
    glow: float,
    width: int,
    height: int,
    overscan: int,
    supersample: int = 1,
    shutter_px: float = 0.0,
    shutter_mix: float = 0.25,
    *,
    pix_fmt: str = "rgba",
    color: str | None = None,
    fps: float = 60.0,
    n_frames: int | None = None,
    ribbon_finish: tuple[float, bool, float, float, float] | None = None,
    suite_candidate: str | None = None,
) -> str:
    """Downsample, optional hybrid temporal mix, glow under a sharp-ish base, crop.

    Visible base is ``(1-mix)*sharp + mix*shutter`` so the edge stays crisp.
    Glow is generated from that stabilized mask and composited underneath.
    """
    if ribbon_finish is not None:
        if color is None:
            raise ValueError("ribbon finishing requires waveform color")
        return ribbon_graph(
            width=width,
            height=height,
            overscan=overscan,
            supersample=supersample,
            pix_fmt=pix_fmt,
            color=color,
            glow=glow,
            finish=ribbon_finish,
            suite_candidate=suite_candidate,
        )
    padded_w = width + 2 * overscan
    padded_h = height + 2 * overscan
    mix = min(max(shutter_mix, 0.0), 1.0)
    sharp_w = 1.0 - mix
    sigma = shutter_sigma(shutter_px)
    use_taa = sigma > 0.0 and mix > 0.0
    scale = f"scale={padded_w}:{padded_h}:flags=area" if supersample > 1 else "format=rgba"
    crop = f",crop={width}:{height}:{overscan}:{overscan}" if overscan > 0 else ""
    if pix_fmt == "gray":
        if color is None:
            msg = "gray encode requires waveform color for downstream colorize"
            raise ValueError(msg)
        head = _colorize_gray_prefix(color)
    else:
        head = "[0:v]"
    if use_taa:
        taa = (
            f"{scale},split=2[sharp][taa];"
            f"[taa]gblur=sigma={sigma:.4f}:sigmaV=0.01:steps=1[taab];"
            f"[sharp][taab]blend=all_expr='A*{sharp_w:.4f}+B*{mix:.4f}'"
            ":shortest=1,format=rgba"
        )
        body = f"{head},{taa}" if head != "[0:v]" else f"[0:v]{taa}"
        if glow > 0:
            return (
                f"{body},split=2[base][g];[g]gblur=sigma="
                f"{glow}:steps=3[gb];[gb][base]overlay=format=auto:shortest=1,"
                f"format=rgba{crop}[vout]"
            )
        return f"{body}{crop}[vout]"
    if glow > 0:
        body = f"{head},{scale}" if head != "[0:v]" else f"[0:v]{scale}"
        return (
            f"{body},split=2[base][g];[g]gblur=sigma="
            f"{glow}:steps=3[gb];[gb][base]overlay=format=auto:shortest=1,"
            f"format=rgba{crop}[vout]"
        )
    body = f"{head},{scale}" if head != "[0:v]" else f"[0:v]{scale}"
    return f"{body}{crop}[vout]"


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
    phases: Any | None = None,
    pix_fmt: str = "rgba",
    color: str | None = None,
    n_frames: int | None = None,
    ribbon_finish: tuple[float, bool, float, float, float] | None = None,
    experiment: EncodeExperiment | SuiteEncoding | None = None,
    ribbon_finish_lut: bool = False,
) -> None:
    if type(ribbon_finish_lut) is not bool:
        raise ValueError("ribbon_finish_lut must be an explicit boolean")
    if ribbon_finish_lut and (
        png_dir is not None
        or prores_path is None
        or ribbon_finish is None
        or experiment is not None
    ):
        raise ValueError(
            "ribbon_finish_lut requires ordinary CPU ribbon finishing and one MOV/no PNG"
        )
    if experiment is not None and (png_dir is not None or prores_path is None):
        raise ValueError("experiments require one MOV output, never simultaneous PNG")
    if png_dir is None and prores_path is None:
        msg = "encode_rgba_stream requires png_dir and/or prores_path"
        raise ValueError(msg)
    ffmpeg = require_tool("ffmpeg")
    ss = max(1, int(supersample))
    in_fmt = "gray" if pix_fmt == "gray" else "rgba"
    if phases is not None:
        phases.extras["raw_feed_pixel_format"] = in_fmt
        phases.extras["ffmpeg_threads_argument"] = ffmpeg_threads
        phases.extras["ffmpeg_threads_option_role"] = (
            "input_rawvideo_decoder"
            if png_dir is not None and prores_path is not None
            else "output_encoder"
        )
        phases.extras["ffmpeg_threads_scope"] = (
            "adapter-selected stream parameter; role follows unchanged option placement; "
            "0 omits -threads; not an observed thread count or process/filter cap"
        )
    in_w = (width + 2 * overscan) * ss
    in_h = height + 2 * overscan
    graph = _glow_crop_graph(
        glow,
        width,
        height,
        overscan,
        ss,
        shutter_px,
        shutter_mix,
        pix_fmt=in_fmt,
        color=color,
        fps=fps,
        n_frames=n_frames,
        ribbon_finish=ribbon_finish,
        suite_candidate=getattr(experiment, "candidate", None),
    )
    argv: list[str] = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        in_fmt,
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
                pix_fmt=in_fmt,
                color=color,
                n_frames=n_frames,
                ribbon_finish=ribbon_finish,
            )
            completed = run_argv_stdin(argv, frames, phases=phases)
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
    if experiment is not None:
        from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding, service_argv
        from ewp_waveform.ffmpeg.experiments import experiment_argv

        argv = (
            service_argv(argv, experiment)
            if isinstance(experiment, SuiteEncoding)
            else experiment_argv(argv, experiment)
        )
    if ribbon_finish_lut:
        assert prores_path is not None and ribbon_finish is not None
        _encode_ribbon_lut(
            argv,
            frames,
            prores_path=prores_path,
            width=width,
            height=height,
            finish=ribbon_finish,
            phases=phases,
        )
        return
    stderr_path = (
        experiment.command_log.with_suffix(".service.stderr")
        if experiment is not None and experiment.command_log is not None
        else None
    )
    completed = run_argv_stdin(
        argv, frames, phases=phases, **({"stderr_path": stderr_path} if stderr_path else {})
    )
    if experiment is not None:
        from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding, selected_device

        if isinstance(experiment, SuiteEncoding):
            diagnostic = completed.stderr.decode("utf-8", errors="replace")
            experiment.command_log.with_suffix(".service.stderr").write_text(diagnostic)
            if completed.returncode == 0 and experiment.gpu:
                selected_device(diagnostic, experiment.expect_device_regex)
    if completed.returncode != 0:
        msg = completed.stderr.decode("utf-8", errors="replace")
        raise EncodeError(msg.strip() or "ffmpeg encode failed")


def _encode_ribbon_lut(
    argv: list[str],
    frames: Iterable[bytes],
    *,
    prores_path: Path,
    width: int,
    height: int,
    finish: tuple[float, bool, float, float, float],
    phases: Any | None,
) -> None:
    """Per-call qualification inside service wall; no cache or worker-global state.

    Masks and qualifier scratch are uniquely output-workdir-owned and removed even
    on failure. The small adjacent sidecar survives for pool-parent collection.
    """
    from ewp_waveform.ffmpeg.ribbon_lut import (
        GeqSampling,
        prepare_ribbon_lut,
        qualify_ribbon_lut,
        ribbon_lut_argv,
    )

    record: dict[str, Any] = {
        "enabled": True,
        "status": "started",
        "ffmpeg": argv[0],
        "pid": os.getpid(),
        "output_path": str(prores_path),
        "timing_scope": (
            "inclusive qualification/setup/encode/scratch-cleanup wall; excludes lazy imports, "
            "ordinary argv construction and sidecar serialization; "
            "all included in outer service wall"
        ),
    }
    sidecar = prores_path.with_suffix(".ribbon-lut.json")
    started = time.perf_counter()
    root: Path | None = None
    try:
        with TemporaryDirectory(prefix=".ribbon-lut-", dir=prores_path.parent) as directory:
            root = Path(directory)
            before = time.perf_counter()
            try:
                qualification = qualify_ribbon_lut(argv[0], root / "qualification")
            except Exception:
                record["qualification_diagnostics"] = {
                    str(path.relative_to(root)): path.read_text(encoding="utf-8", errors="replace")
                    for path in (root / "qualification").glob("*.stderr")
                }
                raise
            finally:
                record["qualification_seconds"] = time.perf_counter() - before
            record["qualification"] = qualification
            if qualification.get("passed") is not True:
                raise ValueError("ribbon LUT selected-runtime qualification did not pass")
            mode = qualification.get("sampling")
            if mode not in ("identity", "smear"):
                raise ValueError("ribbon LUT qualification returned unsupported GEQ sampling")
            sampling = GeqSampling(argv[0], "identity" if mode == "identity" else "smear")
            prepared = prepare_ribbon_lut(
                root / "classes.pgm",
                width=width,
                height=height,
                finish=finish,
                sampling=sampling,
            )
            record["prepared"] = prepared.record()
            command = ribbon_lut_argv(argv, prepared)
            record["argv"] = command
            record["setup_seconds"] = time.perf_counter() - started
            stderr_path = root / "encode.stderr"
            try:
                completed = run_argv_stdin(command, frames, phases=phases, stderr_path=stderr_path)
            finally:
                if stderr_path.is_file():
                    record["stderr"] = stderr_path.read_text(encoding="utf-8", errors="replace")
            record["returncode"] = completed.returncode
            record["stderr"] = completed.stderr.decode("utf-8", errors="replace")
            if completed.returncode:
                raise EncodeError(record["stderr"].strip() or "ffmpeg LUT encode failed")
            record["status"] = "succeeded"
    except (ValueError, subprocess.SubprocessError) as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise EncodeError(f"ribbon LUT refused: {exc}") from exc
    except BaseException as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        record["service_encode_seconds_including_setup"] = time.perf_counter() - started
        record["temporary_masks_removed"] = root is None or not root.exists()
        sidecar.write_text(json.dumps(record, indent=2), encoding="utf-8")
        if phases is not None:
            phases.extras["ribbon_finish_lut"] = record


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
    pix_fmt: str = "rgba",
    color: str | None = None,
    n_frames: int | None = None,
    ribbon_finish: tuple[float, bool, float, float, float] | None = None,
) -> list[str]:
    ss = max(1, int(supersample))
    in_fmt = "gray" if pix_fmt == "gray" else "rgba"
    core = _glow_crop_graph(
        glow,
        width,
        height,
        overscan,
        ss,
        shutter_px,
        shutter_mix,
        pix_fmt=in_fmt,
        color=color,
        fps=fps,
        n_frames=n_frames,
        ribbon_finish=ribbon_finish,
    )
    graph = core.replace("[vout]", ",split=2[png][mov]", 1)
    in_w = (width + 2 * overscan) * ss
    in_h = height + 2 * overscan
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        in_fmt,
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
