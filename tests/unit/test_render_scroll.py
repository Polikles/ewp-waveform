"""Characterize live scroll seams without decoding, rasterizing or encoding media."""

from __future__ import annotations

import importlib
from concurrent.futures import Future
from pathlib import Path
from typing import Any
from unittest.mock import Mock, call

import pytest

import ewp_waveform.application.render as typed_render
from ewp_waveform.application import render_scroll
from ewp_waveform.application.checkpoint import Checkpoint, ChunkRecord
from ewp_waveform.application.chunks import plan_chunks, processing_window
from ewp_waveform.application.render_scroll import ScrollHooks, run_scroll_pipeline
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.ffmpeg.encode import EncodeError
from tests.unit.test_plan import _job

render_module = importlib.import_module("ewp_waveform.application.render")


def _preset(**signal: Any) -> VisualPreset:
    preset = load_preset("iuris-default")
    return preset.model_copy(update={"signal": {**preset.signal, **signal}})


def _checkpoint() -> Checkpoint:
    return Checkpoint(
        schema_version=1,
        source_sha256="source",
        render_signature="signature",
        visual_contract_version=13,
        renderer="ffmpeg",
        fps=10.0,
        clip_start=2.0,
        clip_duration=0.6,
        chunk_seconds=0.2,
        expected_frames=6,
        want_mov=True,
        want_png=False,
        peak=0.75,
    )


def _record(index: int) -> ChunkRecord:
    return ChunkRecord(
        index=index,
        first_frame=2 * index,
        n_frames=2,
        start_seconds=index * 0.2,
        end_seconds=(index + 1) * 0.2,
    )


@pytest.mark.parametrize("style", ["classic", "mirrored", "filled", "segmented"])
@pytest.mark.parametrize(
    "opacity,expected",
    [(None, 0.25), (False, 0.25), ("0.8", 0.25), (-1.0, 0.0), (0.625, 0.625), (2.0, 1.0)],
)
def test_scroll_frame_geometry_and_live_raster_seams(
    monkeypatch: pytest.MonkeyPatch, style: str, opacity: Any, expected: float
) -> None:
    preset = _preset() if opacity is None else _preset(classic_alternate_opacity=opacity)
    preset = preset.model_copy(
        update={
            "canvas": preset.canvas.model_copy(update={"width": 20, "height": 10}),
            "waveform": preset.waveform.model_copy(update={"style": style, "window_seconds": 2.0}),
        }
    )
    bins = [0.1, 0.4]
    sampler = Mock(return_value=[0.6])
    raster = Mock(return_value=b"first")
    monkeypatch.setattr(render_module, "glow_overscan", Mock(return_value=3))
    monkeypatch.setattr(render_module, "envelope_oversample_from_signal", Mock(return_value=4))
    monkeypatch.setattr(render_module, "viewport_left_px", Mock(return_value=12.25))
    monkeypatch.setattr(render_module, "window_from_origin", sampler)
    monkeypatch.setattr(render_module, "draw_envelope_frame", raster)
    frames = render_module.iter_scroll_frames(
        bins,
        duration=100.0,
        preset=preset,
        fps=10.0,
        glow=1.5,
        first_frame=7,
        n_frames=2,
        origin=123.5,
    )
    assert next(frames) == b"first"
    # The generator must consult the live dispatcher on the next iteration too.
    replacement = Mock(return_value=b"second")
    monkeypatch.setattr(render_module, "draw_envelope_frame", replacement)
    assert list(frames) == [b"second"]
    assert (
        sampler.call_args_list
        == [
            call(bins, global_end_exclusive=142, width=105, origin=123.5),
        ]
        * 2
    )
    expected_kwargs = {
        "width": 26,
        "height": 16,
        "color": preset.waveform.color,
        "amplitude": preset.waveform.amplitude,
        "stroke_width": preset.waveform.stroke_width or 6.0,
        "style": style,
        "center_line": bool(preset.waveform.center_line),
        "scroll_phase": 9.25,
        "content_height": 10,
        "supersample": 12,
        "glow_sigma": 1.5,
        "envelope_oversample": 4,
        "classic_alternate_opacity": expected,
    }
    raster.assert_called_once_with([0.6], **expected_kwargs)
    replacement.assert_called_once_with([0.6], **expected_kwargs)


