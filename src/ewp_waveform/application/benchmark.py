"""Benchmark matrix expansion and execution (docs/13, FR-BENCH-*)."""

from __future__ import annotations

import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ewp_waveform.application.capability import capability_for_preset
from ewp_waveform.application.estimate import ESTIMATE_LABEL, estimate_output_mb
from ewp_waveform.application.evidence import parent_resource_observation, render_measurements
from ewp_waveform.application.formats import validate_output_formats
from ewp_waveform.application.plan import plan_destinations_for_job
from ewp_waveform.application.render import render_job
from ewp_waveform.application.results import utc_now, write_run_summary
from ewp_waveform.config.load import load_benchmark_manifest, load_performance, load_preset
from ewp_waveform.config.models import BenchmarkManifest, BenchmarkVariant, VisualPreset
from ewp_waveform.domain.diagnostics import CapabilityLevel
from ewp_waveform.domain.grouping import ids_for_path
from ewp_waveform.domain.models import PlannedJob, TimeMode, VisualizationDomain
from ewp_waveform.ffmpeg.probe import ProbeError, probe_media
from ewp_waveform.ffmpeg.process import ToolNotFoundError, require_tool, run_argv
from ewp_waveform.identity import sha256_file

OVERRIDE_KEYS = frozenset(
    {
        "style",
        "color",
        "amplitude",
        "fps",
        "glow",
        "domain",
        "time_mode",
        "window_seconds",
        "stroke_width",
        "center_line",
        "classic_alternate_opacity",
    }
)


