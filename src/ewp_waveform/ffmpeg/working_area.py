"""Opt-in compact finishing domains; never a replacement production canvas.

EARLY-AREA deliberately changes recursive blur boundaries. A three-sigma margin
is a minimum experimental guard, NOT finite support or an equivalence guarantee.
Full masks and horizontal supersampling remain production-sized and unchanged.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ewp_waveform.ffmpeg.experiments import (
    Crop,
    EncodeExperiment,
    experiment_argv,
    frame_metrics,
    record_command,
)
from ewp_waveform.ffmpeg.process import run_argv_stdin
from ewp_waveform.ffmpeg.ribbon import ribbon_graph

CONTROLS = ("CPU-BASE", "CROP-OUT", "EARLY-AREA")


@dataclass(frozen=True)
class WorkingArea:
    """Frozen whole-clip final rectangle and explicit vertical blur guard."""

    crop: Crop
    margin: int

    def __post_init__(self) -> None:
        if type(self.margin) is not int or self.margin < 0:
            raise ValueError("explicit nonnegative integer working margin required")

    def domain(self, overscan: int, glow: float) -> tuple[int, int]:
        if type(overscan) is not int or overscan < 0 or not math.isfinite(glow) or glow < 0:
            raise ValueError("invalid production padding/glow")
        if self.margin < max(1, math.ceil(3 * glow)):
            raise ValueError("earlier domain requires explicit margin >= max(1, ceil(3*glow))")
        top = max(0, overscan + self.crop.y - self.margin)
        bottom = min(
            self.crop.canvas_height + 2 * overscan,
            overscan + self.crop.y + self.crop.height + self.margin,
        )
        if bottom - top >= self.crop.canvas_height + 2 * overscan:
            raise ValueError("bounded refusal: margin leaves no smaller working height")
        return top, bottom

    def record(self, overscan: int, glow: float, control: str) -> dict[str, Any]:
        if control not in CONTROLS:
            raise ValueError("unknown compact-area control")
        top, bottom = (
            self.domain(overscan, glow)
            if control == "EARLY-AREA"
            else (0, self.crop.canvas_height + 2 * overscan)
        )
        c = self.crop
        return {
            "control": control,
            "frozen_export_rectangle": c.record(),
            "placement": c.record()
            if control != "CPU-BASE"
            else Crop(
                0, 0, c.canvas_width, c.canvas_height, c.canvas_width, c.canvas_height
            ).record(),
            "placement_offset_xy": [c.x, c.y] if control != "CPU-BASE" else [0, 0],
            "output_size": [c.width, c.height]
            if control != "CPU-BASE"
            else [c.canvas_width, c.canvas_height],
            "working_padded_y_interval": [top, bottom],
            "working_width": c.canvas_width + 2 * overscan,
            "working_height": bottom - top,
            "original_padded_height": c.canvas_height + 2 * overscan,
            "guarded_geq_canvas_y_interval": [
                max(0, top - overscan),
                min(c.canvas_height, bottom - overscan),
            ],
            "explicit_margin": self.margin,
            "minimum_margin_rule": "max(1, ceil(3*glow)); not a recursive-blur support bound",
            "unchanged_stages": [
                "analysis",
                "normalization",
                "raster",
                "full-mask feed",
                "AA scale",
            ],
            "affected_stages": {
                "CPU-BASE": [],
                "CROP-OUT": ["post-finish export crop", "color conversion", "encoding"],
                "EARLY-AREA": [
                    "pre-blur gray working height",
                    "recursive gblur",
                    "body/halo blend",
                    "global-coordinate horizon/reflection on guarded working domain",
                    "colorization",
                    "color conversion",
                    "encoding",
                ],
            }[control],
            "intentional_differences": (
                "outside-export content/halo loss (not necessarily faint for tight bounds); "
                "EARLY-AREA also changes recursive blur boundaries"
            ),
            "alpha_association": "straight",
            "visual_acceptance": "PENDING",
            "resolve_acceptance": "PENDING",
            "production_promotion": False,
        }


def working_area_graph(
    *,
    area: WorkingArea,
    control: str,
    overscan: int,
    supersample: int,
    glow: float,
    color: str,
    finish: tuple[float, bool, float, float, float],
    pix_fmt: str = "gray",
) -> str:
    """Adapt the actual production ribbon graph, refusing unrecognized seams.

    Crop gray AFTER unchanged AA downsampling and BEFORE recursive gblur. Keep
    full horizontal blur support. Shift only analytic coordinates, never lum's
    local sampling coordinates; reflection split and horizon stay canvas-global.
    """
    if control not in CONTROLS or pix_fmt != "gray":
        raise ValueError("compact-area seam supports explicit controls and gray ribbon only")
    if type(supersample) is not int or supersample < 1:
        raise ValueError("invalid horizontal supersampling")
    c = area.crop
    graph = ribbon_graph(
        width=c.canvas_width,
        height=c.canvas_height,
        overscan=overscan,
        supersample=supersample,
        pix_fmt=pix_fmt,
        color=color,
        glow=glow,
        finish=finish,
    )
    if control == "CPU-BASE":
        return graph
    if control == "CROP-OUT":
        # Reuse the established finished-output crop transformation, not a new algorithm.
        argv = experiment_argv(
            ["ffmpeg", "-filter_complex", graph, "-c:v", "prores_ks", "unused.mov"],
            EncodeExperiment("CROP-OUT", c),
        )
        return argv[2]
    top, bottom = area.domain(overscan, glow)
    pw, ph = c.canvas_width + 2 * overscan, c.canvas_height + 2 * overscan
    prefix = "[0:v]format=gray"
    if supersample > 1:
        prefix += f",scale={pw}:{ph}:flags=area"
    if not graph.startswith(prefix):
        raise ValueError("unrecognized production gray/AA seam")
    graph = prefix + f",crop={pw}:{bottom - top}:0:{top}:exact=1" + graph[len(prefix) :]
    old_crop = f",crop={c.canvas_width}:{c.canvas_height}:{overscan}:{overscan}"
    # Keep guard rows through geq too: its local lum interpolation at an export
    # edge must not manufacture a new reflection/horizon sampling boundary.
    global_top = max(0, top - overscan)
    global_bottom = min(c.canvas_height, bottom - overscan)
    new_crop = (
        f",crop={c.canvas_width}:{global_bottom - global_top}:"
        f"{overscan}:{overscan + global_top - top}:exact=1"
    )
    if overscan:
        if graph.count(old_crop) != 1:
            raise ValueError("unrecognized production overscan crop seam")
        graph = graph.replace(old_crop, new_crop, 1)
    else:
        graph = graph.replace(",geq=lum=", new_crop + ",geq=lum=", 1)
    match = re.search(r",geq=lum='([^']*)'", graph)
    if match is None:
        raise ValueError("unrecognized production horizon/reflection seam")
    expression = match[1].replace("lum(X,Y)", "LOCAL_SAMPLE")
    expression = re.sub(r"\bY\b", f"(Y+{global_top})", expression)
    expression = expression.replace("LOCAL_SAMPLE", "lum(X,Y)")
    graph = graph[: match.start(1)] + expression + graph[match.end(1) :]
    return graph.removesuffix("[vout]") + (
        f",crop={c.width}:{c.height}:{c.x}:{c.y - global_top}:exact=1[vout]"
    )


def encode_working_area(
    frames: Iterable[bytes],
    *,
    area: WorkingArea,
    control: str,
    output: Path,
    ffmpeg: str,
    command_log: Path,
    width: int,
    height: int,
    fps: float,
    glow: float,
    overscan: int = 0,
    supersample: int = 1,
    pix_fmt: str = "gray",
    color: str | None = None,
    ribbon_finish: tuple[float, bool, float, float, float] | None = None,
    ffmpeg_threads: int = 0,
    phases: Any | None = None,
    shutter_px: float = 0.0,
    shutter_mix: float = 0.25,
    n_frames: int | None = None,
) -> None:
    """Same single-output production ProRes encoder, full original raster input.

    Caller owns process deadlines/resource supervision. No rendered master input
    exists at this seam. Unknown active finishing controls fail closed.
    """
    if (width, height) != (area.crop.canvas_width, area.crop.canvas_height):
        raise ValueError("crop canvas differs from original production canvas")
    if color is None or ribbon_finish is None or shutter_px != 0:
        raise ValueError("only production ribbon finishing without temporal shutter is supported")
    graph = working_area_graph(
        area=area,
        control=control,
        overscan=overscan,
        supersample=supersample,
        glow=glow,
        color=color,
        finish=ribbon_finish,
        pix_fmt=pix_fmt,
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
        "gray",
        "-s",
        f"{(width + 2 * overscan) * supersample}x{height + 2 * overscan}",
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
        argv += ["-threads", str(ffmpeg_threads)]
    argv += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(output)]
    record_command(command_log, argv, phase="compact-area-production-raster-encode")
    result = run_argv_stdin(argv, frames, phases=phases)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr.decode(errors="replace"))


def difference_metrics(reference: bytes, candidate: bytes, *, crop: Crop) -> dict[str, Any]:
    """Full canvas vs compact canonical RGBA8; descriptive, not acceptance limits.

    Suitable for pre-encode or decoded frames; do not mix those measurement domains.
    """
    c = crop
    a = np.frombuffer(reference, dtype=np.uint8).reshape(c.canvas_height, c.canvas_width, 4)
    small = np.frombuffer(candidate, dtype=np.uint8).reshape(c.height, c.width, 4)
    b = np.zeros_like(a)
    b[c.y : c.y + c.height, c.x : c.x + c.width] = small
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
    outside = a[:, :, 3].copy()
    outside[c.y : c.y + c.height, c.x : c.x + c.width] = 0
    inside = delta[c.y : c.y + c.height, c.x : c.x + c.width, 3]
    return {
        "alpha_max_error": int(delta[:, :, 3].max()),
        "inside_alpha_max_error": int(inside.max()),
        "rgba_max_error": int(delta.max()),
        "hidden_rgb_changed_pixels": int(
            np.count_nonzero(
                (a[:, :, 3] == 0) & (b[:, :, 3] == 0) & np.any(delta[:, :, :3] != 0, axis=2)
            )
        ),
        "outside_crop_alpha_max": int(outside.max()),
        "outside_crop_alpha_sum": int(outside.sum(dtype=np.int64)),
        "alpha_error_exceeds_codes": {
            str(t): int(np.count_nonzero(delta[:, :, 3] > t)) for t in (0, 1, 2, 8, 32)
        },
        "outside_alpha_exceeds_codes": {
            str(t): int(np.count_nonzero(outside > t)) for t in (0, 1, 2, 8, 32)
        },
        "threshold_semantics": "descriptive code-value bins only; no appearance PASS threshold",
        "edge_halo_composite_integer_metrics": frame_metrics(
            reference, b.tobytes(), c.canvas_width, c.canvas_height
        ),
    }