def test_prepare_preserves_decode_offsets_and_bin_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = [
        processing_window(chunk, source_duration=0.6, preroll=0.1, postroll=0.05)
        for chunk in plan_chunks(0.6, 10.0, 0.2)
    ]
    settings = render_module._envelope_settings(_preset(), 10.0, 0.0)
    decode = Mock()
    probe = Mock(return_value=Mock(sample_rate=8000))
    filtered = Mock(side_effect=[([1.0], 2.5), ([2.0], 2.5), ([3.0], 2.5)])
    origin = Mock(side_effect=[0.0, 320.0, 960.0])
    monkeypatch.setattr(render_module, "decode_mono_wav", decode)
    monkeypatch.setattr(render_module, "probe_media", probe)
    monkeypatch.setattr(render_module, "_filter_wav", filtered)
    monkeypatch.setattr(render_module, "bin_origin", origin)
    actual = render_module._prepare_chunk_envelopes(
        tmp_path / "source.wav",
        windows,
        settings,
        work=tmp_path,
        clip_start=2.0,
        width=20,
        window_seconds=0.2,
    )
    assert [item.window for item in actual] == windows
    assert [item.bins for item in actual] == [[1.0], [2.0], [3.0]]
    assert [item.origin for item in actual] == [0.0, 320.0, 960.0]
    assert decode.call_args_list == [
        call(
            tmp_path / "source.wav",
            tmp_path / f"chunk-{i:04d}.wav",
            start=2.0 + window.decode_start,
            duration=window.decode_duration,
        )
        for i, window in enumerate(windows)
    ]
    assert origin.call_args_list == [call(window.decode_start, 8000, 2.5) for window in windows]
    assert filtered.call_args_list == [
        call(tmp_path / f"chunk-{i:04d}.wav", settings, 8000, 20, 0.2) for i in range(3)
    ]


def _schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    windows = [
        processing_window(chunk, source_duration=0.6, preroll=0.1, postroll=0.05)
        for chunk in plan_chunks(0.6, 10.0, 0.2)
    ]
    monkeypatch.setattr(render_module, "glow_overscan", Mock(return_value=3))
    return {
        "windows": windows,
        "prepared_by_index": {
            w.chunk.index: render_module.PreparedChunk(w, [float(w.chunk.index)], 12.5)
            for w in windows
        },
        "completed_ok": set(),
        "preset": _preset(),
        "clip_duration": 0.6,
        "fps": 10.0,
        "glow": 1.5,
        "png_work": tmp_path / "png",
        "work": tmp_path,
        "producing_mov": True,
        "ffmpeg_threads": 0,
        "shutter_px": 0.125,
        "shutter_mix": 0.375,
        "workers": 4,
        "fail_after_chunk": None,
        "checkpoint": _checkpoint(),
        "cp_file": tmp_path / "checkpoint.json",
        "note": Mock(),
    }


