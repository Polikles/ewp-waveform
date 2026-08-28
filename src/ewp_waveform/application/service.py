"""Application service. CLI and tests call this; FFmpeg details stay in the adapter."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from ewp_waveform.application.render import output_root, render_job
from ewp_waveform.config.load import load_application_config, load_performance, load_preset
from ewp_waveform.config.models import ApplicationConfig, VisualPreset
from ewp_waveform.discovery.scan import DiscoveryError, discover_paths
from ewp_waveform.domain.diagnostics import (
    EXIT_CODE_VALUES,
    CapabilityItem,
    CapabilityLevel,
    Diagnostic,
    DiagnosticCode,
    ExitCode,
    Severity,
)
from ewp_waveform.domain.grouping import ids_for_path
from ewp_waveform.domain.models import (
    PlannedJob,
    SourceMedia,
    TimeMode,
    VisualizationDomain,
)
from ewp_waveform.ffmpeg.capabilities import ffmpeg_capabilities
from ewp_waveform.ffmpeg.doctor import check_environment
from ewp_waveform.ffmpeg.probe import ProbeError, probe_media
from ewp_waveform.ffmpeg.process import ToolNotFoundError


class AppError(Exception):
    def __init__(
        self, exit_code: ExitCode, message: str, diagnostic: Diagnostic | None = None
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.diagnostic = diagnostic

    @property
    def numeric_exit(self) -> int:
        return EXIT_CODE_VALUES[self.exit_code]


def _capability_for_preset(preset: VisualPreset) -> tuple[CapabilityLevel, str]:
    domain = preset.waveform.domain
    if domain == "frequency":
        return (
            CapabilityLevel.EXPERIMENTAL,
            "Fixed-axis spectrum: showfreqs is the right idea, not the product look.",
        )
    if preset.waveform.time_mode == "playhead":
        return CapabilityLevel.UNSUPPORTED, "Playhead envelope is deferred."
    style = preset.waveform.style
    if style == "segmented":
        return CapabilityLevel.EXPERIMENTAL, "Impuls segmentowy is not implemented faithfully."
    if style in {"classic", "mirrored", "filled"}:
        return (
            CapabilityLevel.LIMITED,
            "Scrolling RMS envelope bars (5 s window). Limited vs brand linia lustrzana.",
        )
    return CapabilityLevel.UNSUPPORTED, f"Unknown style '{style}'."


def doctor() -> list[str]:
    return check_environment()


def capabilities() -> list[CapabilityItem]:
    return ffmpeg_capabilities()


def inspect_input(
    input_path: Path,
    *,
    recursive: bool = False,
    config_path: Path | None = None,
    grouping_separator: str | None = None,
) -> list[tuple[SourceMedia, str, str]]:
    app_cfg = load_application_config(config_path)
    separator = grouping_separator or app_cfg.input.grouping.separator
    try:
        paths = discover_paths(
            input_path,
            recursive=recursive or app_cfg.input.recursive,
            follow_symlinks=app_cfg.input.follow_symlinks,
        )
    except DiscoveryError as exc:
        raise AppError(ExitCode.INPUT, exc.diagnostic.message, exc.diagnostic) from exc
    if not paths:
        raise AppError(ExitCode.INPUT, f"No WAV/MP3 inputs under {input_path}")
    rows: list[tuple[SourceMedia, str, str]] = []
    try:
        for path in paths:
            media = probe_media(path)
            project_id, track_id = ids_for_path(path, separator)
            rows.append((media, project_id, track_id))
    except (ToolNotFoundError, ProbeError) as exc:
        raise AppError(ExitCode.CAPABILITY, str(exc)) from exc
    return rows


def dry_run(
    input_path: Path,
    *,
    recursive: bool = False,
    config_path: Path | None = None,
    preset_name: str | None = None,
    performance_name: str | None = None,
    fps_override: float | None = None,
) -> tuple[ApplicationConfig, VisualPreset, list[PlannedJob], list[Diagnostic]]:
    app_cfg = load_application_config(config_path)
    try:
        preset = load_preset(preset_name or app_cfg.defaults.preset)
        load_performance(performance_name or app_cfg.defaults.performance)
    except FileNotFoundError as exc:
        raise AppError(ExitCode.CONFIG, str(exc)) from exc
    except ValueError as exc:
        raise AppError(ExitCode.CONFIG, str(exc)) from exc

    try:
        paths = discover_paths(
            input_path,
            recursive=recursive or app_cfg.input.recursive,
            follow_symlinks=app_cfg.input.follow_symlinks,
        )
    except DiscoveryError as exc:
        raise AppError(ExitCode.INPUT, exc.diagnostic.message, exc.diagnostic) from exc
    if not paths:
        raise AppError(ExitCode.INPUT, f"No WAV/MP3 inputs under {input_path}")

    cap_level, cap_notes = _capability_for_preset(preset)
    fps = fps_override if fps_override is not None else preset.canvas.fps
    domain = VisualizationDomain(preset.waveform.domain)
    time_mode = TimeMode(preset.waveform.time_mode) if preset.waveform.time_mode else None
    separator = app_cfg.input.grouping.separator

    durations: dict[str, list[float]] = defaultdict(list)
    jobs: list[PlannedJob] = []
    extra: list[Diagnostic] = []
    for path in paths:
        project_id, track_id = ids_for_path(path, separator)
        duration = 0.0
        try:
            media = probe_media(path)
            duration = media.duration_seconds
            if media.channels > 1:
                extra.append(
                    Diagnostic(
                        code=DiagnosticCode.W_AUDIO_STEREO_DOWNMIX,
                        severity=Severity.WARNING,
                        message="Multichannel source will be downmixed for visualization.",
                        path=str(path),
                    )
                )
        except (ToolNotFoundError, ProbeError):
            pass
        if duration:
            durations[project_id].append(duration)
        jobs.append(
            PlannedJob(
                path=path,
                project_id=project_id,
                track_id=track_id,
                preset=preset.name,
                domain=domain,
                time_mode=time_mode,
                style=preset.waveform.style,
                fps=fps,
                capability=cap_level,
                capability_notes=cap_notes,
            )
        )
    extra.extend(_timeline_diagnostics(durations, fps))
    return app_cfg, preset, jobs, extra


def render(
    input_path: Path,
    *,
    recursive: bool = False,
    config_path: Path | None = None,
    preset_name: str | None = None,
    performance_name: str | None = None,
    fps_override: float | None = None,
    output_dir: Path | None = None,
    formats: list[str] | None = None,
    force: bool = False,
    start: float | None = None,
    duration: float | None = None,
    keep_temp: bool = False,
) -> list[dict[str, object]]:
    app_cfg, preset, jobs, diagnostics = dry_run(
        input_path,
        recursive=recursive,
        config_path=config_path,
        preset_name=preset_name,
        performance_name=performance_name,
        fps_override=fps_override,
    )
    if any(d.severity == Severity.ERROR for d in diagnostics):
        raise AppError(ExitCode.INPUT, diagnostics[-1].message, diagnostics[-1])
    particles = preset.effects.get("particles")
    if isinstance(particles, dict) and particles.get("enabled"):
        raise AppError(
            ExitCode.CAPABILITY,
            "Particles are unsupported in the FFmpeg MVP.",
            Diagnostic(
                code=DiagnosticCode.E_RENDERER_CAPABILITY,
                severity=Severity.ERROR,
                message="Particles are unsupported in the FFmpeg MVP.",
            ),
        )
    if preset.waveform.time_mode == "playhead":
        raise AppError(
            ExitCode.CAPABILITY,
            "Playhead envelope is deferred.",
            Diagnostic(
                code=DiagnosticCode.E_RENDERER_CAPABILITY,
                severity=Severity.ERROR,
                message="Playhead envelope is deferred.",
            ),
        )
    performance = load_performance(performance_name or app_cfg.defaults.performance)
    fmts = formats or app_cfg.output.formats
    results: list[dict[str, object]] = []
    failed = 0
    for job in jobs:
        media = probe_media(job.path)
        root = output_root(job.path, output_dir, app_cfg.output.directory_name)
        payload = render_job(
            job,
            media,
            preset,
            performance,
            output_dir=root,
            formats=fmts,
            force=force,
            start=start,
            duration=duration,
            keep_temp=keep_temp,
        )
        out_dir = root / job.project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        result_file = out_dir / f"{job.path.stem}_{preset.name}_results.json"
        result_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["result_json"] = str(result_file)
        results.append(payload)
        job_meta = cast(dict[str, Any], payload.get("job") or {})
        if job_meta.get("status") == "FAILED":
            failed += 1
    _ = failed
    return results


def _timeline_diagnostics(durations: dict[str, list[float]], fps: float) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    if fps <= 0:
        return out
    for project_id, values in durations.items():
        if len(values) < 2:
            continue
        span = max(values) - min(values)
        frames = span * fps
        if frames <= 1:
            continue
        if frames <= 3:
            out.append(
                Diagnostic(
                    code=DiagnosticCode.W_PROJECT_DURATION_MISMATCH,
                    severity=Severity.WARNING,
                    message=(
                        f"Project {project_id}: duration span {span:.4f}s "
                        f"({frames:.2f} frames at {fps} fps)"
                    ),
                )
            )
        else:
            out.append(
                Diagnostic(
                    code=DiagnosticCode.E_PROJECT_TIMELINE_MISMATCH,
                    severity=Severity.ERROR,
                    message=(
                        f"Project {project_id}: duration span {span:.4f}s "
                        f"({frames:.2f} frames at {fps} fps) exceeds 3 frames"
                    ),
                )
            )
    return out
