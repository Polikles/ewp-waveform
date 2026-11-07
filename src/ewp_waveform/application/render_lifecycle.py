"""Existing render lifecycle, separated from scroll/fixed-axis execution.

This is not a transaction: MOV may already be published when PNG validation or
publication fails. Hooks are the live render-module namespace, not a snapshot,
so compatibility forwards and existing monkeypatch/import seams remain active.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

from ewp_waveform.application.appearance import FixedAxisAppearance
from ewp_waveform.application.render_types import RenderContext, RendererOutcome
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import PerformanceProfile, VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import PlannedJob, SourceMedia
from ewp_waveform.ffmpeg.encode import EncodeError
from ewp_waveform.ffmpeg.probe import ProbeError, VideoStreamInfo


class LifecycleHooks(Protocol):
    """Structural view of live compatibility helpers in application.render.

    No import of the dispatcher or eager callback binding is needed. The concrete
    module is supplied by render; checkpoint/results functions remain the existing
    implementations re-exported there.
    """

    __version__: str
    VISUAL_CONTRACT_VERSION: int
    CLASSIC_SCROLL_ALTERNATE_OPACITY: float

    def output_is_complete(self, path: Path) -> bool: ...

    def next_version_path(self, path: Path) -> Path: ...

    def planned_destinations(
        self,
        job: PlannedJob,
        preset: VisualPreset,
        *,
        source_sha256: str,
        output_dir: Path,
        formats: Sequence[str],
        clip_start: float = 0.0,
        clip_duration: float | None = None,
        fixed_axis_recipe: dict[str, Any] | None = None,
    ) -> tuple[str, Path | None, Path | None]: ...

    def publish_path(self, dest: Path, *, force: bool) -> tuple[Path, bool]: ...

    def _validate_mov(
        self, path: Path, *, width: int, height: int, expected_frames: int, fps: float
    ) -> dict[str, Any]: ...

    def _validate_png(
        self, directory: Path, *, expected_frames: int, width: int, height: int
    ) -> dict[str, Any]: ...

    def _result_payload(
        self,
        job: PlannedJob,
        media: SourceMedia,
        preset: VisualPreset,
        performance: PerformanceProfile,
        source_sha: str,
        sig: str,
        started: str,
        *,
        status: str,
        outputs: list[dict[str, Any]],
        warnings: list[Diagnostic],
        workdir: str | None = None,
        validation: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
        normalization: dict[str, Any] | None = None,
        resume_history: list[dict[str, Any]] | None = None,
        phase_report: dict[str, Any] | None = None,
        fixed_axis_recipe: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def _utcnow(self) -> str: ...

    def probe_video(self, path: Path, *, first_frame: bool = False) -> VideoStreamInfo: ...

    def probe_png_sequence(self, directory: Path) -> list[dict[str, Any]]: ...

    def sha256_file(self, path: Path) -> str: ...

    def render_signature(
        self,
        *,
        source_sha256: str,
        preset: VisualPreset,
        fps: float,
        renderer: str = "ffmpeg",
        clip_start: float = 0.0,
        clip_duration: float | None = None,
        fixed_axis_recipe: dict[str, Any] | None = None,
    ) -> str: ...

    def short_signature(self, full: str) -> str: ...

    def envelope_oversample_from_signal(self, signal: dict[str, object]) -> int: ...

    def envelope_aa_from_signal(self, signal: dict[str, object]) -> tuple[str, float]: ...

    def motion_lpf_from_signal(self, signal: dict[str, object]) -> tuple[str, float, float]: ...

    def motion_cutoff_cyc_px(
        self,
        *,
        width: int,
        window_seconds: float,
        fps: float,
        margin: float = 0.85,
        explicit: float = 0.0,
    ) -> float: ...

    def workdir_key(
        self,
        *,
        render_signature: str,
        clip_start: float,
        clip_duration: float,
        want_mov: bool,
        want_png: bool,
    ) -> str: ...

    def resolve_workdir(self, performance: PerformanceProfile, key: str) -> Path: ...

    def elapsed_seconds(self, started_at: str, completed_at: str) -> float: ...

    def validate_output_formats(self, formats: Sequence[str]) -> None: ...

    def resolve_fixed_axis_appearance(
        self,
        preset: VisualPreset,
        *,
        spectrum_contour: bool = False,
        spectrum_spatial_scale: float = 1.0,
        spectrum_spatial_filter: str = "box",
        spectrum_n_bands: int | None = None,
        spectrum_tilt_db_per_octave: float = 0.0,
        spectrum_compress: float = 1.0,
        spectrum_recenter: bool = False,
        spectrum_edge_taper: float = 0.0,
        visual_geometry: str = "spectrum",
        spectrum_layout: str = "linear",
        spectrum_slot_sigma: float = 0.0,
        ribbon_supersample: int | None = None,
        render_path: str | None = None,
        render_aa: str | None = None,
        field_geometry: str = "ribbon",
        bar_width: float | None = None,
        bar_gap: float | None = None,
        bar_count: int | None = None,
        bar_fill: float | None = None,
        bar_align: str | None = None,
        bar_alternate: bool | None = None,
        bar_color_b: str | None = None,
        bar_center_line_width: float | None = None,
    ) -> FixedAxisAppearance: ...


def output_root(source: Path, configured: Path | None, directory_name: str) -> Path:
    if configured is not None:
        return configured
    parent = source.parent if source.is_file() else source
    return parent / directory_name


def next_version_path(path: Path) -> Path:
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    n = 2
    while True:
        candidate = parent / f"{stem}_v{n:03d}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def output_is_complete(path: Path) -> bool:
    """True when dest looks like a finished publish, not an empty leftover."""
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.glob("frame_*.png"))
    return False


def publish_path(
    hooks: LifecycleHooks,
    dest: Path,
    *,
    force: bool,
) -> tuple[Path, bool]:
    """Return dest, skip. skip True means equivalent output already present."""
    if not hooks.output_is_complete(dest):
        return dest, False
    if force:
        return hooks.next_version_path(dest), False
    return dest, True


def planned_destinations(
    hooks: LifecycleHooks,
    job: PlannedJob,
    preset: VisualPreset,
    *,
    source_sha256: str,
    output_dir: Path,
    formats: Sequence[str],
    clip_start: float = 0.0,
    clip_duration: float | None = None,
    fixed_axis_recipe: dict[str, Any] | None = None,
) -> tuple[str, Path | None, Path | None]:
    """Return render signature and canonical dest paths (mov, png dir)."""
    hooks.validate_output_formats(formats)
    if fixed_axis_recipe is None and preset.waveform.domain == "frequency":
        fixed_axis_recipe = hooks.resolve_fixed_axis_appearance(preset).identity()
    sig = hooks.render_signature(
        source_sha256=source_sha256,
        preset=preset,
        fps=job.fps,
        clip_start=clip_start,
        clip_duration=clip_duration,
        fixed_axis_recipe=fixed_axis_recipe,
    )
    short = hooks.short_signature(sig)
    project_dir = output_dir / job.project_id
    stem = f"{job.path.stem}_{preset.name}_{short}"
    want_png = "png" in formats
    want_mov = "prores4444" in formats or not formats
    mov = project_dir / f"{stem}.mov" if want_mov else None
    png = project_dir / f"{stem}_png" if want_png else None
    return sig, mov, png


def _validate_mov(
    hooks: LifecycleHooks,
    path: Path,
    *,
    width: int,
    height: int,
    expected_frames: int,
    fps: float,
) -> dict[str, Any]:
    """Check metadata plus one decoded frame, not every ProRes frame."""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return {"passed": False}
        info = hooks.probe_video(path, first_frame=True)
        rate_ok = Fraction(info.avg_frame_rate) == Fraction(str(fps))
        duration_ok = (
            math.isfinite(info.duration_seconds)
            and info.duration_seconds > 0
            # MOV/ffprobe durations are rounded to microseconds.
            and abs(info.duration_seconds - expected_frames / fps) <= 1 / fps + 1e-6
        )
        passed = (
            info.codec_name == "prores"
            and info.profile in {"4444", "XQ"}
            and info.pix_fmt.startswith("yuva444p")
            and info.width == width
            and info.height == height
            and info.nb_frames is not None
            and abs(info.nb_frames - expected_frames) <= 1
            and rate_ok
            and duration_ok
        )
    except (ProbeError, OSError, ValueError, ZeroDivisionError):
        return {"passed": False}
    return {
        "passed": passed,
        "codec": info.codec_name,
        "pix_fmt": info.pix_fmt,
        "width": info.width,
        "height": info.height,
        "frames": info.nb_frames,
        "duration_seconds": info.duration_seconds,
    }


def _validate_png(
    hooks: LifecycleHooks, directory: Path, *, expected_frames: int, width: int, height: int
) -> dict[str, Any]:
    """Require contiguous readable RGBA PNGs, including every frame's geometry."""
    count = 0
    passed = False
    try:
        frames = sorted(directory.glob("frame_*.png"))
        count = len(frames)
        if (
            not directory.is_dir()
            or expected_frames < 1
            or count != expected_frames
            or any(
                frame.name != f"frame_{index:06d}.png"
                or not frame.is_file()
                or frame.stat().st_size <= 0
                for index, frame in enumerate(frames, 1)
            )
        ):
            return {"passed": False, "frames": count, "format": "png"}
        decoded = hooks.probe_png_sequence(directory)
        passed = len(decoded) == expected_frames and all(
            frame.get("width") == width
            and frame.get("height") == height
            and frame.get("pix_fmt") in {"rgba", "rgba64be", "rgba64le"}
            for frame in decoded
        )
    except (ProbeError, OSError, ValueError):
        pass
    return {"passed": passed, "frames": count, "format": "png"}


