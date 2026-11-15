"""Tiny real CPU LUT/CPU-Torch service proof; never a CUDA performance result."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import uuid
import wave
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application.cuda_combined_experiment import COMBINED
from ewp_waveform.application.portable_experiments_worker import dispatch

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or not shutil.which("ffmpeg"),
    reason="optional real CPU Torch and FFmpeg required",
)


def test_matched_real_cpu_lut_and_cpu_torch_same_side_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = os.environ.get("EWP_EXPERIMENT_TEST_MEDIA")
    if not parent:
        pytest.skip("explicit outside-Git synthetic media destination required")
    from ewp_waveform.application import service
    from ewp_waveform.ffmpeg import ribbon_lut, torch_finish

    root = Path(parent) / ("matched-tiny-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    audio = root / "synthetic.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x40\x00\xc0" * 12000)
    source_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    active = False
    qualifications: list[str] = []
    real_render = service.render
    real_lut = ribbon_lut.qualify_ribbon_lut
    real_torch = torch_finish.qualify

    def render(*args: Any, **kwargs: Any) -> Any:
        nonlocal active
        assert not active
        active = True
        try:
            return real_render(*args, **kwargs)
        finally:
            active = False

    def qualify_lut(*args: Any, **kwargs: Any) -> Any:
        assert active  # Qualification is inside each ordinary service call.
        qualifications.append("A")
        return real_lut(*args, **kwargs)

    def qualify_torch(*args: Any, **kwargs: Any) -> Any:
        assert active
        qualifications.append("B")
        assert {key: kwargs[key] for key in COMBINED} == COMBINED
        return real_torch(*args, **kwargs)

    def cache_forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("neither side may read or populate the analysis cache")

    import ewp_waveform.application.render as rendering

    monkeypatch.setattr(service, "render", render)
    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", qualify_lut)
    monkeypatch.setattr(torch_finish, "qualify", qualify_torch)
    monkeypatch.setattr(rendering, "load_analysis_cache", cache_forbidden)
    monkeypatch.setattr(rendering, "store_analysis_cache", cache_forbidden)
    first: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    for ordinal, side in enumerate("ABBA"):
        name = f"{ordinal}-{side}"
        evidence = root / (name + "-logs")
        evidence.mkdir()
        request = {
            "operation": "service",
            "matched_cpu_cuda": True,
            "jobs": 1,
            "finish_lut": side == "A",
            "torch_finish": side == "B",
            # Explicit CPU-only simulation of the candidate's ordinary service seam.
            "backend": "torch-cpu" if side == "B" else "cpu-lut",
            **({} if side == "A" else COMBINED),
            "audio": str(audio),
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "original_path": os.environ["PATH"],
            "visual_overrides": {},
            "media": str(root / name),
            "evidence": str(evidence),
            "workload": {
                "id": "synthetic",
                "kind": "short",
                "start": 0.1,
                "duration": 3 / 60,
                "frames": 3,
            },
        }
        if results:
            request["expected_raster_sha256"] = results[0]["original_raster_sha256"]
        if side in first:
            request["reference"] = first[side]["output"]
            if side == "B":
                request["expected_finished_rgba_sha256"] = first[side]["finished_rgba_sha256"]
        value = dispatch(request)
        results.append(value)
        first.setdefault(side, value)
        assert value["status"] == "SUCCEEDED" and value["validation"]["passed"]
        assert value["validation"]["frames"] == 3
        assert value["route"] == "MATCHED_SERIAL_CPU_CUDA_SERVICE"
        assert value["worker_interpreter"]["executable"] == sys.executable
        assert value["service_result"]["analysis"]["encode_workers"] == 1
        assert value["service_result"]["resolved_performance_config"]["ffmpeg_threads"] == 0
        assert "overhead included" in value["raster_observation_scope"]
        preset = value["effective_preset"]
        assert preset["waveform"]["color_mode"] == "custom"
        assert preset["waveform"]["color"] == "#C7E6EC"
        assert preset["signal"]["noise_rate"] == 0.8
        assert preset["signal"]["visual_noise"] == 0.35
        assert preset["signal"]["noise_seed"] == 1729
        assert not (root / name / "analysis-cache").exists()
        assert value["validation"]["lossless_against_preencode"] is None
        if side == "A":
            setup = value["lut_setup"]
            assert setup["qualification"]["passed"]
            assert value["wall_seconds"] >= setup["qualification_seconds"] > 0
            assert "-threads" not in setup["argv"]  # Auto requested, not a sampled thread count.
            assert (
                value["service_result"]["resolved_performance_config"]["ribbon_finish_lut"] is False
            )
        else:
            assert not value["qualification"]["gpu_qualified"]
            assert value["wall_seconds"] >= value["qualification_seconds"] > 0
            assert value["worker"]["import_seconds"] >= 0
            assert value["worker"]["context_seconds"] >= 0
            initialization = sum(
                sum(
                    case["worker"][key]
                    for key in ("import_seconds", "context_seconds", "setup_seconds")
                )
                for case in value["qualification"]["cases"]
                if case.get("worker")
            )
            assert value["qualification_seconds"] >= initialization
    assert qualifications == list("ABBA")
    assert all(r["original_raster_sha256"] == results[0]["original_raster_sha256"] for r in results)
    assert all(r["effective_preset"] == results[0]["effective_preset"] for r in results)
    assert all(r["spec"] == results[0]["spec"] for r in results)
    for side, repeat in (("A", results[3]), ("B", results[2])):
        assert (
            repeat["validation"]["decoded_rgba_sha256"]
            == first[side]["validation"]["decoded_rgba_sha256"]
        )
        assert repeat["validation"]["lossless_against_reference_master"]
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == source_sha
    (root / "cpu-only-proof.json").write_text(
        json.dumps(
            {
                "claim": "tiny real CPU LUT and CPU Torch; not CUDA qualification/performance",
                "results": results,
            },
            indent=2,
        )
    )
