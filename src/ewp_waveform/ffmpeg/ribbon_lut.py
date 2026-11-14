"""Bounded, opt-in exact CPU replacement of ribbon's final gray GEQ only.

Call ``probe_geq_sampling`` once with the frozen FFmpeg executable, then
``prepare_ribbon_lut`` once per render. Report preparation separately from
render-call wall AND include it in E2E wall. Pass the resulting object to
``ribbon_lut_argv`` at the production single-output argv seam. No production
defaults or thread options change.

The installed FFmpeg may sample integer lum(X,Y) at the last row/column OR
clamp to the penultimate row/column. Never infer this from a version string:
the tiny actual-GEQ witness below selects identity or smear, otherwise refuses.
Actual all-256-code GEQ/lut2 byte oracles must qualify the selected runtime.
"""

from __future__ import annotations

import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ewp_waveform.ffmpeg.ribbon import ribbon_graph

Finish = tuple[float, bool, float, float, float]
_SAMPLE = ",geq=lum='([^']*)'"


@dataclass(frozen=True)
class GeqSampling:
    """Observed integer-coordinate GEQ behavior of the selected executable."""

    ffmpeg: str
    mode: Literal["identity", "smear"]


def probe_geq_sampling(ffmpeg: str) -> GeqSampling:
    """Real nonuniform corner witness; no timestamp/thread/performance claims."""
    source = bytes(range(30))
    result = subprocess.run(
        [
            ffmpeg,
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
            "geq=lum='lum(X,Y)'",
            "-frames:v",
            "1",
            "-c:v",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        input=source,
        capture_output=True,
        check=True,
        timeout=30,
    )
    if result.stderr:
        raise ValueError(f"GEQ sampling witness diagnostics: {result.stderr!r}")
    smeared = bytes(source[min(y, 3) * 6 + min(x, 4)] for y in range(5) for x in range(6))
    if result.stdout == source:
        return GeqSampling(ffmpeg, "identity")
    if result.stdout == smeared:
        return GeqSampling(ffmpeg, "smear")
    raise ValueError("bounded refusal: unsupported GEQ integer sampling behavior")


def _expression(width: int, height: int, finish: Finish) -> str:
    graph = ribbon_graph(
        width=width,
        height=height,
        finish=finish,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#FFFFFF",
        glow=0,
    )
    match = re.search(_SAMPLE, graph)
    if match is None or graph.count(",geq=") != 1:
        raise ValueError("unrecognized production ribbon GEQ")
    return match[1]


@dataclass(frozen=True)
class PreparedRibbonLut:
    """Render-owned static full-canvas mask and exact expression substitution."""

    mask_path: Path
    width: int
    height: int
    finish: Finish
    sampling: GeqSampling
    class_count: int
    preparation_seconds: float
    lut_expression: str
    geq_expression: str

    def record(self) -> dict[str, object]:
        return {
            "mask_path": str(self.mask_path),
            "canvas_width": self.width,
            "canvas_height": self.height,
            "class_count": self.class_count,
            "preparation_seconds": self.preparation_seconds,
            "geq_integer_sampling": self.sampling.mode,
            "ffmpeg": self.sampling.ffmpeg,
            "changed_stage": "final gray GEQ only",
            "unchanged_stages": ["AA", "gblur", "blend", "crop", "colorization", "encoding"],
            "production_default": False,
        }


def _validate(width: int, height: int, finish: Finish, sampling: GeqSampling) -> None:
    if (
        type(width) is not int
        or type(height) is not int
        or min(width, height) < 3
        or max(width, height) > 16384
        or width * height > 64 * 1024 * 1024
    ):
        raise ValueError("bounded refusal: canvas dimensions 3..16384 and <=64 Mi pixels required")
    reflection, enabled, thickness, extent, opacity = finish
    if (
        type(enabled) is not bool
        or not all(math.isfinite(v) for v in (reflection, thickness, extent, opacity))
        or not 0 <= reflection <= 1
        or thickness < 0
        or not 0 <= extent <= 1
        or not 0 <= opacity <= 1
        or sampling.mode not in ("identity", "smear")
    ):
        raise ValueError("invalid finite ribbon geometry or sampling qualification")


def prepare_ribbon_lut(
    mask_path: Path,
    *,
    width: int,
    height: int,
    finish: Finish,
    sampling: GeqSampling,
) -> PreparedRibbonLut:
    """Prepare one PGM, refusing overwrite/unsupported geometry before writing.

    Class identity uses exact double (line coverage, reflection factor). The
    expression for each class substitutes integer coordinates into the ORIGINAL
    production GEQ expression, NOT a rounded line coefficient or rearranged
    multiply/add. Thus FFmpeg evaluates the original operation order in lut2's
    table, once for each input-code/class pair rather than once per canvas pixel.
    Python never computes finished alpha and no rendered frame enters preparation.
    """
    started = time.perf_counter()
    _validate(width, height, finish, sampling)
    reflection, enabled, thickness, extent, opacity = finish
    expression = _expression(width, height, finish)
    left, right = width * (1 - extent) / 2, width * (1 + extent) / 2
    cy = height // 2 + 0.5
    top, bottom = cy - thickness / 2, cy + thickness / 2
    active = enabled and extent > 0 and opacity > 0
    # Consecutive horizontal coverage spans; storage is O(width + class count).
    spans: list[tuple[int, int, float]] = []
    for x in range(width):
        coverage = min(1.0, max(0.0, min(x + 1, right) - max(x, left))) if active else 0.0
        if spans and spans[-1][2] == coverage:
            start, _, value = spans[-1]
            spans[-1] = (start, x + 1, value)
        else:
            spans.append((x, x + 1, coverage))
    classes: dict[tuple[float, float], int] = {}
    expressions: list[str] = []
    rows: list[bytes] = []
    row_cache: dict[tuple[int, ...], bytes] = {}
    for y in range(height):
        vertical = min(1.0, max(0.0, min(y + 1, bottom) - max(y, top))) if active else 0.0
        factor = reflection if y > height // 2 else 1.0
        ids: list[int] = []
        for x, _, horizontal in spans:
            key = (opacity * horizontal * vertical if active else 0.0, factor)
            if key not in classes:
                if len(classes) >= 256:
                    raise ValueError("bounded refusal: ribbon geometry exceeds 256 classes")
                classes[key] = len(classes)
                # Keep lum's replacement separate from canvas coordinates X/Y.
                item = expression.replace("lum(X,Y)", "INPUT_CODE")
                item = re.sub(r"\bX\b", str(x), item)
                item = re.sub(r"\bY\b", str(y), item).replace("INPUT_CODE", "x")
                expressions.append(item)
            ids.append(classes[key])
        signature = tuple(ids)
        if signature not in row_cache:
            row_cache[signature] = b"".join(
                bytes([idx]) * (end - start)
                for idx, (start, end, _) in zip(ids, spans, strict=True)
            )
        rows.append(row_cache[signature])
    # Invalid/unreachable class bytes deterministically evaluate the last class.
    lut = expressions[-1]
    for idx in range(len(expressions) - 2, -1, -1):
        lut = f"if(eq(y,{idx}),{expressions[idx]},{lut})"
    mask_path = mask_path.resolve()
    with mask_path.open("xb") as out:
        out.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        for row in rows:
            out.write(row)
    return PreparedRibbonLut(
        mask_path=mask_path,
        width=width,
        height=height,
        finish=finish,
        sampling=sampling,
        class_count=len(classes),
        preparation_seconds=time.perf_counter() - started,
        lut_expression=lut,
        geq_expression=expression,
    )


def _argument(argv: list[str], key: str) -> str:
    if argv.count(key) != 1 or argv.index(key) + 1 >= len(argv):
        raise ValueError(f"one valued {key} option required")
    return argv[argv.index(key) + 1]


def _check_canvas(argv: list[str], prefix: str, prepared: PreparedRibbonLut) -> None:
    # Only maintained CPU gray/AA/blur/union/crop prefixes, not arbitrary graphs.
    match = re.fullmatch(
        r"\[0:v\](?:format=gray|alphaextract)"
        r"(?:,scale=(\d+):(\d+):flags=area)?"
        r"(?:,split=2\[body\]\[halo\];\[halo\]gblur=sigma=[0-9.eE+\-]+:steps=3\[blur\];"
        r"\[body\]\[blur\]blend=all_expr='A\+B\*\(1-A/255\)':shortest=1)?"
        r"(?:,crop=(\d+):(\d+):(\d+):(\d+))?",
        prefix,
    )
    source = argv[: argv.index("-i")]
    if match is None or _argument(source, "-f") != "rawvideo":
        raise ValueError("unrecognized original CPU gray/AA/blur/union/crop prefix")
    fmt = _argument(source, "-pix_fmt")
    if fmt not in ("gray", "rgba") or prefix.startswith("[0:v]alphaextract") != (fmt == "rgba"):
        raise ValueError("unsupported original ribbon mask format")
    dims = re.fullmatch(r"(\d+)x(\d+)", _argument(source, "-s"))
    if dims is None:
        raise ValueError("explicit original rawvideo dimensions required")
    width, height = int(dims[1]), int(dims[2])
    if match[1] is not None:
        scaled_w, scaled_h = int(match[1]), int(match[2])
        if scaled_w <= 0 or width % scaled_w or width <= scaled_w or height != scaled_h:
            raise ValueError("only production horizontal supersampling is supported")
        width, height = scaled_w, scaled_h
    if match[3] is not None:
        cw, ch, cx, cy = (int(match[i]) for i in range(3, 7))
        if cx != cy or (width, height) != (cw + 2 * cx, ch + 2 * cy):
            raise ValueError("only production symmetric overscan crop is supported")
        width, height = cw, ch
    if (width, height) != (prepared.width, prepared.height):
        raise ValueError("prepared class mask canvas differs from production canvas")


def ribbon_lut_argv(argv: list[str], prepared: PreparedRibbonLut) -> list[str]:
    """Transform only a recognized production single-output ribbon command.

    Add ONE nonlooped still-image input. Explicit framesync repeats its last
    frame through primary EOF; it never creates an infinite primary timeline.
    Existing encoder options and all thread selections are untouched. Refuse
    unknown graph/output/input seams rather than silently selecting a new path.
    """
    out = list(argv)
    if (
        not out
        or out[0] != prepared.sampling.ffmpeg
        or out.count("-i") != 1
        or out.count("-filter_complex") != 1
        or out.count("-map") != 1
        or out.count("-c:v") != 1
        or _argument(out, "-map") != "[vout]"
    ):
        raise ValueError("requires qualified FFmpeg and production single-input/single-output argv")
    gi = out.index("-filter_complex") + 1
    graph = _argument(out, "-filter_complex")
    match = re.search(_SAMPLE, graph)
    if (
        match is None
        or match[1] != prepared.geq_expression
        or graph.count(",geq=") != 1
        or not graph.endswith("[vout]")
        or graph.count("[vout]") != 1
        or not graph.startswith(("[0:v]format=gray", "[0:v]alphaextract"))
        or not graph[match.end() :].startswith(",split=2[alpha][luma];")
    ):
        raise ValueError("unrecognized production ribbon finishing seam or different geometry")
    _check_canvas(out, graph[: match.start()], prepared)
    if not prepared.mask_path.is_file():
        raise ValueError("prepared class mask is missing")
    smear = ",fillborders=right=1:bottom=1:mode=smear" if prepared.sampling.mode == "smear" else ""
    # The mask remains canvas-global AFTER the unchanged overscan crop. Pin the
    # lut2 OUTPUT to gray too: d=8 alone permits downstream GBR negotiation and
    # can fail the filter's one-plane input/three-plane output configuration.
    replacement = (
        smear + "[ribbon_lut_body];[1:v]format=gray[ribbon_lut_classes];"
        f"[ribbon_lut_body][ribbon_lut_classes]lut2=c0='{prepared.lut_expression}':"
        "d=8:eof_action=repeat:shortest=0:repeatlast=1,format=gray"
    )
    out[gi] = graph[: match.start()] + replacement + graph[match.end() :]
    # Insert after primary input options and before all output options. The PGM
    # demuxer emits one frame at t=0; lut2 repeatlast supplies subsequent frames.
    fi = out.index("-filter_complex")
    out[fi:fi] = ["-f", "image2", "-pattern_type", "none", "-i", str(prepared.mask_path)]
    return out
