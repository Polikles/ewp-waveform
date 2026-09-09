#!/usr/bin/env python3
"""A/B/C visual experiment: spectral mapping before contour raster.

Not a public CLI. Contour raster, glow, temporal EMA, and auto-gain stay.
Production mapping remains pixel log-resample + 3-box spatial.

A = current mapping (pixel log-resample) + contour + Gaussian 1x
B = 64 log-RMS bands + moderate tilt/compression
C = 32 log-RMS bands + stronger tilt/compression

Example:

    uv run python scripts/spectrum_mapping_abc.py \\
      /mnt/d/podkast/remaster/mp4test/s0e00.wav \\
      --output-dir /mnt/d/podkast/remaster/mp4test/output-test-spectrum-mapping \\
      --duration 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ewp_waveform.application.service import AppError, render
from ewp_waveform.paths import normalize_user_path

# folder, label, n_bands, tilt_db/oct, compress
VARIANTS: tuple[tuple[str, str, int | None, float, float], ...] = (
    ("a-mapping-current", "A current mapping", None, 0.0, 1.0),
    ("b-mapping-64-tilt", "B 64 bands + moderate tilt", 64, 3.0, 0.75),
    ("c-mapping-32-tilt", "C 32 bands + stronger tilt/compress", 32, 5.0, 0.55),
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
    n_bands: int | None,
    tilt_db: float,
    compress: float,
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
        spectrum_n_bands=n_bands,
        spectrum_tilt_db_per_octave=tilt_db,
        spectrum_compress=compress,
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
    bands = tilt = compress = "?"
    if isinstance(analysis, dict):
        bands = str(analysis.get("spectrum_n_bands"))
        tilt = str(analysis.get("spectrum_tilt_db_per_octave"))
        compress = str(analysis.get("spectrum_compress"))
    outputs = payload.get("outputs")
    path = ""
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        path = str(outputs[0].get("path", ""))
    print(f"{status}: {label} bands={bands} tilt={tilt} compress={compress} {path}")


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
        for folder, label, n_bands, tilt, compress in VARIANTS:
            payload = _run(
                source,
                dest=output_dir / folder,
                start=args.start,
                duration=args.duration,
                preset=args.preset,
                n_bands=n_bands,
                tilt_db=tilt,
                compress=compress,
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
