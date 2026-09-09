#!/usr/bin/env python3
"""A/B visual experiment: spectrum column raster vs PCHIP contour.

Not a public CLI. FFT, span, EMA, normalization, and preset schema are unchanged.
Default production spectrum path stays columns (A).

Example (same 8 s clip as the operator preview):

    uv run python scripts/spectrum_contour_ab.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-ab \\
      --duration 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _run(
    source: Path,
    *,
    output_dir: Path,
    contour: bool,
    start: float,
    duration: float,
    preset: str,
) -> dict[str, object]:
    label = "b-contour" if contour else "a-columns"
    dest = output_dir / label
    _progress(f"{label}: render -> {dest}")
    results = render(
        source,
        output_dir=dest,
        preset_name=preset,
        formats=["prores4444"],
        force=True,
        start=start,
        duration=duration,
        spectrum_contour=contour,
        progress=_progress,
    )
    if not results:
        msg = f"{label}: no jobs"
        raise RuntimeError(msg)
    return results[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Audio file (same source for A and B)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--preset", default="iuris-spectrum")
    args = parser.parse_args()
    source = normalize_user_path(args.input_path)
    output_dir = normalize_user_path(args.output_dir)
    try:
        columns = _run(
            source,
            output_dir=output_dir,
            contour=False,
            start=args.start,
            duration=args.duration,
            preset=args.preset,
        )
        contour = _run(
            source,
            output_dir=output_dir,
            contour=True,
            start=args.start,
            duration=args.duration,
            preset=args.preset,
        )
    except AppError as exc:
        print(exc, file=sys.stderr)
        return exc.numeric_exit
    for label, payload in (("A columns", columns), ("B contour", contour)):
        job = payload.get("job")
        status = job.get("status") if isinstance(job, dict) else "?"
        analysis = payload.get("analysis")
        raster = analysis.get("spectrum_raster") if isinstance(analysis, dict) else "?"
        outputs = payload.get("outputs")
        path = ""
        if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
            path = str(outputs[0].get("path", ""))
        print(f"{status}: {label} raster={raster} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
