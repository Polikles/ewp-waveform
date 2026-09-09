#!/usr/bin/env python3
"""A/B/C visual experiment: static center-out fold of 64 spectral bands.

Not a public CLI. Temporal-envelope experiments are rejected: X must be
stationary. No dynamic recenter, no scrolling.

A = 64-band B mapping, dominant-region recenter (control)
B = same 64 bands, fixed center-out fold (even left, odd right)
C = B plus mild Gaussian on neighboring visual slots (sigma=1)

Example:

    uv run python scripts/spectrum_fold_abc.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-fold \\
      --duration 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path

# folder, label, recenter, layout, slot_sigma
VARIANTS: tuple[tuple[str, str, bool, str, float], ...] = (
    ("a-recentered-control", "A recentered spectrum control", True, "linear", 0.0),
    ("b-center-out-fold", "B fixed center-out fold", False, "center_out", 0.0),
    ("c-center-out-smooth", "C center-out + slot smooth", False, "center_out", 1.0),
)

B_BANDS = 64
B_TILT_DB = 3.0
B_COMPRESS = 0.75


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _run(
    source: Path,
    *,
    dest: Path,
    start: float,
    duration: float,
    preset: str,
    recenter: bool,
    layout: str,
    slot_sigma: float,
) -> dict[str, object]:
    _progress(f"{dest.name}: render -> {dest}")
    results = render(
        source,
        output_dir=dest,
        preset_name=preset,
        formats=["prores4444"],
        force=True,
        start=start,
        duration=duration,
        spectrum_contour=True,
        spectrum_spatial_scale=1.0,
        spectrum_spatial_filter="gaussian",
        spectrum_n_bands=B_BANDS,
        spectrum_tilt_db_per_octave=B_TILT_DB,
        spectrum_compress=B_COMPRESS,
        spectrum_recenter=recenter,
        spectrum_edge_taper=0.0,
        visual_geometry="spectrum",
        spectrum_layout=layout,
        spectrum_slot_sigma=slot_sigma,
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
    layout = recenter = slot = "?"
    if isinstance(analysis, dict):
        layout = str(analysis.get("spectrum_layout", "?"))
        recenter = str(analysis.get("spectrum_recenter", "?"))
        slot = str(analysis.get("spectrum_slot_sigma", "?"))
    outputs = payload.get("outputs")
    path = ""
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        path = str(outputs[0].get("path", ""))
    print(f"{status}: {label} layout={layout} recenter={recenter} slot_sigma={slot} {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--preset", default="iuris-spectrum")
    args = parser.parse_args()
    source = normalize_user_path(args.input_path)
    output_dir = normalize_user_path(args.output_dir)
    try:
        payloads: list[tuple[str, dict[str, object]]] = []
        for folder, label, recenter, layout, slot_sigma in VARIANTS:
            payload = _run(
                source,
                dest=output_dir / folder,
                start=args.start,
                duration=args.duration,
                preset=args.preset,
                recenter=recenter,
                layout=layout,
                slot_sigma=slot_sigma,
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
