#!/usr/bin/env python3
"""Two-speaker mirrored-line color test (board ``2 mówców.png``).

Speaker 1 (Damian): all white. Speaker 2 (Szymon): all blue.
Same T1+G2+L2 geometry; no intra-bar alternate (solid speaker color).

    uv run python scripts/spectrum_field_speakers.py --duration 8
    uv run python scripts/spectrum_field_speakers.py --duration 0
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
from ewp_waveform.visual.bars import SPEAKER_BLUE, SPEAKER_WHITE

AUDIO_DIR = Path("/home/linuch/waveform-rendering/zz-audio-samples/s0e00")
START = 0.0
FRAME = 239

SPEAKERS: tuple[dict[str, object], ...] = (
    {
        "name": "Damian-white",
        "audio": AUDIO_DIR / "s0e00-Damian.wav",
        "color": SPEAKER_WHITE,
        "alternate": False,
        "color_b": None,
    },
    {
        "name": "Szymon-blue",
        "audio": AUDIO_DIR / "s0e00-Szymon.wav",
        "color": SPEAKER_BLUE,
        "alternate": False,
        "color_b": None,
    },
)


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
    parser.add_argument("--audio-dir", default=str(AUDIO_DIR))
    parser.add_argument("--output-root", default="/tmp/ewp-speakers")
    parser.add_argument("--start", type=float, default=START)
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="0 = full file. Use 8 for a short diagnostic.",
    )
    parser.add_argument("--preview-frame", type=int, default=FRAME)
    args = parser.parse_args()
    audio_dir = Path(args.audio_dir)
    root = Path(args.output_root)
    duration = None if args.duration == 0 else args.duration
    perf = _performance_toml(root / "performance.toml")
    rows = []
    for spec in SPEAKERS:
        name = str(spec["name"])
        audio = audio_dir / Path(str(spec["audio"])).name
        print(f"=== {name} {audio} ===", flush=True)
        wall0 = time.perf_counter()
        results = render(
            normalize_user_path(str(audio)),
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
            bar_alternate=bool(spec["alternate"]),
            bar_color_b=str(spec["color_b"]) if spec["color_b"] is not None else None,
            waveform_color=str(spec["color"]),
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
                "color": spec["color"],
                "alternate": spec["alternate"],
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
