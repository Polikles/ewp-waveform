"""Tiny numerical checks; CPU execution and sync semantics, not CUDA qualification."""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ewp_waveform.application.torch_experiment import _torch_stream, main, render_experiment
from ewp_waveform.ffmpeg.torch_finish import (
    OUTPUT_MODES,
    U8,
    FinishSpec,
    HostRGBAAssembler,
    TorchFinisher,
    numpy_finish,
    rgba_from_alpha,
)

HAS_TORCH = importlib.util.find_spec("torch") is not None


def test_reusable_host_assembly_exact_at_all_half_byte_boundaries() -> None:
    spec = FinishSpec(width=256, height=3, color=(17, 129, 251))
    thresholds = (np.arange(256, dtype=np.float32) + np.float32(0.5)) / np.float32(255)
    alpha = np.stack(
        [np.nextafter(thresholds, -np.inf), thresholds, np.nextafter(thresholds, np.inf)]
    )[None]
    alpha[0, 0, :3] = (-1, 0, 2)
    before = alpha.copy()
    assembler = HostRGBAAssembler(spec, batch_size=2)
    expected = rgba_from_alpha(alpha, spec)
    actual = assembler.assemble(alpha)
    assert np.array_equal(actual, expected)
    assert np.array_equal(alpha, before)
    assert np.all(actual[actual[..., 3] == 0, :3] == 0)
    assert np.all(actual[actual[..., 3] > 0, :3] == spec.color)
    assert actual.flags.c_contiguous


def test_reusable_buffers_partial_tail_noncontiguous_and_owned_snapshot() -> None:
    spec = FinishSpec(width=7, height=5)
    assembler = HostRGBAAssembler(spec, batch_size=3)
    buffers = (assembler.scratch, assembler.quantized, assembler.output, assembler.indices)
    full = np.linspace(-0.1, 1.1, 3 * 5 * 14, dtype=np.float32).reshape(3, 5, 14)[..., ::2]
    assert not full.flags.c_contiguous
    output = assembler.assemble(full)
    assert np.array_equal(output, rgba_from_alpha(full, spec))
    snapshot = output.copy()
    tail = assembler.assemble(np.zeros((1, 5, 7), dtype=np.float32))
    assert tail.shape == (1, 5, 7, 4)
    assert np.shares_memory(tail, output)
    assert not np.any(tail)
    assert np.array_equal(output[1:], snapshot[1:])  # Inactive capacity not touched.
    assert np.array_equal(snapshot, rgba_from_alpha(full, spec))
    assert all(
        a is b
        for a, b in zip(
            buffers,
            (assembler.scratch, assembler.quantized, assembler.output, assembler.indices),
            strict=True,
        )
    )
    quantized = np.arange(35, dtype=np.uint8).reshape(1, 5, 7)
    assert np.array_equal(assembler.from_quantized(quantized)[..., 3], quantized)


def test_host_assembler_rejects_invalid_shape_and_dtype() -> None:
    assembler = HostRGBAAssembler(FinishSpec(width=4, height=3), batch_size=2)
    for shape in ((0, 3, 4), (3, 3, 4), (1, 4, 3), (3, 4)):
        with pytest.raises(ValueError, match="shape"):
            assembler.assemble(np.zeros(shape, dtype=np.float32))
    with pytest.raises(ValueError, match="float32"):
        assembler.assemble(np.zeros((1, 3, 4), dtype=np.float64))
    with pytest.raises(ValueError, match="uint8"):
        assembler.from_quantized(np.zeros((1, 3, 4), dtype=np.float32))