def _result_payload(
    hooks: LifecycleHooks,
    job: PlannedJob,
    media: SourceMedia,
    preset: VisualPreset,
    performance: PerformanceProfile,
    source_sha: str,
    sig: str,
    started: str,
    *,
    status: str,
    outputs: list[dict[str, Any]],
    warnings: list[Diagnostic],
    workdir: str | None = None,
    validation: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    normalization: dict[str, Any] | None = None,
    resume_history: list[dict[str, Any]] | None = None,
    phase_report: dict[str, Any] | None = None,
    fixed_axis_recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    glow = preset.effects.get("glow") if isinstance(preset.effects.get("glow"), dict) else {}
    report = validation if validation is not None else {"passed": status == "SUCCEEDED"}
    return {
        "schema_version": 1,
        "tool": {"name": "ewp-waveform", "version": hooks.__version__},
        "job": {
            "job_id": f"{job.project_id}-{job.track_id}-{hooks.short_signature(sig)}",
            "status": status,
            "render_signature": sig,
            "seed": 0,
        },
        "renderer": {
            "name": "ffmpeg",
            "version": "system",
            "visual_contract_version": hooks.VISUAL_CONTRACT_VERSION,
        },
        "project": {"project_id": job.project_id, "track_id": job.track_id},
        "inputs": [
            {
                "path": str(media.path),
                "sha256": source_sha,
                "size_bytes": media.size_bytes,
                "duration_seconds": media.duration_seconds,
                "codec": media.codec,
                "sample_rate": media.sample_rate,
                "channels": media.channels,
            }
        ],
        "preset": {"name": preset.name, "source": "builtin"},
        "resolved_visual_config": {
            **({"fixed_axis_recipe": fixed_axis_recipe} if fixed_axis_recipe is not None else {}),
            "fps": job.fps,
            "style": preset.waveform.style,
            "domain": preset.waveform.domain,
            "time_mode": preset.waveform.time_mode,
            "color": preset.waveform.color,
            "window_seconds": preset.waveform.window_seconds,
            "classic_alternate_opacity": preset.signal.get(
                "classic_alternate_opacity", hooks.CLASSIC_SCROLL_ALTERNATE_OPACITY
            ),
            "envelope_oversample": hooks.envelope_oversample_from_signal(preset.signal),
            "envelope_aa": hooks.envelope_aa_from_signal(preset.signal)[0],
            "envelope_aa_support": hooks.envelope_aa_from_signal(preset.signal)[1],
            "shutter_degrees": preset.signal.get("shutter_degrees", 0),
            "shutter_mix": preset.signal.get("shutter_mix", 0.25),
            "envelope_motion_lpf": hooks.motion_lpf_from_signal(preset.signal)[0],
            "envelope_motion_cutoff": hooks.motion_cutoff_cyc_px(
                width=preset.canvas.width,
                window_seconds=preset.waveform.window_seconds,
                fps=job.fps,
                margin=hooks.motion_lpf_from_signal(preset.signal)[2],
                explicit=hooks.motion_lpf_from_signal(preset.signal)[1],
            ),
            "glow": glow,
        },
        "resolved_performance_config": {
            "profile": performance.name,
            **performance.processing,
        },
        "analysis": analysis or {},
        "normalization": normalization or {},
        "warnings": [w.model_dump(mode="json") for w in warnings],
        "outputs": outputs,
        "validation": report,
        "performance": phase_report or {},
        "resume_history": resume_history or [],
        "timestamps": {
            "started_at": started,
            "completed_at": (completed := hooks._utcnow()),
            "duration_seconds": hooks.elapsed_seconds(started, completed),
        },
        "execution": {
            "workdir": workdir,
            "capability": job.capability.value,
            "resumed": bool(resume_history),
        },
    }


@dataclass(frozen=True)
class DestinationSelection:
    signature: str
    mov: Path | None
    png: Path | None
    want_mov: bool
    want_png: bool
    skip_mov: bool
    skip_png: bool
    expected_frames: int
    skip_outputs: list[dict[str, Any]]
    skip_validation: dict[str, Any]

    @property
    def producing_mov(self) -> bool:
        return self.want_mov and not self.skip_mov

    @property
    def producing_png(self) -> bool:
        return self.want_png and not self.skip_png

    def all_reused(self, force: bool) -> bool:
        return (
            (not self.want_mov or self.skip_mov)
            and (not self.want_png or self.skip_png)
            and not force
        )


def prepare_destinations(
    hooks: LifecycleHooks,
    job: PlannedJob,
    preset: VisualPreset,
    *,
    source_sha: str,
    output_dir: Path,
    formats: Sequence[str],
    force: bool,
    clip_start: float,
    clip_duration: float,
    identity_duration: float | None,
    fixed_axis_recipe: dict[str, Any] | None,
) -> DestinationSelection:
    sig, mov_dest, png_dest = hooks.planned_destinations(
        job,
        preset,
        source_sha256=source_sha,
        output_dir=output_dir,
        formats=formats,
        clip_start=clip_start,
        clip_duration=identity_duration,
        fixed_axis_recipe=fixed_axis_recipe,
    )
    project_dir = output_dir / job.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    want_png = png_dest is not None
    want_mov = mov_dest is not None
    skip_mov = False
    skip_png = False
    if mov_dest is not None:
        mov_dest, skip_mov = hooks.publish_path(mov_dest, force=force)
    if png_dest is not None:
        png_dest, skip_png = hooks.publish_path(png_dest, force=force)

    expected_frames = max(1, round(clip_duration * job.fps))
    skip_outputs: list[dict[str, Any]] = []
    skip_validation: dict[str, Any] = {"passed": True}
    if want_mov and skip_mov:
        assert mov_dest is not None
        try:
            skip_validation = hooks._validate_mov(
                mov_dest,
                width=preset.canvas.width,
                height=preset.canvas.height,
                expected_frames=expected_frames,
                fps=job.fps,
            )
        except (ProbeError, OSError):
            skip_validation = {"passed": False}
        if not skip_validation.get("passed"):
            skip_mov = False
        else:
            skip_outputs.append({"path": str(mov_dest), "format": "prores4444"})
    if want_png and skip_png:
        assert png_dest is not None
        png_report = hooks._validate_png(
            png_dest,
            expected_frames=expected_frames,
            width=preset.canvas.width,
            height=preset.canvas.height,
        )
        if not png_report.get("passed"):
            skip_png = False
        else:
            skip_outputs.append({"path": str(png_dest), "format": "png"})
            if not (want_mov and skip_mov):
                skip_validation = png_report

    return DestinationSelection(
        sig,
        mov_dest,
        png_dest,
        want_mov,
        want_png,
        skip_mov,
        skip_png,
        expected_frames,
        skip_outputs,
        skip_validation,
    )


@dataclass(frozen=True)
class WorkdirPolicy:
    path: Path
    keep_on_failure: bool


@dataclass
class RenderLifecycle:
    """Per-invocation destination/result state; no renderer or checkpoint pipeline."""

    context: RenderContext
    hooks: LifecycleHooks
    selection: DestinationSelection
    source_sha: str
    started: str
    fixed_axis_recipe: dict[str, Any] | None
    clip_start: float
    clip_duration: float
    outputs: list[dict[str, Any]] = field(default_factory=list, init=False)
    warnings: list[Diagnostic] = field(default_factory=list, init=False)
    validation: dict[str, Any] = field(default_factory=lambda: {"passed": False}, init=False)

    def skipped(self, note: Callable[[str], None]) -> RendererOutcome:
        note("skip: equivalent output already present")
        return RendererOutcome(
            self.hooks._result_payload(
                self.context.job,
                self.context.media,
                self.context.preset,
                self.context.performance,
                self.source_sha,
                self.selection.signature,
                self.started,
                fixed_axis_recipe=self.fixed_axis_recipe,
                status="SKIPPED",
                outputs=self.selection.skip_outputs,
                warnings=[],
                validation=self.selection.skip_validation,
                phase_report={
                    "extras": {
                        "clip_start_seconds": self.clip_start,
                        "effective_audio_seconds": self.clip_duration,
                        "expected_frames": self.selection.expected_frames,
                        "reused_output_formats": [
                            item["format"] for item in self.selection.skip_outputs
                        ],
                    }
                },
            )
        )

    def prepare_workdir(self, *, keep_temp: bool) -> WorkdirPolicy:
        key = self.hooks.workdir_key(
            render_signature=self.selection.signature,
            clip_start=self.clip_start,
            clip_duration=self.clip_duration,
            want_mov=self.selection.producing_mov,
            want_png=self.selection.producing_png,
        )
        work = self.hooks.resolve_workdir(self.context.performance, key)
        self.outputs = list(self.selection.skip_outputs)
        keep = keep_temp or bool(self.context.performance.workdirs.get("keep_on_failure", True))
        return WorkdirPolicy(work, keep)

    def verify_source(self) -> None:
        after_hash = self.hooks.sha256_file(self.context.job.path)
        if after_hash != self.source_sha:
            self.warnings.append(
                Diagnostic(
                    code=DiagnosticCode.E_OUTPUT_VALIDATION,
                    severity=Severity.ERROR,
                    message="Source hash changed during render; sources must be immutable.",
                    path=str(self.context.job.path),
                )
            )
            raise RuntimeError("source mutated")

    def publish_mov(self, path: Path, *, failure_message: str) -> None:
        self.validation = self.hooks._validate_mov(
            path,
            width=self.context.preset.canvas.width,
            height=self.context.preset.canvas.height,
            expected_frames=self.selection.expected_frames,
            fps=self.context.job.fps,
        )
        if not self.validation.get("passed"):
            raise EncodeError(failure_message)
        if self.selection.mov is not None:
            shutil.move(str(path), str(self.selection.mov))
            self.outputs.append({"path": str(self.selection.mov), "format": "prores4444"})

    def publish_png(self, path: Path) -> None:
        png_report = self.hooks._validate_png(
            path,
            expected_frames=self.selection.expected_frames,
            width=self.context.preset.canvas.width,
            height=self.context.preset.canvas.height,
        )
        if not png_report.get("passed"):
            raise EncodeError("png sequence failed validation")
        if self.selection.png is not None and self.selection.png.exists():
            shutil.rmtree(self.selection.png)
        if self.selection.png is not None:
            shutil.move(str(path), str(self.selection.png))
            self.outputs.append({"path": str(self.selection.png), "format": "png"})
        if not self.selection.producing_mov:
            self.validation = png_report
        else:
            self.validation = {**self.validation, "png_frames": png_report.get("frames")}

    def mark_succeeded(self) -> None:
        self.validation["passed"] = True

    def failed(
        self,
        exc: Exception,
        policy: WorkdirPolicy,
        *,
        analysis: dict[str, Any],
        normalization: dict[str, Any],
        resume_history: list[dict[str, Any]],
        clock: PhaseTimes,
    ) -> RendererOutcome:
        self.warnings.append(
            Diagnostic(
                code=DiagnosticCode.E_OUTPUT_VALIDATION
                if "hash" in str(exc) or "validation" in str(exc)
                else DiagnosticCode.E_RENDERER_CAPABILITY,
                severity=Severity.ERROR,
                message=str(exc),
            )
        )
        self.validation = {**self.validation, "passed": False}
        if not policy.keep_on_failure:
            shutil.rmtree(policy.path, ignore_errors=True)
        return self._result(
            status="FAILED",
            workdir=str(policy.path) if Path(policy.path).exists() else None,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
            phase_report=clock.snapshot(),
        )

    def succeeded(
        self,
        policy: WorkdirPolicy,
        *,
        keep_temp: bool,
        analysis: dict[str, Any],
        normalization: dict[str, Any],
        resume_history: list[dict[str, Any]],
        clock: PhaseTimes,
    ) -> RendererOutcome:
        if not keep_temp and not bool(
            self.context.performance.workdirs.get("keep_on_success", False)
        ):
            shutil.rmtree(policy.path, ignore_errors=True)
            work_out = None
        else:
            work_out = str(policy.path)
        return self._result(
            status="SUCCEEDED",
            workdir=work_out,
            analysis=analysis,
            normalization=normalization,
            resume_history=resume_history,
            phase_report=clock.snapshot(),
        )

    def _result(
        self,
        *,
        status: str,
        workdir: str | None,
        analysis: dict[str, Any],
        normalization: dict[str, Any],
        resume_history: list[dict[str, Any]],
        phase_report: dict[str, Any],
    ) -> RendererOutcome:
        return RendererOutcome(
            self.hooks._result_payload(
                self.context.job,
                self.context.media,
                self.context.preset,
                self.context.performance,
                self.source_sha,
                self.selection.signature,
                self.started,
                fixed_axis_recipe=self.fixed_axis_recipe,
                status=status,
                outputs=self.outputs,
                warnings=self.warnings,
                workdir=workdir,
                validation=self.validation,
                analysis=analysis,
                normalization=normalization,
                resume_history=resume_history,
                phase_report=phase_report,
            )
        )
