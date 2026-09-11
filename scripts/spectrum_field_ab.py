#!/usr/bin/env python3
"""A/B locked ribbon vs VisualField mirrored bars on the 8 s diagnostic clip.

    uv run python scripts/spectrum_field_ab.py \\
      --audio /home/linuch/waveform-rendering/zz-audio-samples/s0e00/s0e00-Damian.wav
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ewp_waveform.application.service import render
from ewp_waveform.paths import normalize_user_path

AUDIO = Path("/home/linuch/waveform-rendering/zz-audio-samples/s0e00/s0e00-Damian.wav")
START = 25.0
DURATION = 8.0
COMPARE = (0, 239, 479)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _extract(mov: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for index in COMPARE:
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


def _render(
    audio: Path,
    out_dir: Path,
    *,
    geometry: str,
    bar_width: float | None,
    bar_gap: float | None,
) -> dict[str, object]:
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
        field_geometry=geometry,
        bar_width=bar_width,
        bar_gap=bar_gap,
        progress=_progress,
    )
    payload = results[0]
    job = payload.get("job")
    if not isinstance(job, dict) or job.get("status") != "SUCCEEDED":
        raise RuntimeError(str(payload.get("warnings")))
    outputs = payload.get("outputs")
    mov = Path(str(outputs[0]["path"])) if isinstance(outputs, list) and outputs else None
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    perf = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    size = mov.stat().st_size if mov is not None and mov.is_file() else 0
    return {
        "geometry": geometry,
        "mov": str(mov) if mov is not None else "",
        "size_bytes": size,
        "render_path": analysis.get("render_path") if isinstance(analysis, dict) else None,
        "field_geometry": analysis.get("field_geometry") if isinstance(analysis, dict) else None,
        "performance": perf,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", default=str(AUDIO))
    parser.add_argument("--output-root", default="/tmp/ewp-field-ab")
    parser.add_argument("--bar-width", type=float, default=5.0)
    parser.add_argument("--bar-gap", type=float, default=3.0)
    args = parser.parse_args()
    audio = normalize_user_path(args.audio)
    root = Path(args.output_root)
    print("=== A ribbon ===", flush=True)
    ribbon = _render(audio, root / "A-ribbon", geometry="ribbon", bar_width=None, bar_gap=None)
    _extract(Path(str(ribbon["mov"])), root / "A-ribbon" / "frames")
    print("=== B mirrored_bars ===", flush=True)
    bars = _render(
        audio,
        root / "B-bars",
        geometry="mirrored_bars",
        bar_width=args.bar_width,
        bar_gap=args.bar_gap,
    )
    _extract(Path(str(bars["mov"])), root / "B-bars" / "frames")
    print("SUMMARY", json.dumps({"A": ribbon, "B": bars}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
