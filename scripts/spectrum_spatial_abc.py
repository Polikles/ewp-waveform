#!/usr/bin/env python3
"""A/B/C visual experiment: log-Hz spatial Gaussian scale, contour raster.

Not a public CLI. FFT, span, amplitude scale, temporal EMA, glow, and PCHIP
contour interpolation are unchanged. Production spectrum stays 3-box spatial
smoothing + column raster.

A = current spatial scale as a true Gaussian (sigma = width/200)
B = 2x that sigma
C = 3.5x that sigma (in the 3-4x range)

Example (same 8 s clip as the contour A/B):

    uv run python scripts/spectrum_spatial_abc.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-spatial \\
      --duration 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path

VARIANTS: tuple[tuple[str, str, float], ...] = (
    ("a-spatial-1x", "A gaussian 1x (current scale)", 1.0),
    ("b-spatial-2x", "B gaussian 2x", 2.0),
    ("c-spatial-3p5x", "C gaussian 3.5x", 3.5),
)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _run(
    source: Path,
    *,
    dest: Path,
    start: float,
    duration: float,
    preset: str,
    spatial_scale: float,
) -> dict[str, object]:
    _progress(f"{dest.name}: render -> {dest} (gaussian x{spatial_scale:g})")
    results = render(
        source,
        output_dir=dest,
        preset_name=preset,
        formats=["prores4444"],
        force=True,
        start=start,
        duration=duration,
        spectrum_contour=True,
        spectrum_spatial_scale=spatial_scale,
        spectrum_spatial_filter="gaussian",
        progress=_progress,
    )
    if not results:
        msg = f"{dest.name}: no jobs"
        raise RuntimeError(msg)
    return results[0]


def _print_result(label: str, payload: dict[str, object]) -> None:
    job = payload.get("job")
    status = job.get("status") if isinstance(job, dict) else "?"
    analysis = payload.get("analysis")
    raster = "?"
    filt = "?"
    sigma = "?"
    scale = "?"
    if isinstance(analysis, dict):
        raster = str(analysis.get("spectrum_raster", "?"))
        filt = str(analysis.get("spectrum_spatial_filter", "?"))
        sigma = str(analysis.get("spectrum_spatial_sigma", "?"))
        scale = str(analysis.get("spectrum_spatial_scale", "?"))
    outputs = payload.get("outputs")
    path = ""
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        path = str(outputs[0].get("path", ""))
    print(f"{status}: {label} raster={raster} filter={filt} scale={scale} sigma={sigma} {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Audio file (same source for A/B/C)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--preset", default="iuris-spectrum")
    args = parser.parse_args()
    source = normalize_user_path(args.input_path)
    output_dir = normalize_user_path(args.output_dir)
    try:
        payloads: list[tuple[str, dict[str, object]]] = []
        for folder, label, scale in VARIANTS:
            payload = _run(
                source,
                dest=output_dir / folder,
                start=args.start,
                duration=args.duration,
                preset=args.preset,
                spatial_scale=scale,
            )
            payloads.append((label, payload))
    except AppError as exc:
        print(exc, file=sys.stderr)
        return exc.numeric_exit
    for label, payload in payloads:
        _print_result(label, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
