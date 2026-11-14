"""Real CPU Torch + application validation/publication; never CUDA qualification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import struct
import uuid
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.cuda_combined_experiment import (
    COMBINED,
    CONTROL,
    TorchServiceExperiment,
)
from ewp_waveform.application.portable_experiments_worker import dispatch
from ewp_waveform.ffmpeg import torch_finish

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or not shutil.which("ffmpeg"),
    reason="optional real CPU Torch and FFmpeg required",
)


def test_combined_real_odd_geometry_and_alpha_boundary_batches() -> None:
    spec = torch_finish.FinishSpec(
        width=13,
        height=9,
        overscan=3,
        supersample=3,
        sigma=0.75,
        reflection=0.45,
        horizon=True,
        thickness=0.5,
        extent=0.87,
        color=(17, 129, 251),
    )
    rng = np.random.default_rng(98)
    masks = [rng.integers(0, 256, spec.input_shape, dtype=np.uint8) for _ in range(5)]
    masks[0][:] = 0
    snapshots = [mask.copy() for mask in masks]
    control = torch_finish.TorchFinisher(spec, "cpu", **CONTROL)
    combined = torch_finish.TorchFinisher(spec, "cpu", **COMBINED)
    expected = [control.finish(mask).copy() for mask in masks]
    observed: list[torch_finish.U8] = []
    for offset in (0, 2, 4):
        group = masks[offset : offset + 2]
        rgba = [np.full((*mask.shape, 4), 173, dtype=np.uint8) for mask in group]
        for image, mask in zip(rgba, group, strict=True):
            image[..., 3] = mask
        observed.extend(image.copy() for image in combined.finish_batch(rgba, "rgba"))
    for actual, reference, mask, before in zip(observed, expected, masks, snapshots, strict=True):
        assert actual.shape == (9, 13, 4)
        assert np.array_equal(actual, reference)
        assert np.array_equal(mask, before)
        assert np.all(actual[actual[..., 3] == 0, :3] == 0)
        assert np.all(actual[actual[..., 3] > 0, :3] == spec.color)
        assert np.any((actual[..., 3] > 0) & (actual[..., 3] < 255))
        oracle = torch_finish.numpy_finish(mask, spec)
        assert np.max(np.abs(actual[..., 3].astype(np.int16) - oracle[..., 3])) <= 1
    assert [r["batch_frames"] for r in combined.timings] == [2, 2, 1]
    assert all(r["download_dtype"] == "uint8-rgba" for r in combined.timings)
    assert all(
        r["host_to_device_bytes"] == r["device_to_host_bytes"] == 0 for r in combined.timings
    )

    # Inject all float32 half-byte neighbors in a full pair then a partial tail;
    # quantization/assembly still execute on actual CPU Torch, not a fake tensor.
    qspec = torch_finish.FinishSpec(width=256, height=3, overscan=0, sigma=0)
    thresholds = (np.arange(256, dtype=np.float32) + np.float32(0.5)) / np.float32(255)
    alpha = np.stack(
        [np.nextafter(thresholds, -np.inf), thresholds, np.nextafter(thresholds, np.inf)]
    )
    worker = torch_finish.TorchFinisher(qspec, "cpu", **COMBINED)
    worker._alpha = lambda values: worker.torch.from_numpy(  # type: ignore[method-assign]
        np.stack([alpha] * len(values))
    )
    for count in (2, 1):
        actual = worker.finish_batch([np.zeros(qspec.input_shape, dtype=np.uint8)] * count)
        assert np.array_equal(
            actual, torch_finish.rgba_from_alpha(np.stack([alpha] * count), qspec)
        )


def test_actual_cpu_service_combined_partial_tail_matches_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = os.environ.get("EWP_EXPERIMENT_TEST_MEDIA")
    if not parent:
        pytest.skip("explicit outside-Git synthetic media destination required")
    root = Path(parent) / ("cuda-combined-service-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    source = root / "synthetic.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(
            b"".join(struct.pack("<h", (i * 137 % 24000) - 12000) for i in range(24000))
        )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    visual = json.loads(
        (Path(__file__).resolve().parents[2] / "examples/experiments/wsl-suite.json").read_text()
    )["visual_overrides"]
    calls: list[dict[str, Any]] = []
    real_qualify = torch_finish.qualify

    def qualification(*args: Any, **kwargs: Any) -> dict[str, Any]:
        value = real_qualify(*args, **kwargs)
        calls.append({"options": kwargs, "value": value})
        return value

    monkeypatch.setattr(torch_finish, "qualify", qualification)
    results: list[dict[str, Any]] = []
    for name, options in (("control", CONTROL), ("combined", COMBINED)):
        evidence = root / (name + "-evidence")
        evidence.mkdir()
        request: dict[str, Any] = {
            "operation": "service",
            "torch_finish": True,
            "jobs": 1,
            "backend": "torch-cpu",
            **options,
            "audio": str(source),
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "original_path": os.environ["PATH"],
            "visual_overrides": {**visual, "glow_level": "none"},
            "workload": {
                "id": "synthetic",
                "kind": "short",
                "start": 0.1,
                "duration": 5 / 60,
                "frames": 5,
            },
            "media": str(root / name),
            "evidence": str(evidence),
        }
        if results:
            request.update(
                reference=results[0]["output"],
                expected_raster_sha256=results[0]["original_raster_sha256"],
                expected_finished_rgba_sha256=results[0]["finished_rgba_sha256"],
            )
        result = dispatch(request)
        assert result["validation"]["lossless_against_preencode"] is None
        assert result["validation"]["preencode_losslessness_proof"]["status"] == "NOT_PERFORMED"
        results.append(result)
        assert result["status"] == "SUCCEEDED"
        assert result["route"] == "EXPLICIT_SERIAL_FIR_SERVICE_EXPERIMENT"
        assert result["service_result"]["validation"]["passed"]
        assert result["service_result"]["analysis"]["encode_workers"] == 1
        assert result["validation"]["passed"] and result["validation"]["frames"] == 5
        assert result["qualification"]["passed"] and not result["qualification"]["gpu_qualified"]
        assert (
            result["wall_seconds"]
            >= result["qualification_seconds"] + result["worker_setup_seconds"]
        )
        assert Path(result["output"]).is_file()
        assert result["raster_feed"]["frames"] == 5
    assert len(calls) == 2  # Not one shared warmup/qualification hidden before both timers.
    assert [{k: c["options"][k] for k in COMBINED} for c in calls] == [CONTROL, COMBINED]
    assert [r["frames"] for r in results[1]["raster_feed"]["batch_calls"]] == [2, 2, 1]
    assert results[0]["original_raster_sha256"] == results[1]["original_raster_sha256"]
    assert results[0]["finished_rgba_sha256"] == results[1]["finished_rgba_sha256"]
    assert (
        results[0]["validation"]["decoded_rgba_sha256"]
        == results[1]["validation"]["decoded_rgba_sha256"]
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    (root / "cpu-proof.json").write_text(json.dumps(results, indent=2))


def test_pool_policy_refused_at_hook_boundary() -> None:
    from types import SimpleNamespace

    from ewp_waveform.config.models import PerformanceProfile

    adapter = TorchServiceExperiment(backend="torch-cpu", device="cpu")
    base = SimpleNamespace(_fixed_hooks=lambda: SimpleNamespace(_job_workers=lambda p: 2))
    hooked = adapter.pipeline_hooks(base)
    with pytest.raises(ValueError, match="serial jobs1"):
        hooked._fixed_hooks()._job_workers(PerformanceProfile(schema_version=1, name="fixture"))
