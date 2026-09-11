#!/usr/bin/env python3
"""Default mirrored-line combo: T1 thin + G2 open gap + C1 alternate + L2 center line.

    uv run python scripts/spectrum_field_mirrored.py \\
      --audio /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-mirrored-line
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path

START = 25.0
DURATION = 8.0
FRAME = 239


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=START)
    parser.add_argument("--duration", type=float, default=DURATION)
    args = parser.parse_args()
    source = normalize_user_path(args.audio)
    dest = normalize_user_path(args.output_dir)
    try:
        results = render(
            source,
            output_dir=dest,
            preset_name="iuris-spectrum",
            formats=["prores4444"],
            force=True,
            start=args.start,
            duration=args.duration,
            spectrum_contour=True,
            spectrum_spatial_scale=1.0,
            spectrum_spatial_filter="gaussian",
            spectrum_n_bands=64,
            spectrum_tilt_db_per_octave=3.0,
            spectrum_compress=0.75,
            visual_geometry="spectrum",
            spectrum_layout="field_center_out",
            field_geometry="mirrored_bars",
            progress=_progress,
        )
    except AppError as exc:
        print(exc, file=sys.stderr)
        return exc.numeric_exit
    if not results:
        return 1
    payload = results[0]
    outputs = payload.get("outputs")
    mov = Path(str(outputs[0]["path"])) if isinstance(outputs, list) and outputs else None
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    print(
        "mirrored_bars",
        analysis.get("render_path"),
        analysis.get("field_geometry"),
        mov,
    )
    if mov is not None and mov.is_file():
        frames = dest / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        png = frames / f"frame_{FRAME:04d}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(mov),
                "-vf",
                f"select=eq(n\\,{FRAME})",
                "-frames:v",
                "1",
                str(png),
            ],
            check=False,
        )
        print("preview", png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
