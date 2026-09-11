#!/usr/bin/env python3
"""8 s geometry variants for fixed-axis mirrored bars.

A dense count-grid, B balanced count-grid, C slot-native (65 VisualField slots).
No center line. Same VisualField as the locked ribbon.

    uv run python scripts/spectrum_field_bars_geom.py
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

VARIANTS: tuple[dict[str, object], ...] = (
    {
        "name": "A-dense",
        "field_geometry": "mirrored_bars",
        "bar_count": 233,
        "bar_fill": 0.72,
        "bar_align": "count",
    },
    {
        "name": "B-balanced",
        "field_geometry": "mirrored_bars",
        "bar_count": 117,
        "bar_fill": 0.62,
        "bar_align": "count",
    },
    {
        "name": "C-slots",
        "field_geometry": "mirrored_bars",
        "bar_count": 65,
        "bar_fill": 0.55,
        "bar_align": "slots",
    },
    {
        "name": "R-ribbon",
        "field_geometry": "ribbon",
        "bar_count": None,
        "bar_fill": None,
        "bar_align": None,
    },
)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _extract_png(mov: Path, dest: Path, index: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"frame_{index:04d}.png"
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
        str(out),
    ]
    completed = subprocess.run(argv, check=False, capture_output=True)
    if completed.returncode != 0 or not out.is_file():
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    return out


def _on_black(png: Path, dest: Path) -> Path:
    raw = dest.with_suffix(".raw")
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
            str(dest),
        ],
        check=True,
        capture_output=True,
    )
    return dest


def _run_one(audio: Path, root: Path, spec: dict[str, object]) -> dict[str, object]:
    name = str(spec["name"])
    out_dir = root / name
    wall0 = time.perf_counter()
    results = render(
        audio,
        output_dir=out_dir,
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
        field_geometry=str(spec["field_geometry"]),
        bar_count=spec["bar_count"] if isinstance(spec["bar_count"], int) else None,
        bar_fill=spec["bar_fill"] if isinstance(spec["bar_fill"], float) else None,
        bar_align=str(spec["bar_align"]) if spec["bar_align"] is not None else None,
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
    png = _extract_png(mov, out_dir / "frames", FRAME)
    black = _on_black(png, out_dir / "frames" / f"frame_{FRAME:04d}_black.png")
    perf = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    extras = perf.get("extras") if isinstance(perf, dict) else {}
    seconds = perf.get("seconds") if isinstance(perf, dict) else {}
    return {
        "name": name,
        "wall_s": wall,
        "rtf": wall / DURATION,
        "render_path": extras.get("render_path") if isinstance(extras, dict) else None,
        "geometry": extras.get("fingerprint", {}).get("geometry")
        if isinstance(extras, dict) and isinstance(extras.get("fingerprint"), dict)
        else spec["field_geometry"],
        "bar_count": spec["bar_count"],
        "bar_align": spec["bar_align"],
        "bar_fill": spec["bar_fill"],
        "raster_s": seconds.get("raster") if isinstance(seconds, dict) else None,
        "feed_s": seconds.get("ffmpeg_feed") if isinstance(seconds, dict) else None,
        "bytes_per_frame": extras.get("bytes_per_frame") if isinstance(extras, dict) else None,
        "mov": str(mov),
        "preview": str(black),
        "size_bytes": mov.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", default=str(AUDIO))
    parser.add_argument("--output-root", default="/tmp/ewp-bars-geom")
    args = parser.parse_args()
    audio = normalize_user_path(args.audio)
    root = Path(args.output_root)
    rows = []
    for spec in VARIANTS:
        print(f"=== {spec['name']} ===", flush=True)
        rows.append(_run_one(audio, root, spec))
    print("SUMMARY", json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
