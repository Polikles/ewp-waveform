#!/usr/bin/env python3
"""Render the new AnalysisFrame -> VisualField -> filled-ribbon path.

Stationary 65-slot center-out mapping (one visual center). Old recentered
and even/odd fold modes remain available as reference scripts.

    uv run python scripts/spectrum_field_ribbon.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-field \\
      --duration 2.5
"""

from __future__ import annotations

import argparse
import sys

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=2.5)
    parser.add_argument("--preset", default="iuris-spectrum")
    args = parser.parse_args()
    source = normalize_user_path(args.input_path)
    dest = normalize_user_path(args.output_dir)
    try:
        results = render(
            source,
            output_dir=dest,
            preset_name=args.preset,
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
            spectrum_recenter=False,
            spectrum_edge_taper=0.0,
            visual_geometry="spectrum",
            spectrum_layout="field_center_out",
            spectrum_slot_sigma=0.0,
            progress=_progress,
        )
    except AppError as exc:
        print(exc, file=sys.stderr)
        return exc.numeric_exit
    if not results:
        print("no jobs", file=sys.stderr)
        return 1
    payload = results[0]
    job = payload.get("job")
    status = job.get("status") if isinstance(job, dict) else "?"
    analysis = payload.get("analysis")
    pipeline = slots = "?"
    if isinstance(analysis, dict):
        pipeline = str(analysis.get("visual_pipeline", "?"))
        slots = str(analysis.get("visual_slots", "?"))
    outputs = payload.get("outputs")
    path = ""
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        path = str(outputs[0].get("path", ""))
    print(f"{status}: field ribbon pipeline={pipeline} slots={slots} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
