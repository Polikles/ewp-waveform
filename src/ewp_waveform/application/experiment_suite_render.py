"""Stock-service full/32/short routes and explicitly separate codec-buffer routes."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

from ewp_waveform.application.experiment_suite_state import artifact
from ewp_waveform.application.experiments import frozen_configuration, sha
from ewp_waveform.ffmpeg import experiment_suite as ff
from ewp_waveform.ffmpeg import experiment_suite_validation as validation
from ewp_waveform.ffmpeg.experiments import run_captured
from ewp_waveform.ffmpeg.process import command_evidence


def performance_file(root: Path) -> Path:
    path = root / "performance.toml"
    path.write_text(
        'schema_version=1\nname="wsl-suite-balanced"\n[processing]\n'
        "jobs=2\nffmpeg_threads=0\nchunk_seconds=60\n[workdirs]\npersistent=false\nroot="
        + json.dumps(str(root / "work"))
        + "\nkeep_on_success=false\nkeep_on_failure=true\n"
    )
    return path


def planned(
    session: dict[str, Any], w: dict[str, Any], root: Path, performance: Path | None = None
) -> tuple[Any, Any, Any, Any]:
    from ewp_waveform.application.service import plan_jobs

    app, preset, perf, plans, _diagnostics = plan_jobs(
        Path(session["audio"]["path"]),
        preset_name="iuris-ribbon-refined",
        performance_name=str(performance) if performance else "balanced",
        formats=["prores4444"],
        output_dir=root / "output",
        start=w["start"],
        duration=w["duration"],
        force=True,
        **session["manifest"]["visual_overrides"],
    )
    if len(plans) != 1 or plans[0].action != "PROCESS" or plans[0].media is None:
        raise ValueError("frozen source did not plan exactly one fresh PROCESS")
    if (
        abs(plans[0].media.duration_seconds - session["manifest"]["source_duration_seconds"])
        > 0.000001
    ):
        raise ValueError("source duration mismatch")
    return app, preset, perf, plans[0]


def effective(
    session: dict[str, Any], w: dict[str, Any], root: Path, performance: Path | None = None
) -> dict[str, Any]:
    app, preset, perf, _ = planned(session, w, root, performance)
    value = frozen_configuration(preset, perf)
    reference = session["vm_reference"]["effective_visual_config"]
    if (
        value["preset"] != reference["effective_preset"]
        or value["appearance"] != reference["fixed_axis_recipe"]
    ):
        raise ValueError("effective recipe differs from authenticated VM contract")
    return {"application": app.model_dump(mode="json"), **value}


def service_cell(
    session: dict[str, Any],
    cell: dict[str, Any],
    w: dict[str, Any],
    root: Path,
    attempt: Path,
    expected: dict[str, Any],
) -> dict[str, Any]:
    from ewp_waveform.application.experiments_render import ServiceExperiment
    from ewp_waveform.application.service import render

    log = attempt / "commands.jsonl"
    perf = performance_file(root)
    if effective(session, w, root, perf) != expected:
        raise ValueError("effective frozen configuration drift")
    perf_hash = sha(perf)
    spec = {
        "A": "CPU-CONTROL",
        "B": "CPU-CONTROL",
        "C": "TRANSFER",
        "D": "BLUR",
        "E0": "PRORES-MATCHED",
        "E1": "PRORES-GPU",
    }.get(cell["scenario"])
    kwargs: dict[str, Any] = {}
    if spec is not None:
        kwargs["experiment"] = ServiceExperiment(
            ff.SuiteEncoding(spec, log, session["device"], session["expect_device_regex"]),
            expected_preset=expected["preset"],
        )
    # FULL/PRODUCTION32 use the unchanged stock service; short pairs match verbose logging.
    start = time.perf_counter()
    with command_evidence(log):
        payloads = render(
            Path(session["audio"]["path"]),
            output_dir=root / "output",
            preset_name="iuris-ribbon-refined",
            performance_name=str(perf),
            formats=["prores4444"],
            start=w["start"],
            duration=w["duration"],
            force=True,
            **session["manifest"]["visual_overrides"],
            **kwargs,
        )
    wall = time.perf_counter() - start
    if len(payloads) != 1:
        raise ValueError("one service result required")
    result = cast(dict[str, Any], payloads[0])
    if (
        result["job"]["status"] != "SUCCEEDED"
        or not result["validation"]["passed"]
        or result.get("resume_history")
        or result.get("performance", {}).get("extras", {}).get("reused_output_formats")
        or sha(perf) != perf_hash
    ):
        raise ValueError("service result is not fresh immutable validated PROCESS")
    if result["resolved_visual_config"]["effective_preset"] != expected["preset"]:
        raise ValueError("effective output settings differ from frozen preset")
    if (
        w["kind"] in ("full", "production32")
        and result.get("analysis", {}).get("encode_workers") != 2
    ):
        raise ValueError("full/production32 did not observe the required stock two-worker pool")
    observed = dict(result["resolved_visual_config"])
    observed["fixed_axis_recipe"] = dict(observed["fixed_axis_recipe"])
    observed["fixed_axis_recipe"].pop("experiment", None)
    if observed != session["vm_reference"]["effective_visual_config"]:
        raise ValueError("entire resolved visual contract differs from authenticated reference")
    output = Path(result["outputs"][0]["path"])
    with (attempt / "service-result.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    return {
        "output": str(output),
        "wall_seconds": wall,
        "scope": "ACTUAL_APPLICATION_SERVICE_RENDER_VALIDATION_PUBLICATION",
        "timer": (
            "perf_counter immediately around service.render; "
            "setup/strict external validation/views excluded"
        ),
        "route": "STOCK_SERVICE" if spec is None else "EXPLICIT_SHORT_SERVICE_EXPERIMENT",
        "service_result": result,
        "artifacts": [artifact(perf, "PERFORMANCE_CONFIGURATION")],
        "analysis_context": "full-source"
        if w["kind"] == "full"
        else "interval-local analysis/normalization/EMA; causal history starts at clipped origin",
        "noise_time_origin_seconds": w["start"] or 0.0,
    }


def fixture(
    session: dict[str, Any], w: dict[str, Any], root: Path, attempt: Path, expected: dict[str, Any]
) -> dict[str, Any]:
    from ewp_waveform.application import render as rendering
    from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
    from ewp_waveform.application.render_fixed import FixedHooks, run_fixed_pipeline
    from ewp_waveform.application.timing import PhaseTimes

    perf_file = performance_file(root)
    if effective(session, w, root, perf_file) != expected:
        raise ValueError("fixture settings drift")
    _, preset, perf, plan = planned(session, w, root, perf_file)
    output, log = root / "canonical-PREENCODE.mkv", attempt / "commands.jsonl"
    appearance = resolve_fixed_axis_appearance(preset)
    analysis: dict[str, Any] = {}
    normalization: dict[str, Any] = {}

    class Hooks:
        def __getattr__(self, name: str) -> Any:
            return getattr(rendering, name)

        def load_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def store_analysis_cache(self, *args: Any, **kwargs: Any) -> None:
            return None

        def encode_rgba_stream(self, frames: Any, **kwargs: Any) -> None:
            ff.finish_compressed(
                frames,
                output,
                ffmpeg=session["tools"]["new"]["ffmpeg"]["path"],
                command_log=log,
                **kwargs,
            )

    class Publication:
        def publish_mov(self, path: Path, *, failure_message: str) -> None:
            if not output.is_file():
                raise ValueError(failure_message)

        def publish_png(self, path: Path) -> None:
            raise ValueError("PNG not part of compressed fixture")

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
            source_sha=session["audio"]["sha256"],
            clip_start=w["start"],
            clip_duration=w["duration"],
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
            clock=PhaseTimes(),
        )
    cost = time.perf_counter() - started
    valid = validation.inspect(
        session["tools"]["new"]["ffmpeg"]["path"],
        session["tools"]["new"]["ffprobe"]["path"],
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=log,
        codec="ffv1",
    )
    return {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": False,
        "fixture": str(output),
        "validation": valid,
        "preparation_seconds": cost,
        "scope": "PRODUCTION_FINISH_PREENCODE_RGBA_LOSSLESS_COMPRESSED_NOT_SERVICE_THROUGHPUT",
        "analysis": analysis,
        "normalization": normalization,
        "artifacts": [artifact(output, "COMPRESSED_PREENCODE_ORACLE"), artifact(perf_file)],
    }


def run_cell(
    session: dict[str, Any],
    cell: dict[str, Any],
    w: dict[str, Any],
    root: Path,
    attempt: Path,
    expected: dict[str, Any],
    fixture_result: dict[str, Any] | None,
    reference_result: dict[str, Any] | None,
) -> dict[str, Any]:
    tools = session["tools"]["old" if cell["scenario"] == "A" else "new"]
    ffmpeg, ffprobe = tools["ffmpeg"]["path"], tools["ffprobe"]["path"]
    os.environ["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + session["base_path"]
    log = attempt / "commands.jsonl"
    reference: Path | None
    if cell["scenario"] in ("F0", "F1"):
        if fixture_result is None:
            raise ValueError("common pre-encode fixture missing")
        original = Path(fixture_result["fixture"])
        output = root / "tested-NATIVE.mkv"
        gpu = cell["scenario"] == "F1"
        argv = ff.codec_argv(
            ffmpeg, original, output, gpu=gpu, device=session["device"], frames=w["frames"]
        )
        started = time.perf_counter()
        proc = run_captured(argv, log, phase="timed-shared-fixture-decode-encode")
        cost = time.perf_counter() - started
        if gpu:
            ff.selected_device(proc.stderr.decode(errors="replace"), session["expect_device_regex"])
        result = {
            "output": str(output),
            "wall_seconds": cost,
            "scope": "SHARED_COMPRESSED_FIXTURE_DECODE_CONVERSION_ENCODE_CONTAINER",
            "timer": (
                "perf_counter around run_captured; includes fixture decode, command log IO "
                "and required BGRA/upload; not pure encode"
            ),
            "route": "CODEC_BUFFER_ONLY_NOT_SERVICE",
            "artifacts": [],
            "fixture_rgba_sha256": fixture_result["validation"]["decoded_rgba_sha256"],
        }
        reference, codec, lossless = original, "ffv1", True
    else:
        result = service_cell(session, cell, w, root, attempt, expected)
        output = Path(result["output"])
        reference = Path(reference_result["output"]) if reference_result is not None else None
        codec, lossless = "prores", False
    valid = validation.inspect(
        ffmpeg,
        ffprobe,
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=log,
        codec=codec,
        reference=reference,
        lossless=lossless,
    )
    if (
        cell["scenario"] == "C"
        and reference_result is not None
        and valid["decoded_rgba_sha256"] != reference_result["validation"]["decoded_rgba_sha256"]
    ):
        raise ValueError("transfer practical finishing/control equality failed")
    result.update(
        status="SUCCEEDED",
        actual_action="PROCESS",
        throughput_fresh=True,
        validation=valid,
        visual="PENDING",
        studio="PENDING",
    )
    result["artifacts"].append(artifact(output, "TESTED_NATIVE_MASTER"))
    return result
