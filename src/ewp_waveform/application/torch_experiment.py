"""Explicit bounded finishing experiment; never selected by the stock service.

Subprocess contract (JSON report, exit 0 success / 2 unavailable or failed):
  python -m ewp_waveform.application.torch_experiment qualify --backend numpy --report q.json
  python -m ewp_waveform.application.torch_experiment render --backend numpy \
      --source input.wav --start 1 --duration .25 --output independent.mov --report run.json

Render backends: numpy, torch-cpu, cuda, transfer-cuda, ffmpeg. CUDA options use
--device cuda:0. --reference other.mov adds decoded comparative metrics, NOT an
appearance acceptance gate. --preview preview.mp4 creates a separately timed view.
--ffmpeg/--ffprobe pin executable paths (also recorded by hash). Only batch one is
implemented. Source bounds mandatory, <=32s; original production raster only.
Cold external process E2E must be measured by the invoking runner: Python startup
and package/module import precede main() and cannot honestly be measured here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from ewp_waveform.ffmpeg.torch_finish import (
    ALGORITHM,
    FinishSpec,
    TorchFinisher,
    numpy_finish,
    qualify,
)

BACKENDS = ("numpy", "torch-cpu", "cuda", "transfer-cuda", "ffmpeg")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tool(value: str) -> Path:
    located = shutil.which(value)
    if located is None:
        raise ValueError(f"missing executable: {value}")
    return Path(located).resolve()


def render_experiment(
    *,
    source: Path,
    start: float,
    duration: float,
    output: Path,
    backend: str = "numpy",
    device: str = "cuda:0",
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    reference: Path | None = None,
    preview: Path | None = None,
    visual_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh original-input bounded production pipeline, custom finishing seam only.

    output.parent must be a NEW task-owned directory (no overwrite/reuse). Analysis
    cache is explicitly disabled. Independent transparent ProRes4444, same stock
    CPU prores_ks encoder for every backend, no service publication/default changes.
    """
    entered = time.perf_counter()
    if backend not in BACKENDS:
        raise ValueError("unknown finishing backend")
    if not all(math.isfinite(v) for v in (start, duration)) or start < 0 or not 0 < duration <= 32:
        raise ValueError("explicit finite start>=0 and 0<duration<=32 seconds required")
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or output.suffix.lower() != ".mov":
        raise ValueError("existing original audio source and .mov output required")
    if output.parent.exists():
        raise ValueError("output parent must be a fresh task-owned directory")
    if reference is not None and not reference.is_file():
        raise ValueError("reference does not exist")
    if preview is not None:
        preview = preview.resolve()
        if preview.exists() or preview == output:
            raise ValueError("refusing preview overwrite/collision")
    selected_ffmpeg, selected_ffprobe = _tool(ffmpeg), _tool(ffprobe)
    if selected_ffmpeg.parent != selected_ffprobe.parent:
        raise ValueError("ffmpeg and ffprobe must be in the same selected tool directory")
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(selected_ffmpeg.parent) + os.pathsep + old_path
    try:
        from ewp_waveform.application import render as rendering
        from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
        from ewp_waveform.application.render_fixed import FixedHooks, run_fixed_pipeline
        from ewp_waveform.application.service import plan_jobs
        from ewp_waveform.application.timing import PhaseTimes
        from ewp_waveform.ffmpeg import experiment_suite_validation as validation
        from ewp_waveform.ffmpeg.draw import parse_rgb
        from ewp_waveform.ffmpeg.encode import encode_rgba_stream
        from ewp_waveform.ffmpeg.experiments import run_captured
        from ewp_waveform.ffmpeg.process import command_evidence

        # Plan before making directories or allocating GPU memory.
        _, preset, performance, plans, _ = plan_jobs(
            source,
            preset_name="iuris-ribbon-refined",
            performance_name="balanced",
            formats=["prores4444"],
            output_dir=output.parent / "unused-service-output",
            start=start,
            duration=duration,
            force=True,
            **(visual_overrides or {}),
        )
        if len(plans) != 1 or plans[0].action != "PROCESS" or plans[0].media is None:
            raise ValueError("exactly one fresh PROCESS with original media required")
        plan = plans[0]
        assert plan.media is not None
        clip_start, clip_duration = rendering._clip_bounds(plan.media, start, duration)
        expected_frames = max(1, round(clip_duration * plan.job.fps))
        if not 0 < expected_frames <= 1920 or plan.job.fps != 60:
            raise ValueError("bounded 60fps raster route required")
        # Force the serial production branch; do not modify shared performance config.
        performance = performance.model_copy(deep=True)
        performance.processing["jobs"] = 1
        appearance = resolve_fixed_axis_appearance(preset)
        if appearance.field_plan is None or appearance.ribbon_finish is None:
            raise ValueError("production refined ribbon raster/finish not resolved")
        finish = appearance.ribbon_finish
        glow = rendering._glow_sigma(preset)
        spec = FinishSpec(
            width=preset.canvas.width,
            height=preset.canvas.height,
            overscan=rendering.glow_overscan(glow),
            supersample=appearance.field_plan.supersample,
            sigma=glow,
            reflection=finish[0],
            horizon=finish[1],
            thickness=finish[2],
            extent=finish[3],
            opacity=finish[4],
            color=parse_rgb(preset.waveform.color),
        )
        # Qualification is explicit setup, never hidden in a throughput interval.
        qstart = time.perf_counter()
        qualification = qualify(backend, device=device) if backend != "ffmpeg" else None
        qualification_seconds = time.perf_counter() - qstart
        wstart = time.perf_counter()
        worker = (
            TorchFinisher(spec, "cpu" if backend == "torch-cpu" else device)
            if backend in ("torch-cpu", "cuda", "transfer-cuda")
            else None
        )
        worker_setup_seconds = time.perf_counter() - wstart
        output.parent.mkdir(parents=True, exist_ok=False)
        log = output.parent / "commands.jsonl"
        clock = PhaseTimes()
        analysis: dict[str, Any] = {}
        normalization: dict[str, Any] = {}
        original_digest, finished_digest = hashlib.sha256(), hashlib.sha256()
        counters: dict[str, Any] = {
            "frames": 0,
            "original_bytes": 0,
            "finishing_wall_seconds": 0.0,
            "frame_calls": [],
            "numpy_phases": [],
        }

        class Hooks:
            def __getattr__(self, name: str) -> Any:
                return getattr(rendering, name)

            def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def encode_rgba_stream(self, frames: Iterable[bytes], **kwargs: Any) -> None:
                if (
                    kwargs["width"],
                    kwargs["height"],
                    kwargs["overscan"],
                    kwargs["supersample"],
                ) != (spec.width, spec.height, spec.overscan, spec.supersample):
                    raise ValueError("original production raster geometry drift")
                pix_fmt = kwargs["pix_fmt"]

                def observed() -> Iterator[bytes]:
                    for frame in frames:
                        original_digest.update(frame)
                        counters["original_bytes"] += len(frame)
                        counters["frames"] += 1
                        started = time.perf_counter()
                        phases: dict[str, float] = {}
                        if backend == "ffmpeg":
                            yield frame
                            continue
                        if backend == "transfer-cuda":
                            assert worker is not None
                            # Transfer-only device control, followed by identical CPU FIR.
                            result = numpy_finish(
                                worker.transfer(frame, pix_fmt), spec, phases=phases
                            )
                        elif worker is not None:
                            result = worker.finish(frame, pix_fmt)
                        else:
                            result = numpy_finish(frame, spec, pix_fmt, phases=phases)
                        elapsed = time.perf_counter() - started
                        counters["finishing_wall_seconds"] += elapsed
                        counters["frame_calls"].append(elapsed)
                        if phases:
                            counters["numpy_phases"].append(phases)
                        data = result.tobytes()
                        finished_digest.update(data)
                        yield data

                kwargs.update(prores_path=output, png_dir=None)
                if backend != "ffmpeg":
                    # No RGB reblur: finished frames go to the same CPU encoder.
                    kwargs.update(
                        glow=0.0,
                        overscan=0,
                        supersample=1,
                        pix_fmt="rgba",
                        color=None,
                        ribbon_finish=None,
                    )
                encode_started = time.perf_counter()
                encode_rgba_stream(observed(), **kwargs)
                counters["encoder_envelope_wall_seconds"] = time.perf_counter() - encode_started

        class Publication:
            def publish_mov(self, path: Path, *, failure_message: str) -> None:
                if not output.is_file():
                    raise ValueError(failure_message)

            def publish_png(self, path: Path) -> None:
                raise ValueError("PNG service publication not part of finishing experiment")

        source_digest = _hash(source)
        pipeline_start = time.perf_counter()
        with command_evidence(log):
            run_fixed_pipeline(
                cast(FixedHooks, Hooks()),
                job=plan.job,
                media=plan.media,
                preset=preset,
                performance=performance,
                appearance=appearance,
                spectrum_contour=False,
                ribbon_ss=appearance.ribbon_ss,
                source_sha=source_digest,
                clip_start=clip_start,
                clip_duration=clip_duration,
                expected_frames=expected_frames,
                work=output.parent / "work",
                producing_mov=True,
                producing_png=False,
                glow=glow,
                threads=0,
                note=lambda _: None,
                lifecycle=Publication(),
                analysis=analysis,
                normalization=normalization,
                clock=clock,
            )
        pipeline_seconds = time.perf_counter() - pipeline_start
        if counters["frames"] != expected_frames:
            raise ValueError("original raster generator frame count mismatch")
        valid = validation.inspect(
            str(selected_ffmpeg),
            str(selected_ffprobe),
            output,
            width=spec.width,
            height=spec.height,
            frames=expected_frames,
            log=log,
            reference=reference,
        )
        if _hash(source) != source_digest:
            raise ValueError("original source changed during experiment")
        preview_seconds = None
        if preview is not None:
            if preview.exists():
                raise ValueError("refusing preview overwrite")
            preview.parent.mkdir(parents=True, exist_ok=True)
            view_start = time.perf_counter()
            argv = validation.view_argv(
                str(selected_ffmpeg),
                output,
                preview,
                width=spec.width,
                height=spec.height,
                frames=expected_frames,
                background="checker",
            )
            run_captured(argv, log, phase="separate-checker-preview")
            preview_seconds = time.perf_counter() - view_start
            if not preview.is_file() or not preview.stat().st_size:
                raise ValueError("preview missing")
        return {
            "status": "SUCCEEDED",
            "backend": backend,
            "batch_size": 1,
            "algorithm": "production-ffmpeg-recursive-gblur" if backend == "ffmpeg" else ALGORITHM,
            "scope": "BOUNDED_ORIGINAL_PRODUCTION_RASTER_EXPERIMENT_NOT_STOCK_SERVICE",
            "comparison": "FIR CPU vs FIR GPU isolates backend; FIR vs FFmpeg changes algorithm",
            "source": {"path": str(source), "sha256": source_digest},
            "bounds": {
                "requested_start": start,
                "requested_duration": duration,
                "effective_start": clip_start,
                "effective_duration": clip_duration,
                "frames": expected_frames,
            },
            "spec": asdict(spec),
            "visual_overrides": visual_overrides or {},
            "effective_preset": preset.model_dump(mode="json"),
            "encoder_envelope_wall_seconds": counters.get("encoder_envelope_wall_seconds"),
            "encoder_envelope_scope": (
                "inclusive stream-generation/finishing/feed/CPU-ProRes-encode envelope; "
                "overlaps pipeline and finishing; not encoder-exclusive CPU or wall"
            ),
            "exclusive_encoding_wall_seconds": None,
            "analysis_context": "interval-local; no full-source causal history",
            "analysis_cache": "disabled",
            "analysis": analysis,
            "normalization": normalization,
            "qualification": qualification,
            "qualification_seconds": qualification_seconds,
            "worker_setup_seconds": worker_setup_seconds,
            "worker": worker.evidence() if worker else None,
            "pipeline_wall_seconds": pipeline_seconds,
            "pipeline_timer": (
                "production decode/analysis/raster/finish/conversion/CPU encoding; setup excluded"
            ),
            "api_wall_seconds": time.perf_counter() - entered,
            "external_cold_process_wall_seconds": None,
            "cold_timer_note": (
                "runner must time subprocess launch through report/exit; "
                "API excludes package imports"
            ),
            "warmup": (
                "qualification visible outside pipeline; first rendering call retained separately"
            ),
            "encoder": (
                "same selected FFmpeg CPU prores_ks profile4444 yuva444p10le for all backends"
            ),
            "original_raster_sha256": original_digest.hexdigest(),
            "finished_rgba_sha256": finished_digest.hexdigest() if backend != "ffmpeg" else None,
            "raster_feed": counters,
            "output": str(output),
            "output_sha256": _hash(output),
            "output_bytes": output.stat().st_size,
            "validation": valid,
            "preview": str(preview) if preview else None,
            "preview_seconds": preview_seconds,
            "tools": {
                "ffmpeg": {"path": str(selected_ffmpeg), "sha256": _hash(selected_ffmpeg)},
                "ffprobe": {"path": str(selected_ffprobe), "sha256": _hash(selected_ffprobe)},
            },
            "visual_acceptance": "PENDING",
            "nle_acceptance": "PENDING",
        }
    finally:
        os.environ["PATH"] = old_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("qualify", "render"))
    parser.add_argument("--backend", choices=BACKENDS, default="numpy")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--start", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("report already exists; use a fresh attempt namespace")
    started = time.perf_counter()
    try:
        if args.action == "qualify":
            result = qualify(args.backend, device=args.device)
        else:
            if any(v is None for v in (args.source, args.start, args.duration, args.output)):
                raise ValueError("render requires --source --start --duration --output")
            result = render_experiment(
                source=args.source,
                start=args.start,
                duration=args.duration,
                output=args.output,
                backend=args.backend,
                device=args.device,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                reference=args.reference,
                preview=args.preview,
            )
        code = 0
    except (Exception, KeyboardInterrupt) as exc:
        result = {
            "status": "FAILED_OR_UNAVAILABLE",
            "backend": args.backend,
            "gpu_qualified": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        code = 2
    result["main_wall_seconds"] = time.perf_counter() - started
    result["python_executable"] = sys.executable
    result["python_version"] = sys.version
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({"report": str(args.report), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
