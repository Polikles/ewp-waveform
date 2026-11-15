"""Selected-Python workers for the portable driver (expensive imports stay here)."""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
import time
import wave
from array import array
from pathlib import Path
from typing import Any, cast

from ewp_waveform.application.portable_experiments_state import identity, save


def performance_file(root: Path, *, finish_lut: bool = False, jobs: int = 2) -> Path:
    if type(finish_lut) is not bool:
        raise ValueError("finish_lut must be a strict bool")
    if type(jobs) is not int or jobs not in (1, 2):
        raise ValueError("service jobs must be integer 1 or 2")
    path = root / "performance.toml"
    # JSON-quoted forward slash paths are TOML basic-string safe on Windows too.
    path.write_text(
        'schema_version=1\nname="portable-experiment"\n[processing]\n'
        f"jobs={jobs}\nffmpeg_threads=0\nchunk_seconds=60\n"
        + f"ribbon_finish_lut={str(finish_lut).lower()}\n[workdirs]\npersistent=false\n"
        "root=" + json.dumps((root / "work").as_posix()) + "\n"
        "keep_on_success=false\nkeep_on_failure=true\n",
        encoding="utf-8",
    )
    return path


def audio_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Observe duration and quiet candidates without producing or trimming source media."""
    from ewp_waveform.ffmpeg.probe import probe_media
    from ewp_waveform.ffmpeg.process import command_evidence

    audio = Path(request["audio"])
    log = Path(request["evidence"]) / "commands.jsonl"
    with command_evidence(log):
        media = probe_media(audio)
        duration = media.duration_seconds
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("positive finite audio duration required")
    records = [json.loads(line) for line in log.read_text().splitlines()]
    if request.get("full_source_confirmation"):
        if (
            request["full_source_confirmation"] is not True
            or request["smoke"]
            or abs(duration - 395.6785) > 0.000001
            or media.channels != 1
            or media.sample_rate != 48000
            or media.codec != "pcm_s16le"
        ):
            raise ValueError("full confirmation requires original mono PCM16/48kHz full source")
        return {
            "status": "SUCCEEDED",
            "source_duration_seconds": duration,
            "source_media": media.model_dump(mode="json"),
            "commands": records,
            "workloads": [
                {
                    "id": "full",
                    "kind": "full",
                    "start": None,
                    "duration": None,
                    "frames": round(duration * 60),
                }
            ],
            "analysis_context": "full-source",
        }
    if request["smoke"]:
        if duration < 0.1:
            raise ValueError("CPU smoke needs at least 0.1s of source")
        return {
            "status": "SUCCEEDED",
            "source_duration_seconds": duration,
            "commands": records,
            "workloads": [
                {
                    "id": "smoke",
                    "kind": "short",
                    "start": 0.0,
                    "duration": 0.1,
                    "frames": 6,
                    "selection": "synthetic or explicitly supplied source",
                }
            ],
        }
    if abs(duration - 395.6785) > 0.000001:
        raise ValueError("authenticated default source duration mismatch")
    intervals: list[tuple[float, float]] = []
    # Source-read-only PCM windows; no FFmpeg graph construction in application.
    # Unsupported WAV encodings produce an explicitly unverified candidate.
    try:
        with wave.open(str(audio), "rb") as source:
            if source.getsampwidth() != 2 or source.getcomptype() != "NONE":
                raise ValueError("quiet discovery requires 16-bit PCM WAV")
            block_frames = max(1, source.getframerate() // 10)
            origin: float | None = None
            cursor = 0
            while True:
                block = source.readframes(block_frames)
                if not block:
                    break
                samples = array("h")
                samples.frombytes(block)
                if sys.byteorder != "little":
                    samples.byteswap()
                seconds = cursor / source.getframerate()
                rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples))) / 32768
                if rms <= 10 ** (-45 / 20):
                    if origin is None:
                        origin = seconds
                elif origin is not None:
                    if seconds - origin >= 1.0:
                        intervals.append((origin, seconds))
                    origin = None
                cursor += len(samples) // source.getnchannels()
            if origin is not None and duration - origin >= 1.0:
                intervals.append((origin, duration))
    except (wave.Error, ValueError, OSError):
        intervals = []
    if intervals:
        a, b = max(intervals, key=lambda pair: pair[1] - pair[0])
        quiet_duration = min(4.0, math.floor((b - a) * 60) / 60)
        quiet_start = (a + b - quiet_duration) / 2
        selection = "discovered PCM RMS <=-45dBFS in 100ms windows; longest >=1s quiet interval"
    else:
        quiet_start, quiet_duration = min(120.0, max(0.0, duration - 4)), 4.0
        selection = "requested quiet candidate UNVERIFIED; no >=1s silence found or detector failed"
    workloads = [
        {
            "id": "speech",
            "kind": "short",
            "start": 25.0,
            "duration": 4.0,
            "frames": 240,
            "selection": "requested speech at source offset 25s",
        },
        {
            "id": "onset",
            "kind": "short",
            "start": 0.0,
            "duration": 4.0,
            "frames": 240,
            "selection": "source onset",
        },
        {
            "id": "quiet",
            "kind": "short",
            "start": quiet_start,
            "duration": quiet_duration,
            "frames": max(1, round(quiet_duration * 60)),
            "selection": selection,
        },
        {
            "id": "tail",
            "kind": "short",
            "start": duration - 4.0,
            "duration": 4.0,
            "frames": 240,
            "selection": "source EOF minus 4 seconds",
        },
    ]
    return {
        "status": "SUCCEEDED",
        "source_duration_seconds": duration,
        "workloads": workloads,
        "commands": records,
        "quiet_intervals_seconds": intervals,
        "analysis_context": "each render uses interval-local analysis; not a full-context excerpt",
    }


def validate_batch_tail(counters: dict[str, Any], frames: int, batch_size: int) -> dict[str, Any]:
    """Check the entire live-prefix sequence, including a final nonempty partial batch.

    Indices describe ordered iterator delivery, not independent GPU frame-content
    attestation. Complete decoded frame count and PTS are checked separately.
    """
    if type(frames) is not int or frames <= 0 or type(batch_size) is not int or batch_size <= 0:
        raise ValueError("positive integer frame count and batch size required")
    calls = counters.get("batch_calls")
    if not isinstance(calls, list):
        raise ValueError("missing batch sequence")
    cursor = 0
    for call in calls:
        expected = min(batch_size, frames - cursor)
        if (
            not isinstance(call, dict)
            or expected <= 0
            or type(call.get("frames")) is not int
            or call["frames"] != expected
            or type(call.get("first_frame")) is not int
            or call["first_frame"] != cursor
        ):
            raise ValueError("batch count/order/live-prefix mismatch")
        cursor += expected
    if cursor != frames or counters.get("emitted_frames") != frames:
        raise ValueError("missing/extra final batch or delivered frame count")
    return {
        "passed": True,
        "frames": frames,
        "batch_size": batch_size,
        "batch_count": len(calls),
        "full_batch_count": frames // batch_size,
        "final_batch_frames": calls[-1]["frames"],
        "final_batch_first_frame": calls[-1]["first_frame"],
        "partial_batch_frames": frames % batch_size,
        "ordering_scope": "sequential input/live-prefix output iterator indices; "
        "complete decoded count/cadence/PTS checked independently",
    }


def service_render(request: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.application.service import plan_jobs, render
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation
    from ewp_waveform.ffmpeg.process import command_evidence

    finish_lut = request.get("finish_lut", False)
    torch_finish = request.get("torch_finish", False)
    matched = request.get("matched_cpu_cuda", False)
    full_confirmation = request.get("full_source_confirmation", False)
    confirmation_options: dict[str, Any] = (
        {"full_source_confirmation": True} if full_confirmation else {}
    )
    w = request["workload"]
    if type(full_confirmation) is not bool or (
        full_confirmation
        and (
            matched is not True
            or w.get("kind") != "full"
            or w.get("id") != "full"
            or w.get("start") is not None
            or w.get("duration") is not None
            or type(w.get("frames")) is not int
            or w["frames"] != 23741
            or request.get("reference") is not None
            or request.get("backend") != ("cpu-lut" if finish_lut else "cuda")
            or (
                torch_finish
                and any(
                    request.get(k) != v
                    for k, v in {
                        "output_mode": "device-rgba",
                        "batch_size": 2,
                        "timing_mode": "ordinary",
                    }.items()
                )
            )
        )
    ):
        raise ValueError(
            "full confirmation requires explicit unbounded full-source CPU/CUDA request"
        )
    bounded = (
        w.get("kind") in ("short", "service32")
        and isinstance(w.get("duration"), (int, float))
        and 0 < w["duration"] <= 32
    )
    if type(matched) is not bool or (
        matched
        and (
            request.get("jobs") != 1
            or type(finish_lut) is not bool
            or type(torch_finish) is not bool
            or finish_lut == torch_finish
            or request.get("variant")
            or request.get("visual_overrides") != {}
            or not (bounded or full_confirmation)
        )
    ):
        raise ValueError(
            "matched CPU/CUDA requires bounded serial LUT/FIR or explicit full confirmation "
            "with saved production preset"
        )
    full_input = identity(Path(request["audio"])) if full_confirmation else None
    if full_input is not None and full_input["sha256"] != (
        "e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b"
    ):
        raise ValueError("full confirmation original input SHA256 mismatch")
    if type(torch_finish) is not bool or (
        torch_finish and (finish_lut or request.get("variant") or request.get("jobs", 2) != 1)
    ):
        raise ValueError("FIR service requires explicit jobs1, strict bool, no LUT/codec adapter")
    torch_adapter = None
    jobs = request.get("jobs", 2)
    if type(jobs) is not int or jobs not in (1, 2):
        raise ValueError("service jobs must be integer 1 or 2")
    if jobs != 2 and request["workload"]["kind"] == "production32":
        raise ValueError("serial service32 must not be labelled stock pool2 production32")
    if type(finish_lut) is not bool or (finish_lut and request.get("variant")):
        raise ValueError("service LUT requires a strict bool and no experiment adapter")
    root = Path(request["media"])
    root.mkdir(parents=True, exist_ok=False)
    evidence = Path(request["evidence"])
    performance = (
        # The ordinary service deliberately forbids performance-LUT + any adapter.
        # The matched CPU adapter explicitly selects LUT at its encoder hook,
        # retaining that production guard while sharing cache/raster instrumentation.
        performance_file(root, finish_lut=finish_lut and not matched, jobs=jobs)
        if finish_lut or jobs != 2
        else performance_file(root)
    )
    w = request["workload"]
    kwargs: dict[str, Any] = {
        "output_dir": root / "output",
        "preset_name": "iuris-ribbon-refined",
        "performance_name": str(performance),
        "formats": ["prores4444"],
        "start": w["start"],
        "duration": w["duration"],
        "force": True,
        **request["visual_overrides"],
    }
    if matched:
        kwargs["preset_name"] = str(
            Path(__file__).resolve().parents[3] / "presets/iuris-ribbon-refined-production.toml"
        )
    with command_evidence(evidence / "commands.jsonl"):
        _, preset, perf, plans, _ = plan_jobs(Path(request["audio"]), **kwargs)
        if len(plans) != 1 or plans[0].action != "PROCESS" or plans[0].media is None:
            raise ValueError("exactly one fresh production PROCESS required")
        if perf.processing.get("jobs") != jobs:
            raise ValueError("requested service worker policy drift")
        if full_confirmation:
            media = plans[0].media
            if (
                not math.isfinite(media.duration_seconds)
                or abs(media.duration_seconds - 395.6785) > 0.000001
                or media.channels != 1
                or media.sample_rate != 48000
                or media.codec != "pcm_s16le"
                or plans[0].job.fps != 60
                or round(media.duration_seconds * plans[0].job.fps) != w["frames"]
            ):
                raise ValueError("full confirmation source media/complete frame plan mismatch")
        variant = request.get("variant")
        if torch_finish:
            from ewp_waveform.application.cuda_combined_experiment import TorchServiceExperiment

            backend = request.get("backend", "cuda")
            torch_adapter = TorchServiceExperiment(
                backend=backend,
                device="cpu" if backend == "torch-cpu" else "cuda:0",
                output_mode=request.get("output_mode", "device-rgba"),
                batch_size=request.get("batch_size", 2),
                timing_mode=request.get("timing_mode", "ordinary"),
                expected_preset=preset.model_dump(mode="json"),
                expected_device=request.get("expected_device"),
                **confirmation_options,
            )
            kwargs["experiment"] = torch_adapter
        elif matched:
            from ewp_waveform.application.cuda_combined_experiment import SerialLUTServiceExperiment

            torch_adapter = SerialLUTServiceExperiment(
                expected_preset=preset.model_dump(mode="json"),
                **confirmation_options,
            )
            kwargs["experiment"] = torch_adapter
        if variant:
            from ewp_waveform.application.experiments_render import ServiceExperiment
            from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding

            kwargs["experiment"] = ServiceExperiment(
                SuiteEncoding(
                    variant,
                    evidence / "commands.jsonl",
                    request["device"],
                    request["expected_device"],
                    async_depth=request.get("async_depth"),
                ),
                expected_preset=preset.model_dump(mode="json"),
            )
        # Actual production API, including its validation/publication, not custom rendering.
        started = time.perf_counter()
        payloads = render(Path(request["audio"]), **kwargs)
        wall = time.perf_counter() - started
    if len(payloads) != 1:
        raise ValueError("one service result required")
    result = cast(dict[str, Any], payloads[0])
    save(evidence / "service-result.json", result)
    if (
        result.get("job", {}).get("status") != "SUCCEEDED"
        or result.get("validation", {}).get("passed") is not True
        or result.get("resume_history")
        or result.get("performance", {}).get("extras", {}).get("reused_output_formats")
    ):
        raise ValueError("production result failed fresh validated PROCESS requirements")
    if (
        w["kind"] in ("production32", "full", "service32")
        and result.get("analysis", {}).get("encode_workers") != jobs
    ):
        raise ValueError("service route did not observe required actual worker policy")
    output = Path(result["outputs"][0]["path"])
    torch_metrics = torch_adapter.metrics if torch_adapter is not None else {}
    if torch_finish or matched:
        for expected, observed in (
            ("expected_raster_sha256", "original_raster_sha256"),
            ("expected_finished_rgba_sha256", "finished_rgba_sha256"),
        ):
            if request.get(expected) not in (None, torch_metrics.get(observed)):
                raise ValueError("matched FIR service " + observed + " mismatch")
    if matched and finish_lut:
        lut = result.get("performance", {}).get("extras", {}).get("ribbon_finish_lut", {})
        if (
            lut.get("status") != "succeeded"
            or lut.get("qualification", {}).get("passed") is not True
        ):
            raise ValueError("matched CPU service requires successful per-encode LUT qualification")
        torch_metrics["lut_setup"] = lut
    if matched:
        torch_metrics.update(
            worker_interpreter={
                "executable": sys.executable,
                "version": sys.version,
                "prefix": sys.prefix,
            },
            same_side_reference=request.get("reference"),
            finishing_algorithm="ffmpeg-recursive-gblur-lut" if finish_lut else "gaussian-fir",
            raster_observation_scope="SHA-256 once per original input frame on both sides, "
            "inside service.render; observation overhead included, not subtracted",
            external_verification_scope=(
                "n=1 per side; each complete native MOV verified standalone; outside "
                "service wall, inside cold envelope; no historical/cross-side pixel oracle"
                if full_confirmation
                else "first of each side standalone; subsequent repeats decode against their own "
                "side reference; outside service wall, inside cold envelope"
            ),
        )
    if full_confirmation and torch_finish:
        torch_metrics["batch_tail_validation"] = validate_batch_tail(
            torch_metrics["raster_feed"], w["frames"], request["batch_size"]
        )
    validation_options: dict[str, Any] = {"require_silent": True} if full_confirmation else {}
    valid = validation.inspect(
        request["ffmpeg"],
        request["ffprobe"],
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=evidence / "commands.jsonl",
        reference=Path(request["reference"]) if request.get("reference") else None,
        lossless=request.get("variant") == "TRANSFER"
        or bool(
            (finish_lut or torch_finish or request.get("reference_lossless"))
            and request.get("reference")
        ),
        **validation_options,
    )
    if request.get("variant") == "TRANSFER" or (
        (finish_lut or torch_finish or request.get("reference_lossless"))
        and request.get("reference")
    ):
        valid["lossless_against_reference_master"] = True
    if full_input is not None and identity(Path(request["audio"])) != full_input:
        raise ValueError("full confirmation source changed during worker")
    # Master equality is not a comparison against finished pre-encode bytes.
    # Keep an unavailable proof distinct from a failed numerical comparison.
    valid["lossless_against_preencode"] = None
    valid["preencode_losslessness_proof"] = {
        "status": "NOT_PERFORMED",
        "reason": "service comparison verifies a reference master, not an independent "
        "finished pre-encode RGBA oracle",
        "codec_contract": "lossy ProRes",
    }
    return {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "wall_seconds": wall,
        "render_fps": valid["frames"] / wall,
        "real_time_factor": wall / (w["frames"] / 60),
        "validation": valid,
        "timer": "perf_counter immediately around actual service.render; external preplan and "
        "strict external validation excluded; imports/initialization/per-encode qualification "
        "inside render and production validation/publication included",
        "route": "MATCHED_SERIAL_CPU_CUDA_SERVICE"
        if matched
        else (
            "EXPLICIT_SERIAL_FIR_SERVICE_EXPERIMENT"
            if torch_finish
            else ("EXPLICIT_SHORT_SERVICE_EXPERIMENT" if variant else "STOCK_SERVICE")
        ),
        "workload": w,
        "variant": variant,
        "worker_policy": "serial jobs1 (not stock pool2 production32)" if jobs == 1 else "jobs2",
        "output": str(output),
        "artifacts": [identity(output), identity(performance)],
        "service_result": result,
        **torch_metrics,
        **(
            {
                "full_source_confirmation": True,
                "full_source_context": {
                    "start_seconds": 0.0,
                    "duration_seconds": plans[0].media.duration_seconds,
                    "frames": w["frames"],
                    "normalization_scope": "complete source",
                    "causal_history": "source origin through EOF; no independent intervals",
                },
            }
            if full_confirmation
            else {}
        ),
        "phase_metrics": result.get("performance", {}),
        "external_verification_seconds": valid["validation_seconds"],
        "visual": "PENDING",
        "studio": "PENDING",
        "analysis_context": "full-source"
        if w["kind"] == "full"
        else "interval-local; no full-source causal prehistory",
        "analysis_cache_policy": "disabled identically for matched serial service sides"
        if matched
        else (
            "disabled identically for both FIR service sides"
            if torch_finish
            else "fresh task-owned EWP_ANALYSIS_CACHE selector per service attempt"
        ),
        "analysis_cache_selected_path": os.environ.get("EWP_ANALYSIS_CACHE"),
        "analysis_cache_observed": result.get("performance", {})
        .get("extras", {})
        .get("analysis_cache"),
    }


def codec_render(request: dict[str, Any]) -> dict[str, Any]:
    """Same CPU master decode -> FFV1 encode; distinct from service throughput."""
    from ewp_waveform.ffmpeg import experiment_suite as ff
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation
    from ewp_waveform.ffmpeg.experiments import run_captured

    w = request["workload"]
    if request.get("codec_prefix") and (
        w["frames"] not in (6, 60)
        or w["duration"] != w["frames"] / 60
        or request.get("reference_workload", {}).get("frames", 0) < w["frames"]
    ):
        raise ValueError("codec diagnostic requires explicit 6/60-frame prefix within master")
    root = Path(request["media"])
    root.mkdir(parents=True, exist_ok=False)
    log = Path(request["evidence"]) / "commands.jsonl"
    output = root / "native.mkv"
    original = Path(request["reference"])
    gpu = request.get("gpu", False)
    argv = ff.codec_argv(
        request["ffmpeg"], original, output, gpu=gpu, device=request["device"], frames=w["frames"]
    )
    started = time.perf_counter()
    result = run_captured(argv, log, phase="shared-CPU-MOV-decode-ffv1-encode")
    wall = time.perf_counter() - started
    if gpu:
        selected_device = importlib.import_module(
            "ewp_waveform.ffmpeg.backend_qualification"
        ).selected_device
        selected_device(result.stderr.decode(errors="replace"), request["expected_device"])
    valid = validation.inspect(
        request["ffmpeg"],
        request["ffprobe"],
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=log,
        codec="ffv1",
        reference=original,
        lossless=True,
        reference_prefix_frames=w["frames"] if request.get("codec_prefix") else None,
    )
    valid["lossless_against_preencode"] = False
    valid["lossless_against_reference_master"] = True
    return {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "validation": valid,
        "output": str(output),
        "artifacts": [identity(output)],
        "wall_seconds": wall,
        "throughput_fresh": True,
        "render_fps": w["frames"] / wall,
        "external_verification_seconds": valid["validation_seconds"],
        "workload": w,
        "gpu": gpu,
        "route": "SHARED_CPU_MOV_DECODE_CONVERSION_FFV1_ENCODING_NOT_SERVICE",
        "timer": "run_captured decode+conversion+encode+container; excludes validation",
        "reference": identity(original),
        "reference_workload": request.get("reference_workload"),
        "diagnostic_scope": "n=1 bounded prefix; decode/conversion/encode/process startup mixed; "
        "not waveform render savings or pure startup attribution"
        if request.get("codec_prefix")
        else None,
        # inspect(lossless=True) has compared every RGBA byte including hidden RGB.
        "comparison_mov": None if request.get("codec_prefix") else str(original),
        "visual": "PENDING",
        "studio": "PENDING",
    }


def check_cuda_device(value: dict[str, Any], expected: str) -> None:
    import re

    names = [row["worker"]["device_name"] for row in value.get("cases", []) if row.get("worker")]
    if not names or any(re.search(expected, name, re.IGNORECASE) is None for name in names):
        raise ValueError(
            f"CUDA selected device mismatch: expected {expected!r}; observed {names!r}"
        )
    value["expected_device_regex"] = expected
    value["selected_device_match"] = True


def qualify_finish(request: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.ffmpeg.torch_finish import qualify

    backend = request["backend"]
    value = {
        "status": "SUCCEEDED",
        **qualify(
            backend,
            device="cuda:0",
            output_mode=request.get("output_mode", "host-reference"),
            batch_size=request.get("batch_size", 1),
            timing_mode=request.get("timing_mode", "diagnostic"),
        ),
    }
    if backend in ("cuda", "transfer-cuda"):
        check_cuda_device(value, request["expected_device"])
    if backend == "transfer-cuda":
        value["scope"] = "COMPUTE_FREE_TRANSFER_ONLY_NOT_GPU_FINISHING"
    return value


def make_views(request: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation

    source = Path(request["source"])
    reuse = request.get("reuse_views")
    if reuse:
        views = reuse["views"]
        return {
            "status": "SUCCEEDED",
            "native": str(source),
            "views": views,
            "alias_of": reuse["native"],
            "deduplication": "exact validated decoded RGBA hash",
            "artifacts": [identity(Path(v["path"])) for v in views],
        }
    output = Path(request["media"])
    output.mkdir(parents=True, exist_ok=False)
    # Codec worker sets comparison_mov only after full lossless RGBA validation.
    comparison = Path(request["comparison_mov"]) if request.get("comparison_mov") else source
    views = validation.make_views(
        request["ffmpeg"],
        request["ffprobe"],
        comparison,
        output,
        width=request.get("width", 1400),
        height=request.get("height", 280),
        frames=request["workload"]["frames"],
        log=Path(request["evidence"]) / "commands.jsonl",
    )
    if comparison != source:
        views[0]["role"] = "COMPARISON_MOV_EXACT_RGBA_ALIAS_NOT_NATIVE_FFV1"
    return {
        "status": "SUCCEEDED",
        "native": str(source),
        "views": views,
        "artifacts": [identity(Path(v["path"])) for v in views],
        "timer": "separate view generation/validation; excluded from render throughput",
    }


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    # PATH selection is local to this isolated worker, after original inventory.
    if request.get("ffmpeg"):
        os.environ["PATH"] = (
            str(Path(request["ffmpeg"]).parent) + os.pathsep + request["original_path"]
        )
    operation = request["operation"]
    if operation in ("service", "direct"):
        # Fresh per-attempt cache selection keeps cold AB/BA service controls
        # independent. The selected route may not use this cache; report actual
        # service cache observations rather than infer a hit from the selector.
        os.environ["EWP_ANALYSIS_CACHE"] = str(Path(request["media"]) / "analysis-cache")
    if operation == "prepare-tools":
        if os.name != "nt":
            raise ValueError(
                "--prepare-ffmpeg acquires native Windows executables; run it on Windows"
            )
        tools = importlib.import_module("ewp_waveform.ffmpeg.portable_tools")
        return {
            "status": "SUCCEEDED",
            "acquisition": tools.acquire_windows(
                Path(request["media"]), allow_download=request.get("allow_download", True)
            ),
        }
    if operation == "views":
        return make_views(request)
    if operation == "compact":
        from ewp_waveform.application.portable_optimization_extras import compact_render

        return compact_render(request)
    if operation == "qualify-lut":
        from ewp_waveform.ffmpeg.ribbon_lut import qualify_ribbon_lut

        return {
            "status": "SUCCEEDED",
            **qualify_ribbon_lut(request["ffmpeg"], Path(request["media"])),
        }
    if operation == "qualify-finish":
        return qualify_finish(request)
    if operation == "audio-plan":
        return audio_plan(request)
    if operation == "service":
        return service_render(request)
    if operation == "direct":
        from ewp_waveform.application.portable_experiments_optimize import direct_render

        return direct_render(request)
    if operation == "codec":
        return codec_render(request)
    if operation == "qualify":
        module = importlib.import_module("ewp_waveform.ffmpeg.backend_qualification")

        backends = module.qualify(
            request["ffmpeg"],
            request["ffprobe"],
            Path(request["media"]),
            device=request["device"],
            expected=request["expected_device"],
        )
        failure_states = {"EXECUTION_ERROR", "DEVICE_MISMATCH", "NUMERICAL_MISMATCH", "FAILED"}
        failures = [
            name
            for name in ("transfer", "blur", "prores", "ffv1", "same_build_control")
            if backends.get(name, {}).get("status") in failure_states
        ]
        return {"status": "SUCCEEDED", "backends": backends, "attempt_failures": failures}
    if operation == "cuda":
        torch_experiment = importlib.import_module("ewp_waveform.application.torch_experiment")

        workload = request["workload"]
        output = Path(request["media"]) / "native.mov"
        value = cast(
            dict[str, Any],
            torch_experiment.render_experiment(
                source=Path(request["audio"]),
                start=workload["start"],
                duration=workload["duration"],
                output=output,
                backend=request.get("backend", "cuda"),
                device="cuda:0",
                ffmpeg=request["ffmpeg"],
                ffprobe=request["ffprobe"],
                visual_overrides=request["visual_overrides"],
                reference=Path(request["reference"]) if request.get("reference") else None,
                output_mode=request.get("output_mode", "host-reference"),
                batch_size=request.get("batch_size", 1),
                timing_mode=request.get("timing_mode", "diagnostic"),
            ),
        )
        return {
            **value,
            "workload": workload,
            "artifacts": [identity(output)],
            "wall_seconds": value["pipeline_wall_seconds"],
            "timer": value["pipeline_timer"],
            "route": value["scope"],
            "actual_action": "PROCESS",
            "throughput_fresh": True,
            "render_fps": workload["frames"] / value["pipeline_wall_seconds"],
            "visual": "PENDING",
            "studio": "PENDING",
        }
    raise ValueError(f"unknown portable worker operation: {operation}")
