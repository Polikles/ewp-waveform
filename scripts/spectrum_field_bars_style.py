#!/usr/bin/env python3
"""Style pass on balanced (117-bar) mirrored geometry. Thickness, gaps, alternate, line.

uv run python scripts/spectrum_field_bars_style.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ewp_waveform.application.service import render
from ewp_waveform.paths import normalize_user_path

AUDIO = Path("/home/linuch/waveform-rendering/zz-audio-samples/s0e00/s0e00-Damian.wav")
START = 25.0
DURATION = 8.0
FRAME = 239
BASE_COUNT = 117

VARIANTS: tuple[dict[str, object], ...] = (
    {"name": "T1-thin", "bar_count": BASE_COUNT, "bar_fill": 0.40, "bar_align": "count"},
    {"name": "T2-medium", "bar_count": BASE_COUNT, "bar_fill": 0.62, "bar_align": "count"},
    {"name": "T3-thick", "bar_count": BASE_COUNT, "bar_fill": 0.80, "bar_align": "count"},
    {"name": "G1-tight", "bar_width": 7.0, "bar_gap": 3.0, "bar_align": "period"},
    {"name": "G2-open", "bar_width": 7.0, "bar_gap": 7.0, "bar_align": "period"},
    {"name": "G3-wide", "bar_width": 7.0, "bar_gap": 12.0, "bar_align": "period"},
    {
        "name": "C1-alternate",
        "bar_count": BASE_COUNT,
        "bar_fill": 0.62,
        "bar_align": "count",
        "bar_alternate": True,
        "bar_color_b": "#6E7BA7",
    },
    {
        "name": "L1-center-2px",
        "bar_count": BASE_COUNT,
        "bar_fill": 0.62,
        "bar_align": "count",
        "bar_center_line_width": 2.0,
    },
    {
        "name": "L2-center-alt",
        "bar_count": BASE_COUNT,
        "bar_fill": 0.62,
        "bar_align": "count",
        "bar_alternate": True,
        "bar_color_b": "#6E7BA7",
        "bar_center_line_width": 2.0,
    },
)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _extract_black(mov: Path, dest: Path, index: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    png = dest / f"frame_{index:04d}.png"
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(mov),
        "-vf",
        f"select=eq(n\\,{index})",
        "-frames:v",
        "1",
        str(png),
    ]
    completed = subprocess.run(argv, check=False, capture_output=True)
    if completed.returncode != 0 or not png.is_file():
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    raw = dest / f"frame_{index:04d}.raw"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(png),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    data = bytearray(raw.read_bytes())
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        a = data[i + 3]
        if not a:
            continue
        out[i] = data[i] * a // 255
        out[i + 1] = data[i + 1] * a // 255
        out[i + 2] = data[i + 2] * a // 255
        out[i + 3] = 255
    raw.write_bytes(out)
    black = dest / f"frame_{index:04d}_black.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-s",
            "1400x280",
            "-i",
            str(raw),
            str(black),
        ],
        check=True,
        capture_output=True,
    )
    return black


def _run(audio: Path, root: Path, spec: dict[str, object]) -> dict[str, object]:
    name = str(spec["name"])
    wall0 = time.perf_counter()
    results = render(
        audio,
        output_dir=root / name,
        preset_name="iuris-spectrum",
        formats=["prores4444"],
        force=True,
        start=START,
        duration=DURATION,
        spectrum_contour=True,
        spectrum_spatial_scale=1.0,
        spectrum_spatial_filter="gaussian",
        spectrum_n_bands=64,
        spectrum_tilt_db_per_octave=3.0,
        spectrum_compress=0.75,
        visual_geometry="spectrum",
        spectrum_layout="field_center_out",
        field_geometry="mirrored_bars",
        bar_count=spec.get("bar_count") if isinstance(spec.get("bar_count"), int) else None,
        bar_fill=spec.get("bar_fill") if isinstance(spec.get("bar_fill"), float) else None,
        bar_width=spec.get("bar_width") if isinstance(spec.get("bar_width"), float) else None,
        bar_gap=spec.get("bar_gap") if isinstance(spec.get("bar_gap"), float) else None,
        bar_align=str(spec["bar_align"]) if spec.get("bar_align") is not None else None,
        bar_alternate=bool(spec.get("bar_alternate", False)),
        bar_color_b=str(spec["bar_color_b"]) if spec.get("bar_color_b") is not None else None,
        bar_center_line_width=(
            float(spec["bar_center_line_width"])
            if isinstance(spec.get("bar_center_line_width"), float)
            else None
        ),
        progress=_progress,
    )
    wall = time.perf_counter() - wall0
    payload = results[0]
    job = payload.get("job")
    if not isinstance(job, dict) or job.get("status") != "SUCCEEDED":
        raise RuntimeError(str(payload.get("warnings")))
    outputs = payload.get("outputs")
    mov = Path(str(outputs[0]["path"])) if isinstance(outputs, list) and outputs else None
    if mov is None:
        raise RuntimeError("no mov")
    preview = _extract_black(mov, root / name / "frames", FRAME)
    perf = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    extras = perf.get("extras") if isinstance(perf, dict) else {}
    seconds = perf.get("seconds") if isinstance(perf, dict) else {}
    return {
        "name": name,
        "wall_s": wall,
        "rtf": wall / DURATION,
        "render_path": extras.get("render_path") if isinstance(extras, dict) else None,
        "raster_s": seconds.get("raster") if isinstance(seconds, dict) else None,
        "preview": str(preview),
        "mov": str(mov),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", default=str(AUDIO))
    parser.add_argument("--output-root", default="/tmp/ewp-bars-style")
    parser.add_argument("--only", default="", help="comma-separated variant names")
    args = parser.parse_args()
    wanted = {part.strip() for part in args.only.split(",") if part.strip()}
    audio = normalize_user_path(args.audio)
    root = Path(args.output_root)
    rows = []
    for spec in VARIANTS:
        if wanted and str(spec["name"]) not in wanted:
            continue
        print(f"=== {spec['name']} ===", flush=True)
        rows.append(_run(audio, root, spec))
    print("SUMMARY", json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
