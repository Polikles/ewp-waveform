"""Full-source worker guards and live-prefix accounting (no CUDA claims)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.portable_experiments_worker import service_render, validate_batch_tail
from ewp_waveform.application.torch_experiment import _torch_stream


def test_entire_target_count_live_prefix_without_big_media() -> None:
    class TinyWorker:
        batch_size = 2

        def finish_batch(self, batch: list[bytes], pix_fmt: str) -> Any:
            assert pix_fmt == "gray"
            # Distinct ordinal bytes expose duplication, reordering and aliasing.
            return np.frombuffer(b"".join(batch), dtype=np.uint8).reshape(len(batch), 1, 1, 4)

    worker: Any = TinyWorker()
    frames = 23741
    counters: dict[str, Any] = {"finishing_wall_seconds": 0.0, "batch_calls": [], "frame_calls": []}
    inputs = [i.to_bytes(4, "little") for i in range(frames)]
    assert list(_torch_stream(inputs, worker, "gray", counters)) == inputs
    proof = validate_batch_tail(counters, frames, 2)
    assert proof["full_batch_count"] == frames // 2
    assert proof["batch_count"] == (frames + 1) // 2
    assert proof["final_batch_frames"] == 1
    assert proof["final_batch_first_frame"] == frames - 1
    assert proof["partial_batch_frames"] == 1


@pytest.mark.parametrize("damage", ["missing", "duplicate", "reorder", "tail-two", "emitted"])
def test_bad_batch_sequence_refused(damage: str) -> None:
    counters: dict[str, Any] = {
        "batch_calls": [
            {"frames": 2, "first_frame": 0},
            {"frames": 2, "first_frame": 2},
            {"frames": 1, "first_frame": 4},
        ],
        "emitted_frames": 5,
    }
    if damage == "missing":
        counters["batch_calls"].pop()
    elif damage == "duplicate":
        counters["batch_calls"].append({"frames": 1, "first_frame": 4})
    elif damage == "reorder":
        counters["batch_calls"][1]["first_frame"] = 0
    elif damage == "tail-two":
        counters["batch_calls"][-1]["frames"] = 2
    else:
        counters["emitted_frames"] = 4
    with pytest.raises(ValueError):
        validate_batch_tail(counters, 5, 2)


def test_finisher_missing_output_refused_before_yield() -> None:
    class Broken:
        batch_size = 2

        def finish_batch(self, batch: list[bytes], pix_fmt: str) -> Any:
            return np.zeros((1, 1, 1, 4), dtype=np.uint8)

    counters: dict[str, Any] = {"finishing_wall_seconds": 0.0, "batch_calls": [], "frame_calls": []}
    with pytest.raises(ValueError, match="output count"):
        list(_torch_stream([b"a", b"b"], Broken(), "gray", counters))  # type: ignore[arg-type]


def full_request(tmp_path: Path) -> dict[str, Any]:
    return {
        "matched_cpu_cuda": True,
        "full_source_confirmation": True,
        "jobs": 1,
        "finish_lut": True,
        "torch_finish": False,
        "backend": "cpu-lut",
        "visual_overrides": {},
        "audio": str(tmp_path / "original.wav"),
        "workload": {
            "id": "full",
            "kind": "full",
            "start": None,
            "duration": None,
            "frames": 23741,
        },
    }


@pytest.mark.parametrize("damage", ["implicit", "clip", "count", "reference", "backend", "truthy"])
def test_full_worker_request_refuses_before_any_render(tmp_path: Path, damage: str) -> None:
    request = copy.deepcopy(full_request(tmp_path))
    if damage == "implicit":
        request.pop("full_source_confirmation")
    elif damage == "clip":
        request["workload"]["duration"] = 32
    elif damage == "count":
        request["workload"]["frames"] -= 1
    elif damage == "reference":
        request["reference"] = "historical.mov"
    elif damage == "backend":
        request["backend"] = "torch-cpu"
    else:
        request["full_source_confirmation"] = "true"
    with pytest.raises(ValueError, match=r"full|bounded"):
        service_render(request)


def test_full_worker_original_sha_refusal(tmp_path: Path) -> None:
    request = full_request(tmp_path)
    Path(request["audio"]).write_bytes(b"not the original source")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        service_render(request)


def test_full_audio_plan_does_not_discover_short_intervals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ewp_waveform.application.portable_experiments_worker import audio_plan
    from ewp_waveform.domain.models import SourceMedia
    from ewp_waveform.ffmpeg import probe

    (tmp_path / "commands.jsonl").write_text("")
    media = SourceMedia(
        path=tmp_path / "original.wav",
        duration_seconds=395.6785,
        sample_rate=48000,
        channels=1,
        codec="pcm_s16le",
        format_name="wav",
        size_bytes=37985180,
    )
    monkeypatch.setattr(probe, "probe_media", lambda path: media)
    result = audio_plan(
        {
            "audio": str(media.path),
            "evidence": str(tmp_path),
            "smoke": False,
            "full_source_confirmation": True,
        }
    )
    assert result["analysis_context"] == "full-source"
    assert len(result["workloads"]) == 1
    workload = result["workloads"][0]
    assert workload["kind"] == "full" and workload["frames"] == 23741
    assert workload["start"] is workload["duration"] is None
    assert "quiet_intervals_seconds" not in result
    from ewp_waveform.application.cuda_combined_experiment import compare_full_campaign

    calls: list[dict[str, Any]] = []

    def simulated_step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append(request)
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "validation": {"passed": True},
            "original_raster_sha256": "fixture-raster",
        }

    compare_full_campaign(
        {
            "compare_cpu_cuda_full": True,
            "compare_cpu_cuda": False,
            "audio": {"sha256": "e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b"},
            "cuda_python": "same-fixture-python",
            "cuda_environment": {"fixture": True},
        },
        result,
        simulated_step,
        lambda *a: None,
    )
    assert [r["backend"] for r in calls if r["operation"] == "service"] == ["cpu-lut", "cuda"]


@pytest.mark.parametrize("side", ["A", "B"])
def test_positive_full_worker_passes_unbounded_request_to_real_service_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, side: str
) -> None:
    from types import SimpleNamespace

    from ewp_waveform.application import portable_experiments_worker as worker
    from ewp_waveform.application import service

    request = full_request(tmp_path)
    if side == "B":
        request.update(
            finish_lut=False,
            torch_finish=True,
            backend="cuda",
            output_mode="device-rgba",
            batch_size=2,
            timing_mode="ordinary",
        )
    request.update(media=str(tmp_path / "media"), evidence=str(tmp_path))
    # This is an admission/boundary simulation, not original audio or CUDA execution.
    monkeypatch.setattr(
        worker,
        "identity",
        lambda path: {"sha256": "e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b"},
    )
    media = SimpleNamespace(
        duration_seconds=395.6785, channels=1, sample_rate=48000, codec="pcm_s16le"
    )
    preset = SimpleNamespace(model_dump=lambda **kw: {"fixture": "preset"})
    plan = SimpleNamespace(action="PROCESS", media=media, job=SimpleNamespace(fps=60))
    monkeypatch.setattr(
        service,
        "plan_jobs",
        lambda *a, **kw: (None, preset, SimpleNamespace(processing={"jobs": 1}), [plan], None),
    )

    def boundary(path: Path, **kwargs: Any) -> Any:
        assert kwargs["start"] is kwargs["duration"] is None
        assert kwargs["experiment"].full_source_confirmation is True
        assert kwargs["experiment"].identity()["analysis_cache"] == "disabled"
        raise RuntimeError("admitted service boundary, no rendering performed")

    monkeypatch.setattr(service, "render", boundary)
    with pytest.raises(RuntimeError, match="admitted service boundary"):
        worker.service_render(request)
