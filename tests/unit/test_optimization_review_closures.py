from __future__ import annotations

from pathlib import Path
from typing import Any

from ewp_waveform.application import portable_experiments_worker as worker
from ewp_waveform.application import torch_experiment
from ewp_waveform.application.portable_experiments_optimize import campaign
from ewp_waveform.ffmpeg import torch_finish


def test_render_worker_forwards_each_fir_selector(tmp_path: Path, monkeypatch: Any) -> None:
    output = tmp_path / "native.mov"
    output.write_bytes(b"explicit spy fixture, not media")
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"pipeline_wall_seconds": 1, "pipeline_timer": "spy", "scope": "spy"}

    monkeypatch.setattr(torch_experiment, "render_experiment", spy)
    worker.dispatch(
        {
            "operation": "cuda",
            "audio": "unused.wav",
            "media": str(tmp_path),
            "workload": {"start": 0, "duration": 0.1, "frames": 6},
            "backend": "torch-cpu",
            "ffmpeg": "/usr/bin/ffmpeg",
            "ffprobe": "/usr/bin/ffprobe",
            "original_path": "/usr/bin:/bin",
            "visual_overrides": {},
            "output_mode": "device-alpha8",
            "batch_size": 2,
            "timing_mode": "ordinary",
        }
    )
    assert (seen["output_mode"], seen["batch_size"], seen["timing_mode"]) == (
        "device-alpha8",
        2,
        "ordinary",
    )


def test_qualification_worker_forwards_each_fir_selector(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def spy(backend: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(torch_finish, "qualify", spy)
    worker.qualify_finish(
        {
            "backend": "torch-cpu",
            "output_mode": "device-alpha8",
            "batch_size": 2,
            "timing_mode": "ordinary",
        }
    )
    assert (seen["output_mode"], seen["batch_size"], seen["timing_mode"]) == (
        "device-alpha8",
        2,
        "ordinary",
    )


def test_failed_matched_oracle_skips_only_async_screen() -> None:
    names: list[str] = []
    skips: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        names.append(name)
        if name == "opt-prores-matched-cpu":
            return {"status": "FAILED", "error": "explicit injected test failure"}
        return {"status": "SUCCEEDED", "output": "spy.mov", "original_raster_sha256": "spy"}

    campaign(
        {
            "repeats": 2,
            "optimization": {"encoder_threads": 2, "filter_threads": 1, "async_depth": 4},
        },
        [{"id": "speech", "duration": 0.1, "frames": 6}],
        step,
        lambda name, _: skips.append(name),
        {"backends": {"prores": {"status": "PASS"}}},
    )
    assert "opt-prores-async" in skips
    assert not any(n.startswith("opt-prores-async-r") for n in names)
    assert "opt-direct-ffv1-r02-A" in names
    assert "opt-prores-filter-r02-A" in names
