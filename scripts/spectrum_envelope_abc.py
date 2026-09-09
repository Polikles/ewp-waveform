#!/usr/bin/env python3
"""A/B/C visual experiment: recentered spectrum vs centered temporal envelope.

Not a public CLI. Contour, glow, canvas, and auto-gain stay. No frequency tilt
on the temporal path. No edge taper.

A = 64-band B mapping, recentered (current spectrum baseline)
B = centered temporal RMS, 1.5 s window, 64 bins
C = centered temporal RMS+peak (mix 0.3), 1.5 s window, 64 bins

Example:

    uv run python scripts/spectrum_envelope_abc.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-envelope \\
      --duration 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path

# folder, label, geometry, recenter
VARIANTS: tuple[tuple[str, str, str, bool], ...] = (
    ("a-recentered-spectrum", "A recentered spectrum B", "spectrum", True),
    ("b-temporal-rms", "B temporal RMS 1.5s", "temporal_rms", False),
    ("c-temporal-rms-peak", "C temporal RMS+peak 1.5s", "temporal_rms_peak", False),
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
    geometry: str,
    recenter: bool,
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
        spectrum_n_bands=B_BANDS if geometry == "spectrum" else None,
        spectrum_tilt_db_per_octave=B_TILT_DB if geometry == "spectrum" else 0.0,
        spectrum_compress=B_COMPRESS if geometry == "spectrum" else 1.0,
        spectrum_recenter=recenter,
        spectrum_edge_taper=0.0,
        visual_geometry=geometry,
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
    geometry = "?"
    if isinstance(analysis, dict):
        geometry = str(analysis.get("visual_geometry", "?"))
    outputs = payload.get("outputs")
    path = ""
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        path = str(outputs[0].get("path", ""))
    print(f"{status}: {label} geometry={geometry} {path}")


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
        for folder, label, geometry, recenter in VARIANTS:
            payload = _run(
                source,
                dest=output_dir / folder,
                start=args.start,
                duration=args.duration,
                preset=args.preset,
                geometry=geometry,
                recenter=recenter,
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
