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


def performance_file(root: Path) -> Path:
    path = root / "performance.toml"
    # JSON-quoted forward slash paths are TOML basic-string safe on Windows too.
    path.write_text(
        'schema_version=1\nname="portable-experiment"\n[processing]\n'
        "jobs=2\nffmpeg_threads=0\nchunk_seconds=60\n[workdirs]\npersistent=false\n"
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
        duration = probe_media(audio).duration_seconds
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("positive finite audio duration required")
    records = [json.loads(line) for line in log.read_text().splitlines()]
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


def service_render(request: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.application.service import plan_jobs, render
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation
    from ewp_waveform.ffmpeg.process import command_evidence

    root = Path(request["media"])
    root.mkdir(parents=True, exist_ok=False)
    evidence = Path(request["evidence"])
    performance = performance_file(root)
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
    with command_evidence(evidence / "commands.jsonl"):
        _, preset, perf, plans, _ = plan_jobs(Path(request["audio"]), **kwargs)
        if len(plans) != 1 or plans[0].action != "PROCESS" or plans[0].media is None:
            raise ValueError("exactly one fresh production PROCESS required")
        if perf.processing.get("jobs") != 2:
            raise ValueError("production jobs=2 configuration drift")
        variant = request.get("variant")
        if variant:
            from ewp_waveform.application.experiments_render import ServiceExperiment
            from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding

            kwargs["experiment"] = ServiceExperiment(
                SuiteEncoding(
                    variant,
                    evidence / "commands.jsonl",
                    request["device"],
                    request["expected_device"],
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
        w["kind"] in ("production32", "full")
        and result.get("analysis", {}).get("encode_workers") != 2
    ):
        raise ValueError("stock production route did not observe required multiprocessing pool2")
    output = Path(result["outputs"][0]["path"])
    valid = validation.inspect(
        request["ffmpeg"],
        request["ffprobe"],
        output,
        width=1400,
        height=280,
        frames=w["frames"],
        log=evidence / "commands.jsonl",
        reference=Path(request["reference"]) if request.get("reference") else None,
        lossless=request.get("variant") == "TRANSFER",
    )
    if request.get("variant") == "TRANSFER":
        valid["lossless_against_preencode"] = False
        valid["lossless_against_reference_master"] = True
    return {
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "wall_seconds": wall,
        "render_fps": valid["frames"] / wall,
        "real_time_factor": wall / (w["frames"] / 60),
        "validation": valid,
        "timer": "perf_counter immediately around stock service.render; plan and strict external "
        "validation excluded; production validation/publication included",
        "route": "EXPLICIT_SHORT_SERVICE_EXPERIMENT" if variant else "STOCK_SERVICE",
        "workload": w,
        "variant": variant,
        "output": str(output),
        "artifacts": [identity(output), identity(performance)],
        "service_result": result,
        "visual": "PENDING",
        "studio": "PENDING",
        "analysis_context": "interval-local; no full-source causal prehistory",
    }


def codec_render(request: dict[str, Any]) -> dict[str, Any]:
    """Same CPU master decode -> FFV1 encode; distinct from service throughput."""
    from ewp_waveform.ffmpeg import experiment_suite as ff
    from ewp_waveform.ffmpeg import experiment_suite_validation as validation
    from ewp_waveform.ffmpeg.experiments import run_captured

    root = Path(request["media"])
    root.mkdir(parents=True, exist_ok=False)
    log = Path(request["evidence"]) / "commands.jsonl"
    output = root / "native.mkv"
    original = Path(request["reference"])
    w = request["workload"]
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
        "workload": w,
        "gpu": gpu,
        "route": "SHARED_CPU_MOV_DECODE_CONVERSION_FFV1_ENCODING_NOT_SERVICE",
        "timer": "run_captured decode+conversion+encode+container; excludes validation",
        "reference": identity(original),
        # inspect(lossless=True) has compared every RGBA byte including hidden RGB.
        "comparison_mov": str(original),
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
    value = {"status": "SUCCEEDED", **qualify(backend, device="cuda:0")}
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
        width=1400,
        height=280,
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
    if operation == "prepare-tools":
        if os.name != "nt":
            raise ValueError(
                "--prepare-ffmpeg acquires native Windows executables; run it on Windows"
            )
        tools = importlib.import_module("ewp_waveform.ffmpeg.portable_tools")
        return {
            "status": "SUCCEEDED",
            "acquisition": tools.acquire_windows(Path(request["media"]), allow_download=True),
        }
    if operation == "views":
        return make_views(request)
    if operation == "qualify-finish":
        return qualify_finish(request)
    if operation == "audio-plan":
        return audio_plan(request)
    if operation == "service":
        return service_render(request)
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
