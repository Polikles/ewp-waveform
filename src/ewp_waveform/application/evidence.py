"""Empirical performance fingerprints for later labelled dry-run estimates."""

from __future__ import annotations

import math
import os
import platform
import sys
from dataclasses import asdict, dataclass
from typing import Any

try:
    import resource
except ImportError:  # Native Windows has no Unix resource module.
    resource = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PerformanceFingerprint:
    """Enough to match a later job to measured evidence. Not a predictor."""

    renderer: str
    render_path: str
    visual_style: str
    geometry: str
    glow: bool
    particles: bool
    width: int
    height: int
    fps: float
    aa_mode: str
    supersample: int
    pix_fmt: str
    codec: str
    jobs: int
    ffmpeg_threads: int
    nproc: int | None
    machine: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_from_plan(
    *,
    plan_path: str,
    geometry: str,
    style: str,
    glow: bool,
    particles: bool,
    width: int,
    height: int,
    fps: float,
    aa_mode: str,
    supersample: int,
    pix_fmt: str,
    codec: str,
    jobs: int,
    ffmpeg_threads: int,
    renderer: str = "ffmpeg",
) -> PerformanceFingerprint:
    nproc_raw = os.cpu_count()
    return PerformanceFingerprint(
        renderer=renderer,
        render_path=plan_path,
        visual_style=style,
        geometry=geometry,
        glow=glow,
        particles=particles,
        width=width,
        height=height,
        fps=fps,
        aa_mode=aa_mode,
        supersample=supersample,
        pix_fmt=pix_fmt,
        codec=codec,
        jobs=jobs,
        ffmpeg_threads=ffmpeg_threads,
        nproc=nproc_raw,
        machine=platform.platform(),
    )


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if math.isfinite(result) and result > 0 else None


def render_measurements(
    payload: dict[str, Any], *, planned_action: str, wall_seconds: float, fps: float
) -> dict[str, Any]:
    """Only validated, wholly processed output is a rendering-throughput sample."""
    job = payload.get("job", {})
    status = job.get("status", "UNKNOWN") if isinstance(job, dict) else "UNKNOWN"
    validation = payload.get("validation", {})
    report = validation if isinstance(validation, dict) else {}
    performance = payload.get("performance", {})
    phases = performance if isinstance(performance, dict) else {}
    raw_extras = phases.get("extras", {})
    extras = raw_extras if isinstance(raw_extras, dict) else {}
    duration = _positive_number(extras.get("effective_audio_seconds"))
    frames = _positive_number(report.get("frames"))
    primary_format = (
        "png"
        if report.get("format") == "png"
        else ("prores4444" if report.get("codec") == "prores" else None)
    )
    frames_by_format = {primary_format: report.get("frames")} if primary_format else {}
    if "png_frames" in report:
        frames_by_format["png"] = report["png_frames"]
        if report["png_frames"] != report.get("frames"):
            frames = None  # no common validated dual-format timeline count
    outputs = payload.get("outputs")
    execution = payload.get("execution", {})
    resumed = execution.get("resumed") if isinstance(execution, dict) else None
    eligible = (
        planned_action == "PROCESS"
        and status == "SUCCEEDED"
        and report.get("passed") is True
        and isinstance(outputs, list)
        and bool(outputs)
        and not resumed
        and not extras.get("reused_output_formats")
        and duration is not None
        and frames is not None
        and _positive_number(wall_seconds) is not None
    )
    output_duration = _positive_number(report.get("duration_seconds"))
    duration_basis = "validated MOV metadata" if output_duration is not None else None
    if output_duration is None and report.get("format") == "png" and frames is not None:
        rate = _positive_number(fps)
        if rate is not None:
            output_duration = frames / rate
            duration_basis = "validated PNG frame count / configured fps"
    thread_parameter = extras.get(
        "ffmpeg_threads_resolved_argument", extras.get("ffmpeg_threads_argument")
    )
    thread_role = extras.get("ffmpeg_threads_option_role")
    positive_thread_option = (
        isinstance(thread_parameter, int)
        and not isinstance(thread_parameter, bool)
        and thread_parameter > 0
    )
    return {
        "throughput_available": eligible,
        "throughput_unavailable_reason": None
        if eligible
        else (
            "requires planned PROCESS, actual SUCCEEDED, validated non-reused outputs, "
            "effective duration, validated frame count and positive render wall time"
        ),
        "effective_audio_seconds": duration,
        "clip_start_seconds": extras.get("clip_start_seconds"),
        "expected_frames": extras.get("expected_frames"),
        "validated_output_frames": report.get("frames"),
        "validated_output_frames_by_format": frames_by_format,
        "throughput_frame_count": frames,
        "throughput_frame_count_basis": "validated common output timeline, not summed formats",
        "output_duration_seconds": output_duration,
        "output_duration_basis": duration_basis,
        "duration_drift_seconds": (
            output_duration - duration
            if output_duration is not None and duration is not None
            else None
        ),
        "render_fps": frames / wall_seconds if eligible and frames is not None else None,
        "real_time_factor": (
            wall_seconds / duration if eligible and duration is not None else None
        ),
        "speedup": None,
        "speedup_unavailable_reason": "no paired comparable baseline collected",
        "phases": phases,
        "validation": payload.get("validation"),
        "execution": payload.get("execution"),
        "resume_history": payload.get("resume_history"),
        "warnings": payload.get("warnings"),
        "resolved_performance_config": payload.get("resolved_performance_config"),
        "ffmpeg_threads_resolved_argument": thread_parameter,
        "ffmpeg_threads_option_role": thread_role,
        "ffmpeg_encoder_threads_argument": (
            thread_parameter if positive_thread_option and thread_role == "output_encoder" else None
        ),
        "ffmpeg_decoder_threads_argument": (
            thread_parameter
            if positive_thread_option and thread_role == "input_rawvideo_decoder"
            else None
        ),
        "ffmpeg_threads_argument_scope": (
            "adapter-selected stream parameter; dual outputs apply positive -threads to the "
            "input rawvideo decoder, single output to its encoder; 0 omits the option; "
            "not observed thread counts or a whole-process/filter cap"
        ),
        "analysis_cache_observed": extras.get("analysis_cache"),
        "raw_feed_bytes": extras.get("raw_feed_bytes"),
        "raw_feed_pixel_format": extras.get("raw_feed_pixel_format"),
        "raw_feed_scope": "parent instrumented feeds only; worker feeds unobserved",
    }


def parent_resource_observation() -> dict[str, Any]:
    """RUSAGE_SELF is lifetime parent high-water, never a per-cell delta."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None
    unit = (
        "bytes"
        if sys.platform == "darwin"
        else ("KiB" if sys.platform.startswith("linux") else "platform-defined")
    )
    return {
        "parent_lifetime_ru_maxrss": raw,
        "parent_lifetime_ru_maxrss_unit": unit if resource is not None else None,
        "scope": (
            "RUSAGE_SELF parent process-lifetime high-water sampled after cell"
            if resource is not None
            else "unavailable: this platform has no Unix resource module"
        ),
        "per_cell_peak_rss_bytes": None,
        "process_tree_peak_rss_bytes": None,
        "parent_cpu_seconds": None,
        "child_cpu_seconds": None,
        "normalized_cpu_utilization": None,
        "disk_io_bytes": None,
        "peak_workdir_bytes": None,
        "unavailable_reason": "not collected; no worker/process-tree monitoring",
    }
