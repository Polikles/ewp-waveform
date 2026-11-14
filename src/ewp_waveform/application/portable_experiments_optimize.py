"""Small opt-in codec/thread campaign and real fixed-pipeline native output seam."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast


def direct_render(request: dict[str, Any]) -> dict[str, Any]:
    """Production analysis/raster/finishing -> encoder, never MOV -> FFV1 transcode.

    This is not service publication: native MKV remains an experimental artifact.
    Both codec sides use this exact wrapper; stock service is a separate control.
    """
    from ewp_waveform.application import render as rendering
    from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
    from ewp_waveform.application.portable_experiments_state import identity
    from ewp_waveform.application.portable_experiments_worker import performance_file
    from ewp_waveform.application.render_fixed import FixedHooks, run_fixed_pipeline
    from ewp_waveform.application.service import plan_jobs
    from ewp_waveform.application.timing import PhaseTimes
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation
    from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding
    from ewp_waveform.ffmpeg.process import command_evidence

    w = request["workload"]
    codec = request.get("codec", "ffv1")
    if codec not in ("ffv1", "prores") or not 0 < w["duration"] <= 32:
        raise ValueError("direct pipeline requires prores/ffv1 and explicit duration <=32s")
    root, evidence = Path(request["media"]), Path(request["evidence"])
    root.mkdir(parents=True, exist_ok=False)
    performance = performance_file(root)
    log = evidence / "commands.jsonl"
    with command_evidence(log):
        _, preset, perf, plans, _ = plan_jobs(
            Path(request["audio"]),
            output_dir=root / "unused-service-output",
            preset_name="iuris-ribbon-refined",
            performance_name=str(performance),
            formats=["prores4444"],
            start=w["start"],
            duration=w["duration"],
            force=True,
            **request["visual_overrides"],
        )
    if len(plans) != 1 or plans[0].action != "PROCESS" or plans[0].media is None:
        raise ValueError("direct pipeline requires exactly one fresh PROCESS")
    plan = plans[0]
    assert plan.media is not None
    # The experimental output hook is serial. A32s direct pair is not the stock
    # production32 pool2 route; keep both codec sides on this same explicit policy.
    perf = perf.model_copy(deep=True)
    perf.processing["jobs"] = 1
    clip_start, clip_duration = rendering._clip_bounds(plan.media, w["start"], w["duration"])
    if plan.job.fps != 60 or max(1, round(clip_duration * plan.job.fps)) != w["frames"]:
        raise ValueError("frozen direct workload differs from effective clipped timeline")
    appearance = resolve_fixed_axis_appearance(preset)
    output = root / ("native.mkv" if codec == "ffv1" else "native.mov")
    spec = SuiteEncoding(
        "FFV1-DIRECT" if codec == "ffv1" else "CPU-CONTROL",
        log,
        encoder_threads=request.get("encoder_threads"),
        filter_threads=request.get("filter_threads"),
    )
    digest = hashlib.sha256()
    raster_count = 0

    class Hooks:
        def __getattr__(self, name: str) -> Any:
            return getattr(rendering, name)

        def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def encode_rgba_stream(self, frames: Any, **kwargs: Any) -> None:
            def observed() -> Iterator[bytes]:
                nonlocal raster_count
                for frame in frames:
                    digest.update(frame)
                    raster_count += 1
                    yield frame

            kwargs.update(prores_path=output)
            rendering.encode_rgba_stream(observed(), **kwargs, experiment=spec)

    class Publication:
        def publish_mov(self, path: Path, *, failure_message: str) -> None:
            if not output.is_file():
                raise ValueError(failure_message)

        def publish_png(self, path: Path) -> None:
            raise ValueError("direct pipeline has no PNG publication")

    clock = PhaseTimes()
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}
    source = identity(Path(request["audio"]))
    started = time.perf_counter()
    with command_evidence(log):
        run_fixed_pipeline(
            cast(FixedHooks, Hooks()),
            job=plan.job,
            media=plan.media,
            preset=preset,
            performance=perf,
            appearance=appearance,
            spectrum_contour=False,
            ribbon_ss=appearance.ribbon_ss,
            source_sha=source["sha256"],
            clip_start=clip_start,
            clip_duration=clip_duration,
            expected_frames=w["frames"],
            work=root / "work",
            producing_mov=True,
            producing_png=False,
            glow=rendering._glow_sigma(preset),
            threads=0,
            note=lambda _: None,
            lifecycle=Publication(),
            analysis=analysis,
            normalization=normalization,
            clock=clock,
        )
    wall = time.perf_counter() - started
    clock.extras["actual_output_codec"] = codec
    clock.extras["encoding_options_requested"] = spec.identity()
    clock.extras["fingerprint_scope"] = (
        "inherited production render plan; actual codec/options above"
    )
    if raster_count != w["frames"] or analysis.get("encode_workers") != 1:
        raise ValueError("direct pipeline requires bounded serial original raster")
    raster_sha = digest.hexdigest()
    if request.get("expected_raster_sha256") not in (None, raster_sha):
        raise ValueError("matched original raster mismatch")
    valid = validation.inspect(
        request["ffmpeg"],
        request["ffprobe"],
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=log,
        codec=codec,
        reference=Path(request["reference"]) if request.get("reference") else None,
        lossless=request.get("reference_lossless", False),
    )
    # The reference may be a lossy MOV, never assert losslessness against it.
    valid["lossless_against_preencode"] = False
    valid["lossless_against_reference_master"] = bool(request.get("reference_lossless"))
    return {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "wall_seconds": wall,
        "render_fps": valid["frames"] / wall,
        "real_time_factor": wall / (valid["frames"] / 60),
        "validation": valid,
        "external_verification_seconds": valid["validation_seconds"],
        "timer": "perf_counter around run_fixed_pipeline including raster hash/feed/finish/encode; "
        "excludes planning, imports, external validation and views; no service publication",
        "route": "EXPLICIT_SERIAL_PRODUCTION_FIXED_PIPELINE_NATIVE_NOT_SERVICE",
        "workload": w,
        "output": str(output),
        "codec": codec,
        "encoding": spec.identity(),
        "original_raster_sha256": raster_sha,
        "effective_preset": preset.model_dump(mode="json"),
        "phase_metrics": clock.snapshot(),
        "analysis": analysis,
        "normalization": normalization,
        "artifacts": [identity(output), identity(performance)],
        "source": source,
        "visual": "PENDING",
        "studio": "PENDING",
        "analysis_cache_policy": "disabled identically on both direct-pipeline sides",
        "execution_policy": "explicit serial jobs1; "
        "32s direct pairs are not stock pool2 production32",
        "claim": "direct native output; no master decode; no Resolve support or speedup claim",
    }


def campaign(
    config: dict[str, Any],
    workloads: list[dict[str, Any]],
    step: Callable[..., dict[str, Any]],
    skipped: Callable[[str, str], None],
    qualification: dict[str, Any],
) -> None:
    """One speech clip; independent encoder/filter controls, not a Cartesian matrix."""
    from ewp_waveform.application.portable_experiments import (
        backend_failure_reason,
        backend_passed,
    )

    w = next((w for w in workloads if w["id"] in ("speech", "smoke")), None)
    if w is None:
        raise ValueError("optimization shortlist requires speech or smoke workload")
    base = {"operation": "direct", "workload": w}
    stock = step("opt-stock-service", {"operation": "service", "workload": w})

    def pair(label: str, a: dict[str, Any], b: dict[str, Any], comparison: str) -> None:
        first: dict[str, Any] = {}
        for ordinal in range(1, config.get("repeats", 2) + 1):
            order = "AB" if ordinal % 2 else "BA"
            for side in order:
                request = dict(a if side == "A" else b)
                if side == "B" and request["operation"] == "direct":
                    if first.get("status") != "SUCCEEDED":
                        skipped(
                            f"{label}-r{ordinal:02d}-{side}", "matched direct control unavailable"
                        )
                        continue
                    request.update(
                        reference=first["output"],
                        reference_lossless=a.get("codec") == b.get("codec"),
                        expected_raster_sha256=first["original_raster_sha256"],
                    )
                value = step(
                    f"{label}-r{ordinal:02d}-{side}",
                    {
                        **request,
                        "pair": {
                            "id": label,
                            "repeat": ordinal,
                            "order": order,
                            "side": side,
                            "comparison": comparison,
                        },
                    },
                    optional=True,
                )
                if side == "A" and not first:
                    first = value

    # The stock API remains visible, but never divide its different wrapper wall
    # by the direct pipeline wall. Codec comparison uses identical wrappers.
    pair(
        "opt-direct-ffv1",
        {**base, "codec": "prores", "reference": stock["output"], "reference_lossless": True},
        {**base, "codec": "ffv1"},
        "matched production pipeline; ProRes vs direct FFV1 codec/container",
    )
    for setting, key in (("encoder_threads", "encoder"), ("filter_threads", "filter")):
        selected = config["optimization"][setting]
        if selected is not None:
            codec = "prores" if key == "filter" else "ffv1"
            pair(
                "opt-" + codec + "-" + key,
                {**base, "codec": codec},
                {**base, "codec": codec, setting: selected},
                "same direct " + codec + " pipeline; only " + setting + " changes",
            )
    depth = config["optimization"].get("async_depth")
    if config["optimization"].get("ffv1_gpu"):
        if backend_passed(qualification, "ffv1") and w["frames"] >= 60:
            for frames in (6, 60):
                prefix = {
                    **w,
                    "id": f"ffv1-prefix{frames}",
                    "frames": frames,
                    "duration": frames / 60,
                }
                request = {
                    "operation": "codec",
                    "workload": prefix,
                    "reference": stock["output"],
                    "reference_workload": w,
                    "codec_prefix": True,
                }
                for gpu in (False, True):
                    step(
                        f"opt-ffv1-prefix{frames}-{'gpu' if gpu else 'cpu'}",
                        {**request, "gpu": gpu},
                        optional=True,
                    )
        else:
            skipped(
                "opt-ffv1-prefix",
                "requires at least60 master frames; "
                + backend_failure_reason(qualification, "ffv1"),
            )
    if depth is not None:
        if backend_passed(qualification, "prores"):
            service = {"operation": "service", "workload": w}
            cpu = step(
                "opt-prores-matched-cpu", {**service, "variant": "PRORES-MATCHED"}, optional=True
            )
            if cpu.get("status") == "SUCCEEDED":
                service["reference"] = cpu["output"]
                pair(
                    "opt-prores-async",
                    {**service, "variant": "PRORES-GPU", "async_depth": 1},
                    {**service, "variant": "PRORES-GPU", "async_depth": depth},
                    "same qualified Vulkan ProRes service; only async_depth changes",
                )
            else:
                skipped(
                    "opt-prores-async", "matched CPU oracle failed; dependent async screen not run"
                )
        else:
            skipped("opt-prores-async", backend_failure_reason(qualification, "prores"))