def test_parallel_completion_checkpoints_out_of_order_and_keeps_worker_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    writes: list[list[int]] = []
    monkeypatch.setattr(
        render_module,
        "write_checkpoint",
        lambda path, cp: writes.append([record.index for record in cp.completed_chunks]),
    )
    pool = Mock()
    futures: list[Future[ChunkRecord]] = []

    def submit(target: Any, task: Any) -> Future[ChunkRecord]:
        assert target is render_module.encode_scroll_chunk
        assert task.ffmpeg_threads == 1
        assert task.first_frame == task.chunk_index * 2
        assert task.n_frames == 2
        assert task.origin == 12.5
        assert task.supersample == 12 and task.overscan == 3
        assert task.shutter_px == 0.125 and task.shutter_mix == 0.375
        assert task.png_dir == str((tmp_path / "png").resolve())
        assert task.prores_path == str((tmp_path / f"chunk-{task.chunk_index:04d}.mov").resolve())
        future: Future[ChunkRecord] = Future()
        future.set_result(_record(task.chunk_index))
        futures.append(future)
        return future

    pool.submit.side_effect = submit
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=pool)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(render_module, "ProcessPoolExecutor", factory)
    monkeypatch.setattr(render_module, "as_completed", lambda pending: reversed(pending))
    assert render_module._run_scroll_encodes(**kwargs) == ([], 3)
    assert writes == [[2], [2, 1], [2, 1, 0]]
    assert kwargs["checkpoint"].peak == 0.75
    assert factory.call_args.kwargs["max_workers"] == 3
    assert factory.call_args.kwargs["mp_context"].get_start_method() == "spawn"
    assert len(futures) == 3


def test_injected_stop_is_sequential_after_checkpoint_and_retains_auto_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    kwargs["completed_ok"] = {0}
    kwargs["fail_after_chunk"] = 1
    events: list[tuple[str, int]] = []

    def encode(task: Any, note: Any = None) -> ChunkRecord:
        assert task.ffmpeg_threads == 0
        assert note is kwargs["note"]
        events.append(("encode", task.chunk_index))
        return _record(task.chunk_index)

    monkeypatch.setattr(render_module, "encode_scroll_chunk", encode)
    monkeypatch.setattr(
        render_module,
        "write_checkpoint",
        lambda path, cp: events.append(("checkpoint", cp.completed_chunks[-1].index)),
    )
    pool_guard = Mock(side_effect=AssertionError("injection spawned pool"))
    monkeypatch.setattr(render_module, "ProcessPoolExecutor", pool_guard)
    with pytest.raises(RuntimeError, match="injected checkpoint stop"):
        render_module._run_scroll_encodes(**kwargs)
    assert events == [("encode", 1), ("checkpoint", 1)]
    pool_guard.assert_not_called()


def test_all_reused_does_not_build_tasks_or_allocate_png_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    kwargs["completed_ok"] = {0, 1, 2}
    guard = Mock(side_effect=AssertionError("reused work was encoded"))
    monkeypatch.setattr(render_module, "_chunk_task", guard)
    monkeypatch.setattr(render_module, "write_checkpoint", guard)
    assert render_module._run_scroll_encodes(**kwargs) == ([0, 1, 2], 0)
    assert not (tmp_path / "png").exists()
    assert kwargs["note"].call_args_list == [call(f"chunk {i}/3 reuse") for i in (1, 2, 3)]


def test_chunk_worker_preserves_numbering_validation_and_live_encode_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    window = kwargs["windows"][1]
    task = render_module._chunk_task(
        window,
        kwargs["prepared_by_index"][1],
        n_windows=3,
        preset=kwargs["preset"],
        clip_duration=0.6,
        fps=10.0,
        glow=1.5,
        png_work=tmp_path / "png",
        work=tmp_path,
        producing_mov=True,
        ffmpeg_threads=7,
        shutter_px=0.125,
        shutter_mix=0.375,
    )
    frames = iter([b"opaque-stub"])
    iterator = Mock(return_value=frames)
    encode = Mock()
    validate = Mock(return_value={"passed": True})
    monkeypatch.setattr(render_module, "iter_scroll_frames", iterator)
    monkeypatch.setattr(render_module, "encode_rgba_stream", encode)
    monkeypatch.setattr(render_module, "_validate_mov", validate)
    monkeypatch.setattr(render_module, "png_chunk_complete", Mock(return_value=True))
    monkeypatch.setattr(render_module, "sha256_file", Mock(return_value="chunk-hash"))
    result = render_module.encode_scroll_chunk(task, note=Mock())
    assert result.mov_sha256 == "chunk-hash" and result.png_count == 2
    assert result.first_frame == 2 and result.n_frames == 2
    assert encode.call_args.kwargs["png_start_number"] == 3
    assert encode.call_args.kwargs["ffmpeg_threads"] == 7
    assert encode.call_args.kwargs["supersample"] == 12
    assert encode.call_args.kwargs["shutter_px"] == 0.125
    assert encode.call_args.kwargs["shutter_mix"] == 0.375
    iterator.assert_called_once_with(
        task.bins,
        duration=0.6,
        preset=task.preset,
        fps=10.0,
        glow=1.5,
        first_frame=2,
        n_frames=2,
        origin=12.5,
    )
    validate.return_value = {"passed": False}
    with pytest.raises(EncodeError, match="chunk 0001 failed validation"):
        render_module.encode_scroll_chunk(task, note=Mock())


