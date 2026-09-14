#!/usr/bin/env python3
"""Per-track solid colors on the default mirrored-line geometry.

    uv run python scripts/spectrum_field_speakers.py \\
      --audio /path/to/speaker-a.wav --color '#6E7BA7' \\
      --audio /path/to/speaker-b.wav --color '#FFFFFF' \\
      --output-root /path/to/output --duration 0
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
from ewp_waveform.visual.style_defaults import BLUE, WHITE

START = 0.0
FRAME = 239
DEFAULT_COLORS = (BLUE, WHITE)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _performance_toml(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'name = "speakers-serial"',
                "[processing]",
                "chunk_seconds = 60",
                "jobs = 1",
                "ffmpeg_threads = 0",
                "[workdirs]",
                "persistent = false",
                "keep_on_success = false",
                "keep_on_failure = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return dest


def _preview(mov: Path, dest: Path, index: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    png = dest / f"frame_{index:04d}.png"
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
            f"select=eq(n\\,{index})",
            "-frames:v",
            "1",
            str(png),
        ],
        check=False,
        capture_output=True,
    )
    return png


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", action="append", required=True, help="Repeat per track")
    parser.add_argument(
        "--color",
        action="append",
        default=[],
        help="Repeat per track. Defaults: blue then white.",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start", type=float, default=START)
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="0 = full file. Use 8 for a short diagnostic.",
    )
    parser.add_argument("--preview-frame", type=int, default=FRAME)
    args = parser.parse_args()
    root = Path(args.output_root)
    duration = None if args.duration == 0 else args.duration
    perf = _performance_toml(root / "performance.toml")
    rows = []
    for index, audio in enumerate(args.audio):
        color = args.color[index] if index < len(args.color) else DEFAULT_COLORS[index % 2]
        name = Path(audio).stem
        print(f"=== {name} {color} ===", flush=True)
        wall0 = time.perf_counter()
        results = render(
            normalize_user_path(audio),
            output_dir=root / name,
            preset_name="iuris-spectrum",
            performance_name=str(perf),
            formats=["prores4444"],
            force=True,
            start=args.start if args.start > 0 else None,
            duration=duration,
            spectrum_contour=True,
            spectrum_spatial_scale=1.0,
            spectrum_spatial_filter="gaussian",
            spectrum_n_bands=64,
            spectrum_tilt_db_per_octave=3.0,
            spectrum_compress=0.75,
            visual_geometry="spectrum",
            spectrum_layout="field_center_out",
            field_geometry="mirrored_bars",
            bar_alternate=False,
            waveform_color=color,
            progress=_progress,
        )
        wall = time.perf_counter() - wall0
        payload = results[0]
        outputs = payload.get("outputs")
        mov = Path(str(outputs[0]["path"])) if isinstance(outputs, list) and outputs else None
        preview = _preview(mov, root / name / "frames", args.preview_frame) if mov else None
        rows.append(
            {
                "name": name,
                "color": color,
                "wall_s": wall,
                "mov": str(mov) if mov else "",
                "size_bytes": mov.stat().st_size if mov and mov.is_file() else 0,
                "preview": str(preview) if preview else "",
            }
        )
    print("SUMMARY", json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
