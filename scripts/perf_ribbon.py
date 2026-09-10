#!/usr/bin/env python3
"""Time the fixed-axis VisualField ribbon path on a short speech clip.

    uv run python scripts/perf_ribbon.py \\
      --audio /home/linuch/waveform-rendering/zz-audio-samples/s0e00/s0e00-Damian.wav \\
      --ss 12 --repeats 1 --extract-frames
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

from ewp_waveform.application.service import render
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE
from ewp_waveform.paths import normalize_user_path

AUDIO = Path("/home/linuch/waveform-rendering/zz-audio-samples/s0e00/s0e00-Damian.wav")
# First continuous speech on this track; 0-8s is near-silence.
START = 25.0
DURATION = 8.0
COMPARE_FRAMES = (0, 239, 479)


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _extract_one(mov: Path, index: int, dest: Path, *, png: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if png:
        out = dest / f"frame_{index:04d}.png"
        fmt = ["-frames:v", "1", str(out)]
    else:
        out = dest / f"frame_{index:04d}.raw"
        fmt = ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", str(out)]
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
        *fmt,
    ]
    completed = subprocess.run(argv, check=False, capture_output=True)
    if completed.returncode != 0 or not out.is_file() or out.stat().st_size <= 0:
        msg = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(msg or f"failed to extract frame {index}")
    return out


def _extract_frames(mov: Path, dest: Path) -> list[Path]:
    png_dir = dest / "png"
    paths: list[Path] = []
    for index in COMPARE_FRAMES:
        paths.append(_extract_one(mov, index, dest, png=False))
        _extract_one(mov, index, png_dir, png=True)
    return paths


def _mae(left: Path, right: Path) -> tuple[float, int]:
    a = left.read_bytes()
    b = right.read_bytes()
    n = min(len(a), len(b))
    if n == 0 or len(a) != len(b):
        return 1.0, abs(len(a) - len(b))
    acc = 0
    diff = 0
    for i in range(n):
        d = abs(a[i] - b[i])
        acc += d
        if d:
            diff += 1
    return acc / (n * 255.0), diff


def _cpu_times() -> tuple[float, float]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (
        self_usage.ru_utime + child_usage.ru_utime,
        self_usage.ru_stime + child_usage.ru_stime,
    )


def _performance_toml(jobs: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "\n".join(
            [
                "schema_version = 1",
                f'name = "perf-jobs-{max(1, jobs)}"',
                "[processing]",
                "chunk_seconds = 60",
                f"jobs = {max(1, jobs)}",
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


def _run_once(audio: Path, out_dir: Path, ss: int, jobs: int) -> dict[str, object]:
    user0, sys0 = _cpu_times()
    wall0 = time.perf_counter()
    perf_toml = _performance_toml(jobs, out_dir / "performance.toml")
    results = render(
        audio,
        output_dir=out_dir,
        preset_name="iuris-spectrum",
        performance_name=str(perf_toml),
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
        spectrum_recenter=False,
        spectrum_edge_taper=0.0,
        visual_geometry="spectrum",
        spectrum_layout="field_center_out",
        ribbon_supersample=ss,
        progress=_progress,
    )
    wall = time.perf_counter() - wall0
    user1, sys1 = _cpu_times()
    user_s = user1 - user0
    sys_s = sys1 - sys0
    payload = results[0]
    job = payload.get("job")
    status = job.get("status") if isinstance(job, dict) else "?"
    if status != "SUCCEEDED":
        raise RuntimeError(str(payload.get("warnings")))
    outputs = payload.get("outputs")
    mov = Path(str(outputs[0]["path"])) if isinstance(outputs, list) and outputs else None
    perf = payload.get("performance")
    cpu_s = user_s + sys_s
    return {
        "wall_s": wall,
        "cpu_s": cpu_s,
        "user_s": user_s,
        "sys_s": sys_s,
        "cpu_util": (cpu_s / wall) if wall > 0 else 0.0,
        "nproc": os.cpu_count(),
        "performance": perf,
        "mov": str(mov) if mov is not None else "",
        "duration_s": (payload.get("timestamps") or {}).get("duration_seconds")
        if isinstance(payload.get("timestamps"), dict)
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", default=str(AUDIO))
    parser.add_argument("--output-root", default="/tmp/ewp-ribbon-perf")
    parser.add_argument("--ss", type=int, default=RIBBON_SUPERSAMPLE)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--extract-frames", action="store_true")
    parser.add_argument("--compare-dir", default="")
    args = parser.parse_args()
    audio = normalize_user_path(args.audio)
    root = Path(args.output_root)
    runs: list[dict[str, object]] = []
    for i in range(max(1, args.repeats)):
        out = root / f"ss{args.ss}" / f"run{i + 1}"
        print(
            f"=== ss={args.ss} jobs={args.jobs} run {i + 1}/{args.repeats} -> {out}",
            flush=True,
        )
        runs.append(_run_once(audio, out, args.ss, args.jobs))
        print(
            json.dumps(
                {
                    "wall_s": runs[-1]["wall_s"],
                    "cpu_s": runs[-1]["cpu_s"],
                    "cpu_util": runs[-1]["cpu_util"],
                    "performance": runs[-1]["performance"],
                }
            )
        )
    walls = [float(run["wall_s"]) for run in runs]
    summary = {
        "ss": args.ss,
        "jobs": args.jobs,
        "repeats": len(runs),
        "wall_s": {"min": min(walls), "median": statistics.median(walls), "max": max(walls)},
        "runs": runs,
    }
    if args.extract_frames:
        last_mov = Path(str(runs[-1]["mov"]))
        frames_dir = root / f"ss{args.ss}" / "frames"
        extracted = _extract_frames(last_mov, frames_dir)
        summary["frames"] = [str(path) for path in extracted]
        if args.compare_dir:
            base = Path(args.compare_dir)
            diffs = []
            for path in extracted:
                other = base / path.name
                mae, ndiff = _mae(path, other)
                diffs.append({"frame": path.name, "mae": mae, "nbytes_diff": ndiff})
            summary["vs_baseline"] = diffs
    print("SUMMARY", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