def test_hook_view_and_payload_aliases_are_the_live_dispatcher() -> None:
    # A static structural assignment also checks the protocol against the module.
    hooks: ScrollHooks = typed_render
    assert hooks is render_module
    assert render_module._scroll_hooks() is hooks
    assert render_module.PreparedChunk is render_scroll.PreparedChunk
    assert render_module.ChunkEncodeTask is render_scroll.ChunkEncodeTask
    assert render_module.EnvelopeSettings is render_scroll.EnvelopeSettings


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    kwargs = _schedule(tmp_path, monkeypatch)
    preset = kwargs["preset"]
    performance = load_performance("balanced")
    performance.processing["chunk_seconds"] = 0.2
    prepared = list(kwargs["prepared_by_index"].values())
    settings = render_module.EnvelopeSettings(
        oversample=4,
        aa_kind="area",
        aa_support=1.0,
        lpf_kind="sinc",
        lpf_cutoff=0.1,
        smoothing_sigma=0.0,
        scale="sqrt",
        norm_mode="auto",
        soft_clip=True,
        preroll=0.1,
        postroll=0.05,
    )
    monkeypatch.setattr(render_module, "_envelope_settings", Mock(return_value=settings))
    monkeypatch.setattr(render_module, "load_checkpoint", Mock(return_value=None))
    monkeypatch.setattr(render_module, "reset_workdir", Mock())
    monkeypatch.setattr(render_module, "_prepare_chunk_envelopes", Mock(return_value=prepared))
    monkeypatch.setattr(
        render_module, "published_bin_slice", Mock(side_effect=[[0.2], [0.6], [0.9]])
    )
    monkeypatch.setattr(render_module, "bin_peak", Mock(return_value=0.625))
    monkeypatch.setattr(render_module, "normalize_bins", Mock(side_effect=lambda bins, **kw: bins))
    monkeypatch.setattr(render_module, "write_checkpoint", Mock())
    monkeypatch.setattr(render_module, "_run_scroll_encodes", Mock(return_value=([], 3)))
    monkeypatch.setattr(render_module, "concat_videos", Mock())
    return {
        "job": _job(tmp_path / "not-opened.wav").model_copy(update={"fps": 10.0}),
        "preset": preset,
        "performance": performance,
        "source_sha": "source",
        "sig": "signature",
        "clip_start": 2.0,
        "clip_duration": 0.6,
        "expected_frames": 6,
        "work": tmp_path,
        "producing_mov": True,
        "producing_png": True,
        "glow": 1.5,
        "threads": 0,
        "fail_after_chunk": None,
        "note": Mock(),
        "analysis": {},
        "normalization": {},
        "warnings": [],
        "resume_history": [],
        "clock": PhaseTimes(),
    }


