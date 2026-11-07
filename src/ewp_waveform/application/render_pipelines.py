"""Static internal adapters for the existing FFmpeg paths; no public plugin API.

Only path selection and argument forwarding live here. The implementations own
analysis/frames/encoding; lifecycle owns validation/publication and terminal state.
Hooks remain live views of render, never callback snapshots or worker payloads.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from ewp_waveform.application import render_fixed, render_scroll
from ewp_waveform.application.appearance import FixedAxisAppearance
from ewp_waveform.application.render_lifecycle import RenderLifecycle
from ewp_waveform.application.render_types import RenderContext, RenderOptions
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.domain.diagnostics import Diagnostic


class PipelineHooks(Protocol):
    """Obtain the existing typed views at each original invocation boundary."""

    def _fixed_hooks(self) -> render_fixed.FixedHooks: ...

    def _scroll_hooks(self) -> render_scroll.ScrollHooks: ...


@dataclass(frozen=True)
class PipelineRun:
    """Already-selected per-call state, not defaults, validation or a spawn task.

    Raw contour/failure values are the legacy entry-time aliases. Reports, clock,
    lifecycle and effective context members retain their original references.
    """

    context: RenderContext
    appearance: FixedAxisAppearance | None
    spectrum_contour: bool
    ribbon_ss: int
    source_sha: str
    sig: str
    clip_start: float
    clip_duration: float
    expected_frames: int
    work: Path
    producing_mov: bool
    producing_png: bool
    glow: float
    threads: int
    fail_after_chunk: int | None
    note: Callable[[str], None]
    lifecycle: RenderLifecycle
    analysis: dict[str, Any]
    normalization: dict[str, Any]
    warnings: list[Diagnostic]
    resume_history: list[dict[str, Any]]
    clock: PhaseTimes


class RenderPipeline(Protocol):
    """Two existing phases: pre-identity preparation and in-try execution."""

    def prepare(
        self, hooks: PipelineHooks, preset: VisualPreset, options: RenderOptions
    ) -> FixedAxisAppearance | None: ...

    def run(self, hooks: PipelineHooks, state: PipelineRun) -> None: ...


@dataclass(frozen=True, slots=True)
class _FixedPipeline:
    def prepare(
        self, hooks: PipelineHooks, preset: VisualPreset, options: RenderOptions
    ) -> FixedAxisAppearance | None:
        return render_fixed.resolve_fixed_options(hooks._fixed_hooks(), preset, options)

    def run(self, hooks: PipelineHooks, state: PipelineRun) -> None:
        assert state.appearance is not None
        render_fixed.run_fixed_pipeline(
            hooks._fixed_hooks(),
            job=state.context.job,
            media=state.context.media,
            preset=state.context.preset,
            performance=state.context.performance,
            appearance=state.appearance,
            spectrum_contour=state.spectrum_contour,
            ribbon_ss=state.ribbon_ss,
            source_sha=state.source_sha,
            clip_start=state.clip_start,
            clip_duration=state.clip_duration,
            expected_frames=state.expected_frames,
            work=state.work,
            producing_mov=state.producing_mov,
            producing_png=state.producing_png,
            glow=state.glow,
            threads=state.threads,
            note=state.note,
            lifecycle=state.lifecycle,
            analysis=state.analysis,
            normalization=state.normalization,
            clock=state.clock,
        )


@dataclass(frozen=True, slots=True)
class _ScrollPipeline:
    def prepare(
        self, hooks: PipelineHooks, preset: VisualPreset, options: RenderOptions
    ) -> FixedAxisAppearance | None:
        return None

    def run(self, hooks: PipelineHooks, state: PipelineRun) -> None:
        mov_work, png_work = render_scroll.run_scroll_pipeline(
            hooks._scroll_hooks(),
            job=state.context.job,
            preset=state.context.preset,
            performance=state.context.performance,
            source_sha=state.source_sha,
            sig=state.sig,
            clip_start=state.clip_start,
            clip_duration=state.clip_duration,
            expected_frames=state.expected_frames,
            work=state.work,
            producing_mov=state.producing_mov,
            producing_png=state.producing_png,
            glow=state.glow,
            threads=state.threads,
            fail_after_chunk=state.fail_after_chunk,
            note=state.note,
            analysis=state.analysis,
            normalization=state.normalization,
            warnings=state.warnings,
            resume_history=state.resume_history,
            clock=state.clock,
        )
        if mov_work is not None:
            state.lifecycle.publish_mov(mov_work, failure_message="scroll output failed validation")
        if png_work is not None:
            state.lifecycle.publish_png(png_work)


BUILTIN_PIPELINES: Mapping[str, RenderPipeline] = MappingProxyType(
    {"frequency": _FixedPipeline(), "time": _ScrollPipeline()}
)


def select_pipeline(domain: str) -> RenderPipeline:
    """Keep the legacy frequency/else rule, not a new capability-validation gate.

    Service capability checks still reject particles and playhead before dispatch.
    Direct internal calls retain their prior non-frequency scroll fallback.
    """
    return BUILTIN_PIPELINES["frequency" if domain == "frequency" else "time"]