def _as_float(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"override '{key}' must be a number"
        raise ValueError(msg)
    return float(value)


def _planned_job(path: Path, preset: VisualPreset, separator: str = "-") -> PlannedJob:
    project_id, track_id = ids_for_path(path, separator)
    cap_level, cap_notes = capability_for_preset(preset)
    time_mode = TimeMode(preset.waveform.time_mode) if preset.waveform.time_mode else None
    return PlannedJob(
        path=path,
        project_id=project_id,
        track_id=track_id,
        preset=preset.name,
        domain=VisualizationDomain(preset.waveform.domain),
        time_mode=time_mode,
        style=preset.waveform.style,
        fps=preset.canvas.fps,
        capability=cap_level,
        capability_notes=cap_notes,
    )


@dataclass(frozen=True)
class BenchmarkCell:
    input_path: Path
    variant_name: str
    renderer: str
    performance_name: str
    formats: list[str]
    preset: VisualPreset
    action: str
    mov_path: Path | None = None
    png_path: Path | None = None
    duration_seconds: float | None = None
    estimated_output_mb: float | None = None
    estimate_label: str | None = None
    notes: str = ""
    output_dir: Path | None = None


def apply_overrides(
    preset: VisualPreset, overrides: dict[str, object], variant_name: str
) -> VisualPreset:
    """In-memory copy only. Never writes canonical preset files (FR-BENCH-010)."""
    unknown = sorted(key for key in overrides if key not in OVERRIDE_KEYS)
    if unknown:
        msg = f"unknown variant override(s): {', '.join(unknown)}"
        raise ValueError(msg)
    clone = preset.model_copy(deep=True)
    waveform = clone.waveform.model_copy()
    canvas = clone.canvas.model_copy()
    effects = dict(clone.effects)
    signal = dict(clone.signal)
    if "style" in overrides:
        waveform.style = str(overrides["style"])
    if "color" in overrides:
        waveform.color = str(overrides["color"])
    if "amplitude" in overrides:
        waveform.amplitude = _as_float(overrides["amplitude"], "amplitude")
    if "stroke_width" in overrides:
        waveform.stroke_width = _as_float(overrides["stroke_width"], "stroke_width")
    if "center_line" in overrides:
        waveform.center_line = bool(overrides["center_line"])
    if "domain" in overrides:
        waveform.domain = str(overrides["domain"])
    if "time_mode" in overrides:
        waveform.time_mode = str(overrides["time_mode"])
    if "window_seconds" in overrides:
        waveform.window_seconds = _as_float(overrides["window_seconds"], "window_seconds")
    if "fps" in overrides:
        canvas.fps = _as_float(overrides["fps"], "fps")
    if "glow" in overrides:
        glow_raw = effects.get("glow")
        glow = dict(glow_raw) if isinstance(glow_raw, dict) else {}
        level = str(overrides["glow"])
        glow["level"] = level
        glow["enabled"] = level != "none"
        effects["glow"] = glow
    if "classic_alternate_opacity" in overrides:
        opacity = _as_float(overrides["classic_alternate_opacity"], "classic_alternate_opacity")
        if not 0.0 <= opacity <= 1.0:
            msg = "override 'classic_alternate_opacity' must be between 0 and 1"
            raise ValueError(msg)
        signal["classic_alternate_opacity"] = opacity
    clone.waveform = waveform
    clone.canvas = canvas
    clone.effects = effects
    clone.signal = signal
    clone.name = f"{preset.name}--{variant_name}"
    return clone


def _variant_preset(variant: BenchmarkVariant, manifest_dir: Path) -> VisualPreset:
    if variant.preset_file:
        path = Path(variant.preset_file)
        if not path.is_absolute():
            path = manifest_dir / path
        base = load_preset(str(path))
    elif variant.preset:
        base = load_preset(variant.preset)
    else:
        msg = f"variant '{variant.name}' needs preset or preset_file"
        raise ValueError(msg)
    if not variant.overrides:
        clone = base.model_copy(deep=True)
        clone.name = f"{base.name}--{variant.name}"
        return clone
    return apply_overrides(base, variant.overrides, variant.name)


def expand_benchmark(
    manifest: BenchmarkManifest,
    *,
    manifest_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> list[BenchmarkCell]:
    validate_output_formats(manifest.benchmark.formats)
    if not manifest.inputs or not manifest.variants or not manifest.benchmark.renderers:
        msg = "benchmark matrix is empty"
        raise ValueError(msg)
    profiles = manifest.benchmark.performance_profiles or ["balanced"]
    formats = list(manifest.benchmark.formats)
    cells: list[BenchmarkCell] = []
    for item in manifest.inputs:
        source = Path(item.path)
        for variant in manifest.variants:
            preset = _variant_preset(variant, manifest_dir)
            for renderer in manifest.benchmark.renderers:
                for profile_name in profiles:
                    cell_root = output_dir / "cells" / f"cell-{len(cells):06d}"
                    action = "PROCESS"
                    notes = ""
                    if renderer != "ffmpeg":
                        action = "UNSUPPORTED"
                        notes = f"renderer '{renderer}' is not available in the FFmpeg MVP"
                    duration: float | None = None
                    mov: Path | None = None
                    png: Path | None = None
                    estimate: float | None = None
                    label: str | None = None
                    if action == "PROCESS" and source.is_file():
                        try:
                            media = probe_media(source)
                            duration = media.duration_seconds
                            source_sha = sha256_file(source)
                            job = _planned_job(source, preset)
                            planned = plan_destinations_for_job(
                                job,
                                preset,
                                source_sha256=source_sha,
                                output_dir=cell_root / "output",
                                formats=formats,
                                force=force,
                            )
                            action = planned.action
                            mov = planned.mov_path
                            png = planned.png_path
                            if job.capability == CapabilityLevel.UNSUPPORTED:
                                action = "UNSUPPORTED"
                                notes = job.capability_notes
                        except (ToolNotFoundError, ProbeError, OSError, ValueError) as exc:
                            action = "BLOCKED"
                            notes = str(exc)
                    elif action == "PROCESS":
                        action = "BLOCKED"
                        notes = f"missing input {source}"
                    if (
                        manifest.benchmark.dry_run_estimates
                        and duration is not None
                        and duration > 0
                    ):
                        estimate = estimate_output_mb(duration, preset, formats)
                        label = ESTIMATE_LABEL
                    cells.append(
                        BenchmarkCell(
                            input_path=source,
                            variant_name=variant.name,
                            renderer=renderer,
                            performance_name=profile_name,
                            formats=formats,
                            preset=preset,
                            action=action,
                            mov_path=mov,
                            png_path=png,
                            duration_seconds=duration,
                            estimated_output_mb=estimate,
                            estimate_label=label,
                            notes=notes,
                            output_dir=cell_root / "output",
                        )
                    )
    return cells


def load_and_expand(
    manifest_path: Path, *, output_dir: Path, force: bool = False
) -> tuple[BenchmarkManifest, list[BenchmarkCell]]:
    manifest = load_benchmark_manifest(manifest_path)
    cells = expand_benchmark(
        manifest,
        manifest_dir=manifest_path.parent,
        output_dir=output_dir,
        force=force,
    )
    return manifest, cells


def run_benchmark(
    manifest_path: Path,
    *,
    output_dir: Path,
    force: bool = False,
    grouping_separator: str = "-",
) -> dict[str, Any]:
    benchmark_wall0 = time.perf_counter()
    started = utc_now()
    run_dir = output_dir / f"benchmark-{uuid.uuid4().hex}"
    manifest, cells = load_and_expand(manifest_path, output_dir=run_dir, force=force)
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for cell in cells:
        record: dict[str, Any] = {
            "input": str(cell.input_path),
            "variant": cell.variant_name,
            "renderer": cell.renderer,
            "performance": cell.performance_name,
            "formats": cell.formats,
            "preset": cell.preset.name,
            "action": cell.action,  # compatibility alias for planned_action
            "planned_action": cell.action,
            "actual_action": "NOT_RUN",
            "actual_status": "NOT_RUN",
            "jobs_requested": None,
            "ffmpeg_threads_requested": None,
            "encode_workers_resolved": None,
            "jobs_observed": None,
            "ffmpeg_threads_observed": None,
            "wall_seconds": None,
            "wall_seconds_scope": (
                "render_job call only, including hash/reuse/validation/publication/cleanup; "
                "excludes benchmark expansion, input probing and performance-profile loading"
            ),
            "source_duration_seconds": cell.duration_seconds,
            "output_dir": str(cell.output_dir),
            "analysis_cache_selection": os.environ.get("EWP_ANALYSIS_CACHE") or "default",
            "analysis_cache_policy": "externally selected; not cleared or warmed by runner",
        }
        record.update(
            render_measurements(
                {}, planned_action=cell.action, wall_seconds=0, fps=cell.preset.canvas.fps
            )
        )
        if cell.action != "PROCESS":
            record["status"] = cell.action  # legacy planning status, not a terminal observation
            record["notes"] = cell.notes
            record["resources"] = None
            record["ru_maxrss_kb"] = None
            record["output_bytes"] = None
            records.append(record)
            continue
        performance = load_performance(cell.performance_name).model_copy(deep=True)
        assert cell.output_dir is not None
        work_root = cell.output_dir.parent / "work"
        performance.workdirs["root"] = str(work_root)
        record["work_root"] = str(work_root)
        record["jobs_requested"] = performance.processing.get("jobs")
        record["ffmpeg_threads_requested"] = performance.processing.get("ffmpeg_threads")
        job = _planned_job(cell.input_path, cell.preset, grouping_separator)
        media = probe_media(cell.input_path)
        wall0 = time.perf_counter()
        payload = render_job(
            job,
            media,
            cell.preset,
            performance,
            output_dir=cell.output_dir,
            formats=cell.formats,
            force=force,
        )
        wall = time.perf_counter() - wall0
        resources = parent_resource_observation()
        job_meta = payload.get("job")
        status = "UNKNOWN"
        if isinstance(job_meta, dict):
            status = str(job_meta.get("status") or "UNKNOWN")
        output_bytes: int | None = None
        outputs = payload.get("outputs")
        if isinstance(outputs, list) and outputs:
            output_bytes = 0
            for item in outputs:
                if not isinstance(item, dict) or not item.get("path"):
                    output_bytes = None
                    break
                path = Path(str(item["path"]))
                if path.is_file():
                    output_bytes += path.stat().st_size
                elif path.is_dir():
                    output_bytes += sum(
                        child.stat().st_size for child in path.rglob("*") if child.is_file()
                    )
                else:
                    output_bytes = None
                    break
        analysis = payload.get("analysis", {})
        record.update(
            render_measurements(payload, planned_action=cell.action, wall_seconds=wall, fps=job.fps)
        )
        record.update(
            {
                "status": status,
                "actual_status": status,
                "actual_action": "REUSE"
                if status == "SKIPPED"
                else ("PROCESS" if status in {"SUCCEEDED", "FAILED"} else "UNKNOWN"),
                "wall_seconds": wall,
                "resources": resources,
                "ru_maxrss_kb": resources["parent_lifetime_ru_maxrss"]
                if sys.platform.startswith("linux")
                else None,
                "ru_maxrss_kb_scope": (
                    "deprecated alias: lifetime parent high-water in KiB on Linux only"
                ),
                "output_bytes": output_bytes,
                "outputs": outputs,
                "output_bytes_scope": (
                    "post-call bytes at returned paths, including any reused outputs"
                ),
                "job_id": job_meta.get("job_id") if isinstance(job_meta, dict) else None,
                "encode_workers_resolved": analysis.get("encode_workers")
                if isinstance(analysis, dict)
                else None,
                "jobs_observed": None,
                "ffmpeg_threads_observed": None,
                "worker_measurement_scope": (
                    "resolved task partition is not observed process/thread utilization"
                ),
            }
        )
        records.append(record)
    tools: dict[str, Any] = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            executable = require_tool(name)
            result = run_argv([str(executable), "-version"])
            tools[name] = {
                "path": str(executable),
                "version": result.stdout.splitlines()[0]
                if result.returncode == 0 and result.stdout
                else None,
            }
        except (ToolNotFoundError, OSError):
            tools[name] = None
    environment = {"platform": platform.platform(), "python": sys.version, "tools": tools}
    summary = {
        "schema_version": 1,
        "manifest": manifest.name,
        "manifest_path": str(manifest_path),
        "run_dir": str(run_dir),
        "cells": records,
        "counts": {
            "cells": len(records),
            "succeeded": sum(item.get("actual_status") == "SUCCEEDED" for item in records),
            "skipped": sum(item.get("status") in {"SKIP", "SKIPPED"} for item in records),
            "failed": sum(item.get("actual_status") == "FAILED" for item in records),
            "blocked": sum(item.get("status") in {"BLOCKED", "UNSUPPORTED"} for item in records),
            "unknown": sum(item.get("actual_status") == "UNKNOWN" for item in records),
            "throughput_samples": sum(item["throughput_available"] for item in records),
        },
        "timestamps": {"started_at": started, "completed_at": utc_now()},
        "benchmark_wall_seconds": time.perf_counter() - benchmark_wall0,
        "benchmark_wall_seconds_scope": (
            "invocation setup, expansion/probes/profile loads, cells, output-size accounting "
            "and tool/platform fingerprint collection; excludes summary serialization/write"
        ),
        "environment": environment,
    }
    write_run_summary(summary, run_dir / "benchmark.json")
    write_run_summary(summary, output_dir / f"{manifest.name}_benchmark.json")
    summary["result_json"] = str(output_dir / f"{manifest.name}_benchmark.json")
    return summary
