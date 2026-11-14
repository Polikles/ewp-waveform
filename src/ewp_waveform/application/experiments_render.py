"""Narrow explicit production-service bridge for short CPU experiments.

No global monkeypatches, environment-selected adapters or default changes. Pool
work, FFV1 service publication and full-source experiments are deliberately refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ewp_waveform.application import render_fixed, render_lifecycle
from ewp_waveform.application.render_pipelines import PipelineHooks
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.domain.models import PlannedJob
from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding
from ewp_waveform.ffmpeg.experiments import EncodeExperiment


class _View:
    def __init__(self, base: Any) -> None:
        self.base = base

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


@dataclass(frozen=True)
class ServiceExperiment:
    """Opt-in internal API, not a production performance/profile option."""

    encoding: EncodeExperiment | SuiteEncoding
    expected_preset: dict[str, Any] | None = None

    def validate(
        self, job: PlannedJob, preset: VisualPreset, formats: list[str], duration: float | None
    ) -> None:
        if (
            self.expected_preset is not None
            and preset.model_dump(mode="json") != self.expected_preset
        ):
            raise ValueError("frozen effective preset drift; replan required")
        if (
            preset.name != "iuris-ribbon-refined"
            or job.domain.value != "frequency"
            or formats != ["prores4444"]
            or duration is None
            or not 0 < duration <= 4
        ):
            raise ValueError(
                "experiments require refined ribbon, MOV only and explicit duration <=4s"
            )
        if self.encoding.candidate in ("ENC-FFV1", "FFV1-DIRECT"):
            raise ValueError("FFV1 service publication unavailable; use explicit native pipeline")
        c = self.encoding.crop
        if c and (c.canvas_width, c.canvas_height) != (preset.canvas.width, preset.canvas.height):
            raise ValueError("frozen crop canvas does not match production geometry")
        if self.encoding.command_log is None:
            raise ValueError("experiment requires command evidence")

    def identity(self) -> dict[str, Any]:
        if isinstance(self.encoding, SuiteEncoding):
            return self.encoding.identity()
        return {
            "adapter_revision": 1,
            "candidate": self.encoding.candidate,
            "crop": self.encoding.crop.record() if self.encoding.crop else None,
        }

    def lifecycle_hooks(
        self, base: render_lifecycle.LifecycleHooks
    ) -> render_lifecycle.LifecycleHooks:
        encoding = self.encoding

        class View(_View):
            def _validate_mov(self, path: Path, **kwargs: Any) -> dict[str, Any]:
                if encoding.crop:
                    kwargs.update(width=encoding.crop.width, height=encoding.crop.height)
                result: dict[str, Any] = self.base._validate_mov(path, **kwargs)
                return result

        return cast(render_lifecycle.LifecycleHooks, View(base))

    def pipeline_hooks(self, base: PipelineHooks) -> PipelineHooks:
        encoding = self.encoding

        class Fixed(_View):
            def encode_rgba_stream(self, frames: Any, **kwargs: Any) -> None:
                if kwargs.get("png_dir") is not None:
                    raise ValueError("no simultaneous PNG in timed MOV")
                self.base.encode_rgba_stream(frames, **kwargs, experiment=encoding)

        class Pipeline(_View):
            def _fixed_hooks(self) -> render_fixed.FixedHooks:
                return cast(render_fixed.FixedHooks, Fixed(self.base._fixed_hooks()))

        return cast(PipelineHooks, Pipeline(base))