def test_pipeline_global_peak_checkpoint_precedes_encode_and_concat_is_canonical(
    pipeline: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    events = Mock()
    for name in (
        "published_bin_slice",
        "bin_peak",
        "normalize_bins",
        "write_checkpoint",
        "_run_scroll_encodes",
        "concat_videos",
    ):
        events.attach_mock(getattr(render_module, name), name)
    actual = run_scroll_pipeline(render_module._scroll_hooks(), **pipeline)
    work = pipeline["work"]
    assert actual == (work / "out.mov", work / "png")
    assert [event[0] for event in events.mock_calls] == [
        "published_bin_slice",
        "published_bin_slice",
        "published_bin_slice",
        "bin_peak",
        "normalize_bins",
        "normalize_bins",
        "normalize_bins",
        "write_checkpoint",
        "_run_scroll_encodes",
        "concat_videos",
    ]
    render_module.bin_peak.assert_called_once_with([0.2, 0.6, 0.9])
    assert pipeline["normalization"] == {"mode": "auto", "soft_clip": True, "peak": 0.625}
    assert pipeline["analysis"] == {
        "chunk_count": 3,
        "preroll_seconds": 0.1,
        "postroll_seconds": 0.05,
        "encode_workers": 3,
    }
    cp = render_module.write_checkpoint.call_args.args[1]
    assert cp.peak == 0.625 and cp.completed_chunks == []
    assert pipeline["clock"].extras["ffmpeg_threads_resolved_argument"] == 1
    render_module.concat_videos.assert_called_once_with(
        [work / f"chunk-{i:04d}.mov" for i in range(3)],
        work / "out.mov",
        list_path=work / "concat.txt",
    )
    # Report assignments must already be visible if encoding raises.
    render_module._run_scroll_encodes.side_effect = RuntimeError("injected checkpoint stop")
    render_module.published_bin_slice.side_effect = [[0.2], [0.6], [0.9]]
    pipeline["analysis"].clear()
    pipeline["normalization"].clear()
    with pytest.raises(RuntimeError, match="injected checkpoint stop"):
        run_scroll_pipeline(render_module._scroll_hooks(), **pipeline)
    assert pipeline["analysis"] == {
        "chunk_count": 3,
        "preroll_seconds": 0.1,
        "postroll_seconds": 0.05,
    }
    assert pipeline["normalization"] == {"mode": "auto", "soft_clip": True, "peak": 0.625}


@pytest.mark.parametrize(
    "valid,reused,workers,boundary",
    [
        (False, [], 3, None),
        (True, [0, 2], 1, 0.2),
        (True, [0, 1, 2], 0, 0.6),
    ],
)
def test_pipeline_stale_rejection_stored_peak_and_resume_boundary(
    pipeline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
    reused: list[int],
    workers: int,
    boundary: float | None,
) -> None:
    cp = _checkpoint()
    cp.completed_chunks = [_record(i) for i in range(3)]
    monkeypatch.setattr(render_module, "load_checkpoint", Mock(return_value=cp))
    identity = Mock(return_value=valid)
    monkeypatch.setattr(render_module, "identity_matches", identity)
    monkeypatch.setattr(render_module, "reusable_chunk_indices", Mock(return_value=reused))
    monkeypatch.setattr(render_module, "_run_scroll_encodes", Mock(return_value=(reused, workers)))
    run_scroll_pipeline(render_module._scroll_hooks(), **pipeline)
    identity.assert_called_once_with(
        cp,
        source_sha256="source",
        render_signature="signature",
        visual_contract_version=render_module.VISUAL_CONTRACT_VERSION,
        renderer="ffmpeg",
        fps=10.0,
        clip_start=2.0,
        clip_duration=0.6,
        chunk_seconds=0.2,
        expected_frames=6,
        want_mov=True,
        want_png=True,
    )
    if valid:
        render_module.reset_workdir.assert_not_called()
        render_module.bin_peak.assert_not_called()
        assert pipeline["normalization"]["peak"] == 0.75
        assert [record.index for record in cp.completed_chunks] == reused
        assert pipeline["resume_history"] == [
            {
                "resumed": True,
                "boundary_seconds": boundary,
                "reused_chunks": reused,
            }
        ]
        assert pipeline["warnings"][0].code.value == "W_JOB_RESUMED"
        assert pipeline["warnings"][0].message == (
            f"Resumed at source timestamp {boundary:.3f}s (reused {len(reused)} chunk(s))."
        )
        if workers:
            windows = render_module._prepare_chunk_envelopes.call_args.args[1]
            assert [w.chunk.index for w in windows] == [1]
        else:
            render_module._prepare_chunk_envelopes.assert_not_called()
            assert pipeline["clock"].extras["ffmpeg_threads_resolved_argument"] is None
    else:
        render_module.reset_workdir.assert_called_once_with(pipeline["work"])
        render_module.reusable_chunk_indices.assert_not_called()
        render_module.bin_peak.assert_called_once_with([0.2, 0.6, 0.9])
        assert pipeline["normalization"]["peak"] == 0.625
        assert pipeline["warnings"] == [] and pipeline["resume_history"] == []


def test_pipeline_none_normalization_and_shutter_clamping(
    pipeline: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = render_module._envelope_settings.return_value
    from dataclasses import replace

    monkeypatch.setattr(
        render_module,
        "_envelope_settings",
        Mock(
            return_value=replace(
                settings,
                norm_mode="none",
                soft_clip=False,
            )
        ),
    )
    pipeline["preset"] = _preset(shutter_degrees=180, shutter_mix=4.0)
    pipeline["producing_mov"] = False
    mov, png = run_scroll_pipeline(render_module._scroll_hooks(), **pipeline)
    assert mov is None and png == pipeline["work"] / "png"
    render_module.bin_peak.assert_not_called()
    render_module.normalize_bins.assert_not_called()
    render_module.concat_videos.assert_not_called()
    assert pipeline["normalization"] == {"mode": "none", "soft_clip": False, "peak": None}
    kwargs = render_module._run_scroll_encodes.call_args.kwargs
    preset = pipeline["preset"]
    assert kwargs["shutter_px"] == preset.canvas.width / (preset.waveform.window_seconds * 10) / 2
    assert kwargs["shutter_mix"] == 1.0


def test_parallel_preserves_first_failure_and_checkpoints_other_completions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    kwargs["ffmpeg_threads"] = 7
    first_error, later_error = EncodeError("first completion failed"), OSError("later failure")
    futures: list[Future[ChunkRecord]] = []
    for index in range(3):
        future: Future[ChunkRecord] = Future()
        if index == 1:
            future.set_result(_record(index))
        else:
            future.set_exception(first_error if index == 2 else later_error)
        futures.append(future)
    pool = Mock()
    pool.submit.side_effect = futures
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=pool)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(render_module, "ProcessPoolExecutor", factory)
    monkeypatch.setattr(render_module, "as_completed", lambda pending: reversed(pending))
    write = Mock()
    monkeypatch.setattr(render_module, "write_checkpoint", write)
    with pytest.raises(EncodeError) as caught:
        render_module._run_scroll_encodes(**kwargs)
    assert caught.value is first_error
    assert [r.index for r in kwargs["checkpoint"].completed_chunks] == [1]
    write.assert_called_once_with(kwargs["cp_file"], kwargs["checkpoint"])
    assert [entry.args[1].ffmpeg_threads for entry in pool.submit.call_args_list] == [7, 7, 7]


def test_parallel_interrupt_cancels_pending_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _schedule(tmp_path, monkeypatch)
    futures: list[Future[ChunkRecord]] = [Future() for _ in range(3)]
    pool = Mock()
    pool.submit.side_effect = futures
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=pool)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(render_module, "ProcessPoolExecutor", factory)
    monkeypatch.setattr(render_module, "as_completed", Mock(side_effect=KeyboardInterrupt))
    write = Mock()
    monkeypatch.setattr(render_module, "write_checkpoint", write)
    with pytest.raises(KeyboardInterrupt):
        render_module._run_scroll_encodes(**kwargs)
    assert all(future.cancelled() for future in futures)
    assert kwargs["checkpoint"].completed_chunks == []
    write.assert_not_called()
