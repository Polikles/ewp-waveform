"""Narrow combined FIR candidate on the actual serial application service.

Not a production profile, multi-file scheduler or Vulkan/FFV1 workaround. Torch
stays lazy. Each encode qualifies independently inside the service timer.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, cast

# campaign() runs in the stdlib-only invoking interpreter. Rendering imports
# belong to the selected worker, not this module's scheduling surface.
if TYPE_CHECKING:
    from ewp_waveform.application import render_fixed, render_lifecycle
    from ewp_waveform.application.render_pipelines import PipelineHooks
    from ewp_waveform.config.models import VisualPreset
    from ewp_waveform.domain.models import PlannedJob

CONTROL: dict[str, Any] = {
    "output_mode": "host-reuse",
    "batch_size": 1,
    "timing_mode": "diagnostic",
}
COMBINED: dict[str, Any] = {
    "output_mode": "device-rgba",
    "batch_size": 2,
    "timing_mode": "ordinary",
}


@dataclass
class TorchServiceExperiment:
    """Explicit single-file FIR service seam; defaults elsewhere are untouched."""

    backend: str = "cuda"
    device: str = "cuda:0"
    output_mode: str = "device-rgba"
    batch_size: int = 2
    timing_mode: str = "ordinary"
    expected_preset: dict[str, Any] | None = None
    expected_device: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        from ewp_waveform.ffmpeg.torch_finish import (
            validate_backend_device,
            validate_execution_options,
        )

        if self.backend not in ("cuda", "torch-cpu"):
            raise ValueError("FIR service requires cuda or explicit torch-cpu test backend")
        validate_backend_device(self.backend, self.device)
        if self.backend == "torch-cpu" and self.device != "cpu":
            raise ValueError("torch-cpu service requires cpu device")
        validate_execution_options(self.output_mode, self.batch_size, self.timing_mode)

    def validate(
        self, job: PlannedJob, preset: VisualPreset, formats: list[str], duration: float | None
    ) -> None:
        if (
            self.expected_preset is not None
            and preset.model_dump(mode="json") != self.expected_preset
        ):
            raise ValueError("frozen effective preset drift; replan required")
        if (
            (
                preset.name != "iuris-ribbon-refined"
                and not (
                    preset.name == "iuris-ribbon-refined-production"
                    and self.expected_preset is not None
                )
            )
            or job.domain.value != "frequency"
            or formats != ["prores4444"]
            or duration is None
            or not math.isfinite(duration)
            or not 0 < duration <= 32
            or job.fps != 60
        ):
            raise ValueError("FIR service requires refined ribbon MOV at 60fps, duration <=32s")

    def identity(self) -> dict[str, Any]:
        from ewp_waveform.ffmpeg.torch_finish import ALGORITHM

        return {
            "adapter_revision": 1,
            "candidate": "FIR-SERIAL-SERVICE",
            "algorithm": ALGORITHM,
            "backend": self.backend,
            "device": self.device,
            "output_mode": self.output_mode,
            "batch_size": self.batch_size,
            "timing_mode": self.timing_mode,
            "analysis_cache": "disabled",
        }

    def lifecycle_hooks(
        self, base: render_lifecycle.LifecycleHooks
    ) -> render_lifecycle.LifecycleHooks:
        # Ordinary validation/publication is deliberately not replaced.
        return base

    def pipeline_hooks(self, base: PipelineHooks) -> PipelineHooks:
        from ewp_waveform.application import render_fixed
        from ewp_waveform.application.experiments_render import _View
        from ewp_waveform.application.render_pipelines import PipelineHooks

        experiment = self

        class Fixed(_View):
            def _job_workers(self, performance: Any) -> int:
                if self.base._job_workers(performance) != 1:
                    raise ValueError("FIR service experiment requires explicit serial jobs1")
                return 1

            def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
                return None

            def encode_rgba_stream(self, frames: Iterable[bytes], **kwargs: Any) -> None:
                experiment.encode(self.base.encode_rgba_stream, frames, kwargs)

        class Pipeline(_View):
            def _fixed_hooks(self) -> render_fixed.FixedHooks:
                return cast(render_fixed.FixedHooks, Fixed(self.base._fixed_hooks()))

        return cast(PipelineHooks, Pipeline(base))

    def encode(
        self, encoder: Callable[..., None], frames: Iterable[bytes], kwargs: dict[str, Any]
    ) -> None:
        """Preserve production raster/state, replacing only the finishing seam."""
        from ewp_waveform.application.torch_experiment import _torch_stream
        from ewp_waveform.ffmpeg.draw import parse_rgb
        from ewp_waveform.ffmpeg.torch_finish import FinishSpec, TorchFinisher, qualify

        if self.metrics:
            raise ValueError("one FIR service adapter may encode only one file")
        finish = kwargs.get("ribbon_finish")
        if (
            kwargs.get("png_dir") is not None
            or kwargs.get("prores_path") is None
            or finish is None
            or kwargs.get("color") is None
            or kwargs.get("ribbon_finish_lut", False)
            or kwargs.get("fps") != 60
            or kwargs.get("pix_fmt") not in ("gray", "rgba")
        ):
            raise ValueError("FIR service requires original ribbon raster, MOV only, no LUT")
        spec = FinishSpec(
            width=kwargs["width"],
            height=kwargs["height"],
            overscan=kwargs["overscan"],
            supersample=kwargs["supersample"],
            sigma=kwargs["glow"],
            reflection=finish[0],
            horizon=finish[1],
            thickness=finish[2],
            extent=finish[3],
            opacity=finish[4],
            color=parse_rgb(kwargs["color"]),
        )
        options: dict[str, Any] = {
            "output_mode": self.output_mode,
            "batch_size": self.batch_size,
            "timing_mode": self.timing_mode,
        }
        self.metrics.update(
            backend=self.backend,
            device=self.device,
            **options,
            spec=asdict(spec),
            effective_preset=self.expected_preset,
        )
        started = time.perf_counter()
        qualification = qualify(self.backend, device=self.device, **options)
        if qualification.get("passed") is not True or (
            self.backend == "cuda" and qualification.get("gpu_qualified") is not True
        ):
            raise ValueError("FIR service per-encode qualification failed")
        if self.backend == "cuda" and self.expected_device:
            from ewp_waveform.application.portable_experiments_worker import check_cuda_device

            check_cuda_device(qualification, self.expected_device)
        self.metrics["qualification"] = qualification
        self.metrics["qualification_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        worker = TorchFinisher(spec, self.device, **options)
        self.metrics["worker_setup_seconds"] = time.perf_counter() - started
        raster, finished = hashlib.sha256(), hashlib.sha256()
        counters: dict[str, Any] = {
            "frames": 0,
            "finishing_wall_seconds": 0.0,
            "batch_calls": [],
            "frame_calls": [],
        }

        def tracked() -> Iterator[bytes]:
            for frame in frames:
                raster.update(frame)
                counters["frames"] += 1
                yield frame

        def observed() -> Iterator[bytes]:
            for data in _torch_stream(tracked(), worker, kwargs["pix_fmt"], counters):
                finished.update(data)
                yield data

        encoded = {
            **kwargs,
            "glow": 0.0,
            "overscan": 0,
            "supersample": 1,
            "pix_fmt": "rgba",
            "color": None,
            "ribbon_finish": None,
        }
        encode_started = time.perf_counter()
        try:
            encoder(observed(), **encoded)
            if counters["frames"] != kwargs["n_frames"]:
                raise ValueError("FIR service original frame count mismatch")
        finally:
            encode_wall = time.perf_counter() - encode_started
            self.metrics.update(
                worker=worker.evidence(),
                raster_feed=counters,
                original_raster_sha256=raster.hexdigest(),
                finished_rgba_sha256=finished.hexdigest(),
                encoder_envelope_wall_seconds=encode_wall,
                encoder_envelope_scope="inclusive raster/finishing/serialization/feed/CPU encode; "
                "not encoder-exclusive; initialization/qualification precede this envelope",
                initialization_scope="per encode, inside service.render wall; no warmup reuse",
            )


@dataclass
class SerialLUTServiceExperiment(TorchServiceExperiment):
    """Same cache-disabled serial service/raster observation, unchanged CPU LUT encoder.

    Inherit only the bounded service hook spine; never initialize a Torch worker.
    """

    backend: str = "cpu-lut"
    device: str = "cpu"

    def __post_init__(self) -> None:
        if self.backend != "cpu-lut" or self.device != "cpu":
            raise ValueError("serial LUT service requires cpu-lut/cpu")

    def identity(self) -> dict[str, Any]:
        return {
            "adapter_revision": 1,
            "candidate": "CPU-LUT-SERIAL-SERVICE",
            "analysis_cache": "disabled",
            "ribbon_finish_lut": True,
            "flag_scope": "explicit encode hook; ordinary performance flag remains disabled",
        }

    def encode(
        self, encoder: Callable[..., None], frames: Iterable[bytes], kwargs: dict[str, Any]
    ) -> None:
        from ewp_waveform.ffmpeg.draw import parse_rgb
        from ewp_waveform.ffmpeg.torch_finish import FinishSpec

        finish = kwargs.get("ribbon_finish")
        if (
            self.metrics
            or finish is None
            or kwargs.get("ribbon_finish_lut", False)
            or kwargs.get("png_dir") is not None
            or kwargs.get("prores_path") is None
            or kwargs.get("pix_fmt") not in ("gray", "rgba")
            or kwargs.get("fps") != 60
        ):
            raise ValueError("serial LUT service requires one original-raster LUT MOV encode")
        spec = FinishSpec(
            width=kwargs["width"],
            height=kwargs["height"],
            overscan=kwargs["overscan"],
            supersample=kwargs["supersample"],
            sigma=kwargs["glow"],
            reflection=finish[0],
            horizon=finish[1],
            thickness=finish[2],
            extent=finish[3],
            opacity=finish[4],
            color=parse_rgb(kwargs["color"]),
        )
        raster = hashlib.sha256()
        count = 0

        def tracked() -> Iterator[bytes]:
            nonlocal count
            for frame in frames:
                raster.update(frame)
                count += 1
                yield frame

        started = time.perf_counter()
        try:
            # This retains the strict selected-executable identity guard and
            # per-encode LUT qualification/preparation inside service.render.
            encoder(tracked(), **{**kwargs, "ribbon_finish_lut": True})
            if count != kwargs["n_frames"]:
                raise ValueError("serial LUT service original frame count mismatch")
        finally:
            self.metrics.update(
                spec=asdict(spec),
                effective_preset=self.expected_preset,
                original_raster_sha256=raster.hexdigest(),
                raster_feed={"frames": count},
                encoder_envelope_wall_seconds=time.perf_counter() - started,
                encoder_envelope_scope="inclusive raster/feed/CPU finishing/encode and "
                "per-encode LUT qualification/preparation; not encoder-exclusive",
                initialization_scope="per encode, inside service.render wall; no warmup reuse",
            )


def compare_campaign(
    config: dict[str, Any],
    workloads: list[dict[str, Any]],
    step: Callable[..., dict[str, Any]],
    skipped: Callable[[str, str], None],
) -> None:
    """Fresh CPU LUT versus combined CUDA: exactly short4/32 ABBA, never full.

    Qualification and first renders are independent by side. Only same-side
    decoded output is an exact oracle: recursive blur and FIR differ deliberately.
    """
    if config["repeats"] != 2:
        raise ValueError("CPU/CUDA comparison requires exactly two repeats (ABBA)")
    python = config["cuda_python"]
    # CPU runs in the selected CUDA interpreter even when CUDA qualification fails.
    # An invalid interpreter will fail independently, never silently substitute one.
    lut = step(
        "compare-cpu-cuda-lut-qualification",
        {"operation": "qualify-lut"},
        optional=True,
        python=python,
    )
    cuda = step(
        "compare-cpu-cuda-cuda-qualification",
        {"operation": "qualify-finish", "backend": "cuda", **COMBINED},
        optional=True,
        python=python,
    )
    ready = {
        "A": lut.get("status") == "SUCCEEDED" and lut.get("passed") is True,
        "B": cuda.get("status") == "SUCCEEDED"
        and cuda.get("passed") is True
        and cuda.get("gpu_qualified") is True
        and bool(config.get("cuda_environment")),
    }
    short = next(w for w in workloads if w["id"] in ("speech", "smoke"))

    def pair(label: str, workload: dict[str, Any]) -> bool:
        first: dict[str, dict[str, Any]] = {}
        values: list[dict[str, Any]] = []
        raster: str | None = None
        for repeat, order in ((1, "AB"), (2, "BA")):
            for side in order:
                name = f"{label}-r{repeat:02d}-{side}"
                if not ready[side] or (repeat == 2 and side not in first):
                    skipped(
                        name, "independent side qualification/first validated render unavailable"
                    )
                    values.append({"status": "SKIPPED"})
                    continue
                request: dict[str, Any] = {
                    "operation": "service",
                    "jobs": 1,
                    "matched_cpu_cuda": True,
                    "visual_overrides": {},
                    "workload": workload,
                    "finish_lut": side == "A",
                    "torch_finish": side == "B",
                    "backend": "cpu-lut" if side == "A" else "cuda",
                    **({} if side == "A" else COMBINED),
                    "pair": {
                        "id": label,
                        "repeat": repeat,
                        "order": order,
                        "side": side,
                        "comparison": "combined serial CPU LUT recursive-blur pipeline vs CUDA "
                        "FIR device-RGBA8/batch2/ordinary pipeline; not isolated kernel speedup; "
                        "service includes lazy import/context, per-encode qualification, "
                        "publication; "
                        "exact decoded repeat oracle is same-side only",
                    },
                }
                if raster:
                    request["expected_raster_sha256"] = raster
                if side in first:
                    reference = first[side]
                    request.update(reference=reference["output"], reference_lossless=True)
                    if side == "B":
                        request["expected_finished_rgba_sha256"] = reference["finished_rgba_sha256"]
                value = step(name, request, optional=True, python=python)
                values.append(value)
                if (
                    value.get("status") == "SUCCEEDED"
                    and value.get("validation", {}).get("passed") is True
                ):
                    first.setdefault(side, value)
                    raster = raster or value["original_raster_sha256"]
        return len(values) == 4 and all(
            v.get("status") == "SUCCEEDED" and v.get("validation", {}).get("passed") is True
            for v in values
        )

    short_passed = pair("compare-cpu-cuda-short", short)
    if not short_passed or short["id"] == "smoke":
        skipped("compare-cpu-cuda-service32", "requires both complete original-input short sides")
    else:
        pair(
            "compare-cpu-cuda-service32",
            {
                "id": "service32",
                "kind": "service32",
                "start": 25.0,
                "duration": 32.0,
                "frames": 1920,
            },
        )


def campaign(
    config: dict[str, Any],
    workloads: list[dict[str, Any]],
    step: Callable[..., dict[str, Any]],
    skipped: Callable[[str, str], None],
) -> None:
    """Only combined short AB/BA, then explicitly requested serial service32 AB/BA."""
    if not config.get("cuda_environment"):
        skipped("cuda-combined", "CUDA preparation unavailable: " + str(config.get("cuda_error")))
        return
    python = config["cuda_python"]
    ready = True
    for name, options in (("control", CONTROL), ("candidate", COMBINED)):
        q = step(
            "cuda-combined-qualify-" + name,
            {"operation": "qualify-finish", "backend": "cuda", **options},
            optional=True,
            python=python,
        )
        ready = (
            ready
            and q.get("status") == "SUCCEEDED"
            and q.get("passed") is True
            and q.get("gpu_qualified") is True
        )
    if not ready:
        skipped("cuda-combined", "selected combined/control CUDA qualification failed")
        return
    short = next(w for w in workloads if w["id"] in ("speech", "smoke"))

    def pair(label: str, workload: dict[str, Any]) -> bool:
        first: dict[str, Any] = {}
        values: list[dict[str, Any]] = []
        for repeat in range(1, config["repeats"] + 1):
            order = "AB" if repeat % 2 else "BA"
            for side in order:
                name = f"{label}-r{repeat:02d}-{side}"
                control_valid = (
                    first.get("status") == "SUCCEEDED"
                    and first.get("validation", {}).get("passed") is True
                )
                if side == "B" and not control_valid:
                    skipped(name, "matched service control unavailable")
                    values.append({"status": "SKIPPED"})
                    continue
                request = {
                    "operation": "service",
                    "torch_finish": True,
                    "backend": "cuda",
                    "jobs": 1,
                    "workload": workload,
                    **(CONTROL if side == "A" else COMBINED),
                    "pair": {
                        "id": label,
                        "repeat": repeat,
                        "order": order,
                        "side": side,
                        "comparison": "combined device RGBA8 + within-file batch2 + ordinary "
                        "timing vs retained host-reuse batch1 diagnostic; same serial service API; "
                        "initialization/per-encode qualification/validation/publication included",
                    },
                }
                if control_valid:
                    request.update(
                        reference=first["output"],
                        expected_raster_sha256=first["original_raster_sha256"],
                        expected_finished_rgba_sha256=first["finished_rgba_sha256"],
                    )
                value = step(name, request, optional=True, python=python)
                values.append(value)
                if not first and side == "A":
                    first = value
        return len(values) == config["repeats"] * 2 and all(
            v.get("status") == "SUCCEEDED" and v.get("validation", {}).get("passed") is True
            for v in values
        )

    short_passed = pair("cuda-combined-short", short)
    if config.get("cuda_combined_service32"):
        if not short_passed or short["id"] == "smoke":
            skipped(
                "cuda-combined-service32", "requires complete matched original-input short pairs"
            )
        else:
            pair(
                "cuda-combined-service32",
                {
                    "id": "service32",
                    "kind": "service32",
                    "start": 25.0,
                    "duration": 32.0,
                    "frames": 1920,
                },
            )
