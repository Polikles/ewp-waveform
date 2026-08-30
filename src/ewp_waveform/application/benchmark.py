"""Benchmark matrix expansion and execution (docs/13, FR-BENCH-*)."""

from __future__ import annotations

import resource
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ewp_waveform.application.capability import capability_for_preset
from ewp_waveform.application.plan import plan_destinations_for_job
from ewp_waveform.application.render import output_root, render_job
from ewp_waveform.application.results import utc_now, write_run_summary
from ewp_waveform.config.load import load_benchmark_manifest, load_performance, load_preset
from ewp_waveform.config.models import BenchmarkManifest, BenchmarkVariant, VisualPreset
from ewp_waveform.domain.diagnostics import CapabilityLevel
from ewp_waveform.domain.grouping import ids_for_path
from ewp_waveform.domain.models import PlannedJob, TimeMode, VisualizationDomain
from ewp_waveform.ffmpeg.probe import ProbeError, probe_media
from ewp_waveform.ffmpeg.process import ToolNotFoundError
from ewp_waveform.identity import sha256_file

# Spike note (docs/notes/ffmpeg-spike/findings.md): filled+medium glow, 1400x280, 30 fps.
_SPIKE_PRORES_MB_PER_S = 12.5
_SPIKE_PNG_MB_PER_S = 3.6
_SPIKE_PIXEL_FPS = 1400 * 280 * 30
_ESTIMATE_LABEL = (
    "labelled spike extrapolation (filled+glow 1400x280 @ 30 fps); not a profile default"
)

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
    clone.waveform = waveform
    clone.canvas = canvas
    clone.effects = effects
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


def _disk_estimate_mb(duration: float, preset: VisualPreset, formats: list[str]) -> float:
    scale = (preset.canvas.width * preset.canvas.height * preset.canvas.fps) / _SPIKE_PIXEL_FPS
    total = 0.0
    if "prores4444" in formats or not formats:
        total += duration * _SPIKE_PRORES_MB_PER_S * scale
    if "png" in formats:
        total += duration * _SPIKE_PNG_MB_PER_S * scale
    return total


def expand_benchmark(
    manifest: BenchmarkManifest,
    *,
    manifest_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> list[BenchmarkCell]:
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
                                output_dir=output_dir,
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
                        estimate = _disk_estimate_mb(duration, preset, formats)
                        label = _ESTIMATE_LABEL
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
    manifest, cells = load_and_expand(manifest_path, output_dir=output_dir, force=force)
    started = utc_now()
    records: list[dict[str, Any]] = []
    for cell in cells:
        record: dict[str, Any] = {
            "input": str(cell.input_path),
            "variant": cell.variant_name,
            "renderer": cell.renderer,
            "performance": cell.performance_name,
            "formats": cell.formats,
            "preset": cell.preset.name,
            "action": cell.action,
        }
        if cell.action != "PROCESS":
            record["status"] = cell.action
            record["notes"] = cell.notes
            records.append(record)
            continue
        performance = load_performance(cell.performance_name)
        job = _planned_job(cell.input_path, cell.preset, grouping_separator)
        media = probe_media(cell.input_path)
        wall0 = time.perf_counter()
        rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        payload = render_job(
            job,
            media,
            cell.preset,
            performance,
            output_dir=output_root(cell.input_path, output_dir, "benchmark-output"),
            formats=cell.formats,
            force=force,
        )
        wall = time.perf_counter() - wall0
        rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        job_meta = payload.get("job")
        status = "UNKNOWN"
        if isinstance(job_meta, dict):
            status = str(job_meta.get("status") or "UNKNOWN")
        output_bytes = 0
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, dict) and item.get("path"):
                    path = Path(str(item["path"]))
                    if path.is_file():
                        output_bytes += path.stat().st_size
                    elif path.is_dir():
                        output_bytes += sum(
                            child.stat().st_size for child in path.rglob("*") if child.is_file()
                        )
        record.update(
            {
                "status": status,
                "wall_seconds": round(wall, 4),
                "ru_maxrss_kb": max(rss0, rss1),
                "output_bytes": output_bytes,
                "job_id": job_meta.get("job_id") if isinstance(job_meta, dict) else None,
            }
        )
        records.append(record)
    completed = utc_now()
    succeeded = sum(1 for item in records if item.get("status") == "SUCCEEDED")
    skipped = sum(1 for item in records if item.get("status") == "SKIPPED")
    failed = sum(1 for item in records if item.get("status") == "FAILED")
    blocked = sum(1 for item in records if item.get("status") in {"BLOCKED", "UNSUPPORTED"})
    summary = {
        "schema_version": 1,
        "manifest": manifest.name,
        "manifest_path": str(manifest_path),
        "cells": records,
        "counts": {
            "cells": len(records),
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
            "blocked": blocked,
        },
        "timestamps": {"started_at": started, "completed_at": completed},
    }
    write_run_summary(summary, output_dir / f"{manifest.name}_benchmark.json")
    summary["result_json"] = str(output_dir / f"{manifest.name}_benchmark.json")
    return summary
