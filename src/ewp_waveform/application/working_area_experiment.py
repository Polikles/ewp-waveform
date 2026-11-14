"""Bounded original-audio compact-area API; not a stock service or production profile.

Parent supervisors call render_working_area for CPU-BASE / CROP-OUT / EARLY-AREA
with the SAME frozen WorkingArea and original audio bounds. No input master is
accepted for rendering. A full-canvas raw RGBA validation reference is optional,
read only AFTER pipeline timing. Parent owns resource/process-tree admission and
external launch-through-exit timing. Short outputs still need appearance/Resolve
acceptance; no full-source performance campaign is launched by this module.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, cast

from ewp_waveform.ffmpeg.experiments import inspect_master
from ewp_waveform.ffmpeg.working_area import CONTROLS, WorkingArea, encode_working_area


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tool(value: str) -> Path:
    found = shutil.which(value)
    if found is None:
        raise ValueError(f"missing executable: {value}")
    return Path(found).resolve()


def render_working_area(
    *,
    source: Path,
    start: float,
    duration: float,
    output: Path,
    area: WorkingArea,
    control: str,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    visual_overrides: dict[str, Any] | None = None,
    validation_reference_rgba: Path | None = None,
) -> dict[str, Any]:
    """Fresh serial production analysis/raster; only finishing/export seam changes.

    Require a NEW output.parent and explicit finite bounds <=32s. Analysis cache
    is disabled for all controls; interval-local production analysis is unchanged.
    The rectangle is caller-frozen for the whole clip (never frame-adaptive).
    No auto-discovery from rendered masters and no throughput using decoded RGBA.
    The API temporarily pins PATH, so calls must be serial or process-isolated.
    """
    entered = time.perf_counter()
    if control not in CONTROLS:
        raise ValueError("unknown compact-area control")
    if not all(math.isfinite(v) for v in (start, duration)) or start < 0 or not 0 < duration <= 32:
        raise ValueError("explicit finite start>=0 and 0<duration<=32 seconds required")
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source.suffix.lower() not in {
        ".wav",
        ".flac",
        ".mp3",
        ".m4a",
        ".ogg",
        ".aiff",
        ".aif",
    }:
        raise ValueError("original audio file required; rendered-master input forbidden")
    if output.suffix.lower() != ".mov" or output.parent.exists():
        raise ValueError(".mov in fresh task-owned output parent required")
    if validation_reference_rgba is not None and not validation_reference_rgba.is_file():
        raise ValueError("validation-only raw RGBA reference missing")
    selected_ffmpeg, selected_ffprobe = _tool(ffmpeg), _tool(ffprobe)
    if selected_ffmpeg.parent != selected_ffprobe.parent:
        raise ValueError("same-directory FFmpeg/ffprobe tool pair required")
    previous_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(selected_ffmpeg.parent) + os.pathsep + previous_path
    try:
        from ewp_waveform.application import render as rendering
        from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
        from ewp_waveform.application.render_fixed import FixedHooks, run_fixed_pipeline
        from ewp_waveform.application.service import plan_jobs
        from ewp_waveform.application.timing import PhaseTimes
        from ewp_waveform.ffmpeg.process import command_evidence

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
            raise ValueError("exactly one fresh original-audio PROCESS required")
        plan = plans[0]
        assert plan.media is not None
        if (preset.canvas.width, preset.canvas.height) != (
            area.crop.canvas_width,
            area.crop.canvas_height,
        ):
            raise ValueError("frozen crop canvas differs from production preset")
        clip_start, clip_duration = rendering._clip_bounds(plan.media, start, duration)
        expected_frames = max(1, round(clip_duration * plan.job.fps))
        if plan.job.fps != 60 or not 0 < expected_frames <= 1920:
            raise ValueError("bounded 60fps route required")
        if validation_reference_rgba is not None and validation_reference_rgba.stat().st_size != (
            expected_frames * preset.canvas.width * preset.canvas.height * 4
        ):
            raise ValueError("validation-only raw reference frame count/geometry mismatch")
        performance = performance.model_copy(deep=True)
        performance.processing["jobs"] = 1
        appearance = resolve_fixed_axis_appearance(preset)
        if appearance.field_plan is None or appearance.ribbon_finish is None:
            raise ValueError("production refined ribbon field/finish required")
        supersample = appearance.field_plan.supersample
        glow = rendering._glow_sigma(preset)
        pad = rendering.glow_overscan(glow)
        # Earlier-domain refusal must precede output allocation and analysis.
        metadata = area.record(pad, glow, control)
        output.parent.mkdir(parents=True, exist_ok=False)
        log = output.parent / "commands.jsonl"
        clock = PhaseTimes()
        analysis: dict[str, Any] = {}
        normalization: dict[str, Any] = {}
        raster_digest = hashlib.sha256()
        counters: dict[str, Any] = {"frames": 0, "bytes": 0}

        class Hooks:
            def __getattr__(self, name: str) -> Any:
                return getattr(rendering, name)

            def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def encode_rgba_stream(self, frames: Iterable[bytes], **kwargs: Any) -> None:
                geometry = (
                    kwargs["width"],
                    kwargs["height"],
                    kwargs["overscan"],
                    kwargs["supersample"],
                )
                if geometry != (
                    preset.canvas.width,
                    preset.canvas.height,
                    pad,
                    supersample,
                ):
                    raise ValueError("original production raster geometry drift")
                if (
                    kwargs.get("pix_fmt") != "gray"
                    or kwargs.get("ribbon_finish") != appearance.ribbon_finish
                ):
                    raise ValueError("original production finishing selection drift")
                kwargs.pop("prores_path")
                if kwargs.pop("png_dir") is not None:
                    raise ValueError("compact-area route supports single MOV only")
                if kwargs.pop("png_start_number", 1) != 1 or kwargs.get("experiment") is not None:
                    raise ValueError("chunked/combined experiment unsupported")
                kwargs.pop("experiment", None)
                size = (
                    (preset.canvas.width + 2 * pad) * supersample * (preset.canvas.height + 2 * pad)
                )

                def observed() -> Iterator[bytes]:
                    for frame in frames:
                        if len(frame) != size:
                            raise ValueError("incomplete original gray raster frame")
                        raster_digest.update(frame)
                        counters["frames"] += 1
                        counters["bytes"] += len(frame)
                        yield frame

                started = time.perf_counter()
                encode_working_area(
                    observed(),
                    area=area,
                    control=control,
                    output=output,
                    ffmpeg=str(selected_ffmpeg),
                    command_log=log,
                    **kwargs,
                )
                counters["encode_envelope_seconds"] = time.perf_counter() - started

        class Publication:
            def publish_mov(self, path: Path, *, failure_message: str) -> None:
                if not output.is_file():
                    raise ValueError(failure_message)

            def publish_png(self, path: Path) -> None:
                raise ValueError("PNG publication unsupported")

        source_digest = _hash(source)
        started = time.perf_counter()
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
        pipeline_seconds = time.perf_counter() - started
        if counters["frames"] != expected_frames:
            raise ValueError("original production raster count mismatch")
        w, h = metadata["output_size"]
        valid = inspect_master(
            str(selected_ffmpeg),
            str(selected_ffprobe),
            output,
            width=w,
            height=h,
            fps=str(plan.job.fps),
            frames=expected_frames,
            candidate="CPU-BASE",
            command_log=log,
            reference=validation_reference_rgba,
            crop=area.crop if control != "CPU-BASE" else None,
        )
        valid["comparison_available"] = validation_reference_rgba is not None
        if validation_reference_rgba is None:
            for key in (
                "union_pixels",
                "alpha_union_mae",
                "rgb_union_mae",
                "edge_alpha_mae",
                "halo_alpha_mae",
                "composite_union_mae",
            ):
                valid[key] = None
        if _hash(source) != source_digest:
            raise ValueError("original source changed")
        result = {
            "status": "SUCCEEDED",
            "control": control,
            "scope": "BOUNDED_ORIGINAL_PRODUCTION_ANALYSIS_RASTER_COMPACT_AREA_EXPERIMENT",
            "source": {"path": str(source), "sha256": source_digest},
            "bounds": {
                "requested_start": start,
                "requested_duration": duration,
                "effective_start": clip_start,
                "effective_duration": clip_duration,
                "frames": expected_frames,
            },
            "area": metadata,
            "effective_preset": preset.model_dump(mode="json"),
            "visual_overrides": visual_overrides or {},
            "ribbon_finish": list(appearance.ribbon_finish),
            "glow": glow,
            "overscan": pad,
            "supersample": supersample,
            "analysis_cache": "disabled",
            "analysis_context": "interval-local production analysis",
            "analysis": analysis,
            "normalization": normalization,
            "original_raster_sha256": raster_digest.hexdigest(),
            "raster_feed": counters,
            "pipeline_wall_seconds": pipeline_seconds,
            "pipeline_timer": (
                "decode/analysis/raster/full-mask feed/finishing/CPU ProRes through exit; "
                "excludes setup and validation"
            ),
            "encode_envelope_scope": (
                "inclusive raster generation/feed/finishing/encoding; "
                "overlaps pipeline, not encoder-only"
            ),
            "exclusive_encoding_wall_seconds": None,
            "external_cold_process_wall_seconds": None,
            "validation": valid,
            "validation_reference_rgba": str(validation_reference_rgba)
            if validation_reference_rgba
            else None,
            "output": str(output),
            "output_sha256": _hash(output),
            "output_bytes": output.stat().st_size,
            "tools": {
                "ffmpeg": {"path": str(selected_ffmpeg), "sha256": _hash(selected_ffmpeg)},
                "ffprobe": {"path": str(selected_ffprobe), "sha256": _hash(selected_ffprobe)},
            },
            "visual_acceptance": "PENDING",
            "resolve_acceptance": "PENDING",
            "production_promotion": False,
        }
        result["api_wall_seconds"] = time.perf_counter() - entered
        return result
    finally:
        os.environ["PATH"] = previous_path