@pytest.mark.parametrize("batch_size", [0, 17, 1.5, True])
def test_invalid_capacity_refused_before_torch_import(
    batch_size: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(name: str) -> None:
        raise AssertionError("optional imports must follow validation")

    monkeypatch.setattr("ewp_waveform.ffmpeg.torch_finish.importlib.import_module", forbidden)
    with pytest.raises(ValueError, match="batch_size"):
        TorchFinisher(FinishSpec(width=4, height=3), "cpu", batch_size=batch_size)


def test_oversized_geometry_refuses_before_torch_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(name: str) -> None:
        raise AssertionError("oversized geometry must refuse before optional imports")

    monkeypatch.setattr("ewp_waveform.ffmpeg.torch_finish.importlib.import_module", forbidden)
    with pytest.raises(ValueError, match="working-set"):
        TorchFinisher(FinishSpec(width=10000, height=10000), "cpu")


@pytest.mark.parametrize("backend", ["numpy", "ffmpeg", "transfer-cuda"])
def test_other_backend_controls_refuse_without_output(backend: str, tmp_path: Path) -> None:
    output = tmp_path / "absent" / "out.mov"
    with pytest.raises(ValueError, match="controls require"):
        render_experiment(
            source=tmp_path / "absent.wav",
            start=0,
            duration=0.1,
            output=output,
            backend=backend,
            output_mode="host-reuse",
        )
    assert not output.parent.exists()


@pytest.mark.skipif(not HAS_TORCH, reason="optional Torch absent")
@pytest.mark.parametrize("output_mode", OUTPUT_MODES)
@pytest.mark.parametrize("timing_mode", ["diagnostic", "ordinary"])
@pytest.mark.parametrize("sigma", [0.0, 0.75])
def test_cpu_torch_modes_full_partial_order_and_payloads(
    output_mode: str, timing_mode: str, sigma: float
) -> None:
    spec = FinishSpec(
        width=12,
        height=8,
        overscan=2,
        supersample=2,
        sigma=sigma,
        reflection=0.45,
        horizon=True,
        color=(17, 129, 251),
    )
    rng = np.random.default_rng(37)
    masks = [rng.integers(0, 256, size=spec.input_shape, dtype=np.uint8) for _ in range(5)]
    masks[0][:] = 0
    control = TorchFinisher(spec, "cpu", batch_size=3)
    worker = TorchFinisher(
        spec, "cpu", output_mode=output_mode, batch_size=3, timing_mode=timing_mode
    )
    input_buffer = worker.host_input
    actual_frames: list[U8] = []
    for offset in (0, 3):
        group = masks[offset : offset + 3]
        # Hidden source RGB must be ignored, including arbitrary colored alpha-zero pixels.
        rgba = [np.full((*mask.shape, 4), 173, dtype=np.uint8) for mask in group]
        for source, mask in zip(rgba, group, strict=True):
            source[..., 3] = mask
        actual = worker.finish_batch(rgba, "rgba")
        expected = control.finish_batch(group)
        assert np.array_equal(actual, expected)
        for output, mask in zip(actual, group, strict=True):
            oracle = numpy_finish(mask, spec)
            assert np.max(np.abs(output[..., 3].astype(np.int16) - oracle[..., 3])) <= 1
            assert np.all(output[output[..., 3] == 0, :3] == 0)
            assert np.all(output[output[..., 3] > 0, :3] == spec.color)
            # Straight alpha: low-alpha RGB remains full color, not color * alpha.
            fractional = (output[..., 3] > 0) & (output[..., 3] < 255)
            assert np.any(fractional)
            assert np.all(output[fractional, :3] == spec.color)
        actual_frames.extend(image.copy() for image in actual)
        row = worker.timings[-1]
        n = len(group)
        assert row["batch_frames"] == n and row["batch_capacity"] == 3
        assert row["upload_bytes"] == n * np.prod(spec.input_shape)
        assert row["download_bytes"] == n * spec.width * spec.height * (
            1 if output_mode == "device-alpha8" else 4
        )
        assert row["host_to_device_bytes"] == row["device_to_host_bytes"] == 0
        assert row["timing_mode"] == timing_mode
        assert row["call_wall_seconds"] >= 0
        if timing_mode == "ordinary":
            assert not any(key.endswith("cuda_event_seconds") for key in row)
            assert "compute_wall_seconds" not in row
        else:
            assert row["compute_cuda_event_seconds"] is None
    assert worker.host_input is input_buffer
    assert len(actual_frames) == 5
    assert [row["batch_frames"] for row in worker.timings] == [3, 2]
    assert [row["ordinal"] for row in worker.timings] == [0, 1]
    with pytest.raises(ValueError, match="nonempty"):
        worker.finish_batch([])
    with pytest.raises(ValueError, match="configured"):
        worker.finish_batch(masks)


@pytest.mark.skipif(not HAS_TORCH, reason="optional Torch absent")
@pytest.mark.parametrize("output_mode", OUTPUT_MODES)
def test_stream_flushes_partial_batch_without_alias_or_reordering(output_mode: str) -> None:
    spec = FinishSpec(
        width=6, height=4, overscan=0, supersample=1, sigma=0, reflection=1, horizon=False
    )
    masks = [np.full(spec.input_shape, value, dtype=np.uint8) for value in (0, 1, 37, 255, 19)]
    worker = TorchFinisher(
        spec, "cpu", output_mode=output_mode, batch_size=2, timing_mode="ordinary"
    )
    counters: dict[str, Any] = {"finishing_wall_seconds": 0.0, "batch_calls": [], "frame_calls": []}
    outputs = list(_torch_stream((mask.tobytes() for mask in masks), worker, "gray", counters))
    assert outputs == [numpy_finish(mask, spec).tobytes() for mask in masks]
    assert [row["frames"] for row in counters["batch_calls"]] == [2, 2, 1]
    assert counters["frame_calls"] == []  # No fabricated per-frame division of batch times.
    assert [row["download_bytes"] for row in worker.timings] == [
        count * spec.width * spec.height * (1 if output_mode == "device-alpha8" else 4)
        for count in (2, 2, 1)
    ]
    assert list(_torch_stream([], worker, "gray", counters)) == []


def test_phase_event_and_sync_order_not_performance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Event:
        def __init__(self, *, enable_timing: bool) -> None:
            assert enable_timing
            calls.append("event")

        def record(self, stream: str) -> None:
            assert stream == "selected-stream"
            calls.append("record")

        def elapsed_time(self, other: Event) -> float:
            calls.append("elapsed")
            return 0.0  # Mock value is not an observed CUDA measurement.

    worker = object.__new__(TorchFinisher)
    worker.cuda, worker.device = True, "cuda:7"
    worker.torch = SimpleNamespace(
        cuda=SimpleNamespace(
            Event=Event,
            device=lambda device: nullcontext(),
            current_stream=lambda device: "selected-stream",
            synchronize=lambda device: calls.append("sync:" + device),
        )
    )
    worker.timing_mode = "diagnostic"
    row: dict[str, Any] = {}

    def operation() -> int:
        calls.append("operation")
        return 37

    assert worker._phase("compute", operation, row) == 37
    assert calls == [
        "sync:cuda:7",
        "event",
        "event",
        "record",
        "operation",
        "record",
        "sync:cuda:7",
        "elapsed",
    ]
    calls.clear()
    worker.timing_mode = "ordinary"
    ordinary: dict[str, Any] = {}
    assert worker._phase("compute", operation, ordinary) == 37
    assert calls == ["operation"] and ordinary == {}


@pytest.mark.skipif(not HAS_TORCH, reason="optional Torch absent")
def test_ordinary_one_explicit_completion_sync_and_no_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = FinishSpec(width=6, height=4, overscan=0, sigma=0)
    worker = TorchFinisher(
        spec, "cpu", output_mode="host-reuse", batch_size=2, timing_mode="ordinary"
    )
    calls: list[str] = []
    monkeypatch.setattr(worker, "_sync", lambda: calls.append("completion"))
    worker.finish_batch([np.zeros(spec.input_shape, dtype=np.uint8)] * 2)
    assert calls == ["completion"]
    assert not any(key.endswith("cuda_event_seconds") for key in worker.timings[-1])


@pytest.mark.skipif(not HAS_TORCH, reason="optional Torch absent")
@pytest.mark.parametrize("output_mode", OUTPUT_MODES)
def test_cpu_quantization_all_boundary_values(
    output_mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = FinishSpec(width=256, height=3, overscan=0, sigma=0, color=(1, 129, 254))
    thresholds = (np.arange(256, dtype=np.float32) + np.float32(0.5)) / np.float32(255)
    alpha = np.stack(
        [np.nextafter(thresholds, -np.inf), thresholds, np.nextafter(thresholds, np.inf)]
    )[None]
    alpha[0, 0, :3] = (-1, 0, 2)
    worker = TorchFinisher(spec, "cpu", output_mode=output_mode, timing_mode="ordinary")
    monkeypatch.setattr(worker, "_alpha", lambda values: worker.torch.from_numpy(alpha))
    output = worker.finish_batch([np.zeros(spec.input_shape, dtype=np.uint8)])
    assert np.array_equal(output, rgba_from_alpha(alpha, spec))


@pytest.mark.skipif(not HAS_TORCH, reason="optional Torch absent")
@pytest.mark.parametrize("bad_kind", ["shape", "dtype"])
def test_payload_contract_refuses_malformed_compute(
    bad_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = FinishSpec(width=6, height=4, overscan=0, sigma=0)
    worker = TorchFinisher(spec, "cpu", output_mode="device-alpha8", timing_mode="ordinary")
    alpha = worker.torch.zeros(
        (1, 4, 6) if bad_kind == "dtype" else (1, 6, 4),
        dtype=worker.torch.float64 if bad_kind == "dtype" else worker.torch.float32,
    )
    monkeypatch.setattr(worker, "_alpha", lambda values: alpha)
    with pytest.raises(ValueError, match="float32 BxHxW"):
        worker.finish_batch([np.zeros(spec.input_shape, dtype=np.uint8)])
    assert worker.timings == []


def test_cli_passes_controls_to_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_render(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"status": "TEST_ONLY"}

    monkeypatch.setattr("ewp_waveform.application.torch_experiment.render_experiment", fake_render)
    report = tmp_path / "report.json"
    assert (
        main(
            [
                "render",
                "--source",
                "not-opened.wav",
                "--start",
                "0",
                "--duration",
                ".1",
                "--output",
                "not-created.mov",
                "--report",
                str(report),
                "--backend",
                "cuda",
                "--output-mode",
                "host-reuse",
                "--batch-size",
                "2",
                "--timing-mode",
                "ordinary",
            ]
        )
        == 0
    )
    assert seen["output_mode"] == "host-reuse"
    assert seen["batch_size"] == 2 and seen["timing_mode"] == "ordinary"
