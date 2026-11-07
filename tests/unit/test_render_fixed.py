"""Characterize fixed-axis orchestration with no media decode, raster or encode."""

from __future__ import annotations

import importlib
import pickle
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

import ewp_waveform.application.render as typed_render
from ewp_waveform.analysis.cache import load_analysis_cache as real_load_analysis_cache
from ewp_waveform.application import render_fixed
from ewp_waveform.application.render_fixed import FixedHooks
from ewp_waveform.application.render_types import RenderContext, RendererOutcome, RenderOptions
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.models import SourceMedia, VisualizationDomain
from tests.unit.test_plan import _job

render = importlib.import_module("ewp_waveform.application.render")


@pytest.fixture
def fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    source = tmp_path / "never-opened.wav"
    job = _job(source).model_copy(update={"domain": VisualizationDomain.FREQUENCY, "fps": 10.0})
    preset = load_preset("iuris-spectrum")
    preset = preset.model_copy(update={"signal": {**preset.signal, "smoothing": 0.25}})
    performance = load_performance("balanced")
    performance.processing.update(jobs=4, ffmpeg_threads=0)
    performance.workdirs.update(keep_on_failure=True, keep_on_success=True)
    context = RenderContext(
        job,
        SourceMedia(
            path=source,
            duration_seconds=400.0,
            sample_rate=8000,
            channels=1,
            codec="pcm_s16le",
            format_name="wav",
            size_bytes=0,
        ),
        preset,
        performance,
    )
    work = tmp_path / "work"
    work.mkdir()
    span = SimpleNamespace(fmin_hz=20.0, fmax_hz=2000.0, source="auto")
    sequence = Mock()
    sequence.__len__ = Mock(return_value=1800)
    for name in ("reset_workdir", "decode_mono_wav", "store_analysis_cache", "concat_videos"):
        monkeypatch.setattr(render, name, Mock())
    monkeypatch.setattr(render, "sha256_file", Mock(return_value="a" * 64))
    monkeypatch.setattr(
        render,
        "planned_destinations",
        Mock(
            return_value=(
                "sig",
                tmp_path / "out.mov",
                tmp_path / "png",
            )
        ),
    )
    monkeypatch.setattr(render, "publish_path", Mock(side_effect=lambda path, **kw: (path, False)))
    monkeypatch.setattr(render, "resolve_workdir", Mock(return_value=work))
    monkeypatch.setattr(render, "load_mono_pcm", Mock(return_value=([], 8000)))
    monkeypatch.setattr(render, "load_mono_f32", Mock(return_value=([0.25], 8000)))
    monkeypatch.setattr(render, "resolve_frequency_span_from_pcm", Mock(return_value=span))
    monkeypatch.setattr(render, "build_analysis_sequence", Mock(return_value=sequence))
    monkeypatch.setattr(render, "load_analysis_cache", Mock(return_value=None))
    monkeypatch.setattr(render, "analysis_cache_payload", Mock(return_value={"test": "payload"}))
    monkeypatch.setattr(render, "analysis_cache_digest", Mock(return_value="digest"))
    for name in ("spectrum_peak", "temporal_envelope_peak", "_visual_field_peak"):
        monkeypatch.setattr(render, name, Mock(return_value=0.75))
    for name in ("iter_spectrum_frames", "iter_temporal_frames", "iter_field_frames"):
        monkeypatch.setattr(render, name, Mock(return_value=iter(())))
    monkeypatch.setattr(render, "encode_rgba_stream", Mock())
    monkeypatch.setattr(render, "_validate_mov", Mock(return_value={"passed": True}))
    monkeypatch.setattr(render, "_validate_png", Mock(return_value={"passed": True}))
    monkeypatch.setattr(render.shutil, "move", Mock())
    return SimpleNamespace(
        context=context,
        work=work,
        sequence=sequence,
        span=span,
        options=RenderOptions(
            output_dir=tmp_path / "out",
            formats=["prores4444", "png"],
            force=False,
            start=2.0,
            duration=0.2,
            keep_temp=True,
            phases=PhaseTimes(),
        ),
    )


def _run(fixed: SimpleNamespace, **options: Any) -> dict[str, Any]:
    outcome: RendererOutcome = render._render_job(fixed.context, replace(fixed.options, **options))
    return outcome.payload


@pytest.mark.parametrize("geometry,mix", [("temporal_rms", 0.0), ("temporal_rms_peak", 0.3)])
@pytest.mark.parametrize("failure", [False, True])
def test_temporal_padding_reports_and_encode_failure_boundary(
    fixed: SimpleNamespace,
    geometry: str,
    mix: float,
    failure: bool,
) -> None:
    if failure:
        render.encode_rgba_stream.side_effect = RuntimeError("encode stop")
    result = _run(fixed, visual_geometry=geometry)
    render.decode_mono_wav.assert_called_once_with(
        fixed.context.job.path,
        fixed.work / "source.wav",
        start=1.25,
        duration=1.7000000000000002,
    )
    kwargs = render.iter_temporal_frames.call_args.kwargs
    assert kwargs["origin_seconds"] == 0.75 and kwargs["peak_mix"] == mix
    assert kwargs["tau_seconds"] == 0.25 and kwargs["peak"] == 0.75
    assert result["analysis"]["visual_geometry"] == geometry
    assert result["analysis"]["preroll_seconds"] == 0.75
    assert result["normalization"] == (
        {} if failure else {"mode": "auto", "soft_clip": True, "peak": 0.75}
    )
    assert result["job"]["status"] == ("FAILED" if failure else "SUCCEEDED")


@pytest.mark.parametrize("layout", ["linear", "center_out"])
@pytest.mark.parametrize("contour", [False, True])
def test_legacy_controls_and_publication_failure_keep_empty_reports(
    fixed: SimpleNamespace,
    layout: str,
    contour: bool,
) -> None:
    result = _run(
        fixed,
        spectrum_layout=layout,
        spectrum_contour=contour,
        spectrum_n_bands=32,
        spectrum_spatial_filter="gaussian",
        spectrum_spatial_scale=2.0,
        spectrum_tilt_db_per_octave=1.5,
        spectrum_compress=0.6,
        spectrum_recenter=True,
        spectrum_edge_taper=0.1,
        spectrum_slot_sigma=1.25,
        ribbon_supersample=3,
    )
    kwargs = render.iter_spectrum_frames.call_args.kwargs
    assert kwargs["layout"] == layout and kwargs["contour"] == contour
    assert kwargs["n_bands"] == 32 and kwargs["supersample"] == 3
    assert kwargs["spatial_filter"] == "gaussian" and kwargs["spatial_sigma"] > 0
    assert kwargs["tilt_db_per_octave"] == 1.5 and kwargs["compress"] == 0.6
    assert kwargs["recenter"] is True and kwargs["edge_taper"] == 0.1
    assert kwargs["slot_sigma"] == 1.25
    assert result["analysis"]["spectrum_layout"] == layout
    render._validate_png.side_effect = RuntimeError("publish stop")
    failed = _run(fixed)
    assert failed["analysis"] == failed["normalization"] == {}
    assert [o["format"] for o in failed["outputs"]] == ["prores4444"]


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("norm_mode", ["auto", "none"])
def test_field_cache_hit_cold_and_normalization_calls(
    fixed: SimpleNamespace,
    cached: bool,
    norm_mode: str,
) -> None:
    fixed.context.preset.signal["normalization"] = {"mode": norm_mode, "soft_clip": False}
    if cached:
        render.load_analysis_cache.return_value = (fixed.sequence, fixed.span)
    result = _run(fixed, spectrum_layout="field_center_out", spectrum_n_bands=32)
    render.analysis_cache_digest.assert_called_once_with({"test": "payload"})
    render.load_analysis_cache.assert_called_once_with("digest")
    if cached:
        render.decode_mono_wav.assert_not_called()
        render.build_analysis_sequence.assert_not_called()
        render.store_analysis_cache.assert_not_called()
    else:
        render.store_analysis_cache.assert_called_once_with("digest", fixed.sequence, fixed.span)
        render.decode_mono_wav.assert_called_once_with(
            fixed.context.job.path,
            fixed.work / "source.wav",
            start=2.0,
            duration=0.2,
        )
    assert result["performance"]["extras"]["analysis_cache"] == ("hit" if cached else "miss")
    assert result["normalization"] == {
        "mode": norm_mode,
        "soft_clip": False,
        "peak": 0.75 if norm_mode == "auto" else None,
    }
    kwargs = render.iter_field_frames.call_args.kwargs
    assert kwargs["soft_clip"] is False
    assert kwargs["peak"] == (0.75 if norm_mode == "auto" else None)
    assert render._visual_field_peak.call_count == (1 if norm_mode == "auto" else 0)


def test_corrupt_cache_rebuilds_via_original_loader(
    fixed: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "digest.npz"
    corrupt.write_bytes(b"not a numpy archive")
    loader = Mock(side_effect=lambda digest: real_load_analysis_cache(digest, directory=tmp_path))
    monkeypatch.setattr(render, "load_analysis_cache", loader)
    result = _run(fixed, spectrum_layout="field_center_out")
    assert result["job"]["status"] == "SUCCEEDED"
    assert result["performance"]["extras"]["analysis_cache"] == "miss"
    render.decode_mono_wav.assert_called_once()
    render.build_analysis_sequence.assert_called_once()
    render.store_analysis_cache.assert_called_once_with("digest", fixed.sequence, fixed.span)
    assert corrupt.read_bytes() == b"not a numpy archive"  # Store is intentionally stubbed.


def test_forced_mask_falls_back_for_alternate_color_and_keeps_bar_overrides(
    fixed: SimpleNamespace,
) -> None:
    result = _run(
        fixed,
        spectrum_layout="field_center_out",
        field_geometry="mirrored_bars",
        render_path="mask_fast",
        render_aa="coverage_taps",
        bar_width=3.0,
        bar_gap=9.0,
        bar_count=23,
        bar_fill=0.7,
        bar_align="count",
        bar_alternate=True,
        bar_color_b="#654321",
        bar_center_line_width=1.5,
        waveform_color="#123456",
        glow_level="none",
    )
    kwargs = render.iter_field_frames.call_args.kwargs
    plan, bars = kwargs["plan"], kwargs["bar_style"]
    assert plan.path == "rgba_2d" and plan.aa_mode == "physical_ss"
    assert bars.width == 3.0 and bars.gap == 9.0 and bars.count == 23
    assert bars.fill == 0.7 and bars.align == "count" and bars.alternate is True
    assert bars.color_b == "#654321" and bars.center_line_width == 1.5
    assert kwargs["preset"].waveform.color == "#123456" and kwargs["glow"] == 0.0
    assert result["analysis"]["render_path"] == "rgba_2d"
    assert result["resolved_visual_config"]["fixed_axis_recipe"]["bars"]["count"] == 23


@pytest.mark.parametrize("n_frames,pooled", [(1799, False), (1800, True)])
@pytest.mark.parametrize(
    "geometry", ["ribbon", "mirrored_bars", "classic_ticks", "segmented_impulse"]
)
@pytest.mark.parametrize(
    "path,aa",
    [("mask_fast", "physical_ss"), ("mask_fast", "coverage_taps"), ("rgba_2d", "coverage_taps")],
)
def test_field_pool_threshold_payload_and_ordered_concat(
    fixed: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    n_frames: int,
    pooled: bool,
    geometry: str,
    path: str,
    aa: str,
) -> None:
    rows = [[0.1]] * n_frames
    monkeypatch.setattr(render, "_precompute_field_columns", Mock(return_value=rows))
    save = Mock()
    monkeypatch.setattr(render.np, "save", save)
    pool = Mock()
    pool.map.side_effect = lambda target, tasks: [Path(t.prores_path) for t in tasks]
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=pool)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(render, "ProcessPoolExecutor", factory)
    result = _run(
        fixed,
        duration=n_frames / 10.0,
        spectrum_layout="field_center_out",
        field_geometry=geometry,
        bar_alternate=False,
        render_path=path,
        render_aa=aa,
    )
    assert result["job"]["status"] == "SUCCEEDED"
    if not pooled:
        factory.assert_not_called()
        save.assert_not_called()
        render.iter_field_frames.assert_called_once()
        return
    render.iter_field_frames.assert_not_called()
    target, tasks = pool.map.call_args.args
    assert target is render.encode_field_chunk
    assert factory.call_args.kwargs["mp_context"].get_start_method() == "spawn"
    assert [(t.first_frame, t.n_frames) for t in tasks] == render._field_frame_ranges(n_frames, 4)
    for task in tasks:
        assert pickle.loads(pickle.dumps(task)) == task
        assert task.geometry == geometry and task.plan_path == path
        assert task.ffmpeg_threads == 1 and task.columns_path.endswith("field-columns.npy")
        assert task.bar_count == 0
    assert result["analysis"]["encode_workers"] == 4
    render.concat_videos.assert_called_once_with(
        [Path(t.prores_path) for t in tasks],
        fixed.work / "spectrum.mov",
        list_path=fixed.work / "field.concat.txt",
    )


def test_temporal_iterator_looks_up_live_raster_between_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render, "temporal_envelope_columns", Mock(return_value=[0.25]))
    monkeypatch.setattr(render, "draw_spectrum_frame", Mock(return_value=b"one"))
    frames = render.iter_temporal_frames(
        [0.1],
        8000,
        n_frames=2,
        preset=load_preset("iuris-spectrum"),
        fps=10.0,
        glow=0.0,
        peak=None,
        tau_seconds=0.0,
        soft_clip=False,
        origin_seconds=2.0,
        peak_mix=0.0,
    )
    assert next(frames) == b"one"
    monkeypatch.setattr(render, "draw_spectrum_frame", Mock(return_value=b"two"))
    assert list(frames) == [b"two"]
    assert [c.kwargs["time_seconds"] for c in render.temporal_envelope_columns.call_args_list] == [
        2.0,
        2.1,
    ]


@pytest.mark.parametrize("pix_fmt,path", [("gray", "mask_fast"), ("rgba", "rgba_2d")])
@pytest.mark.parametrize("ss,taps", [(2, 1), (1, 4)])
def test_worker_keeps_range_plan_aa_and_live_raster_encoder_seams(
    monkeypatch: pytest.MonkeyPatch,
    pix_fmt: str,
    path: str,
    ss: int,
    taps: int,
) -> None:
    task = render.FieldChunkTask(
        chunk_index=1,
        n_chunks=3,
        first_frame=1,
        n_frames=2,
        columns_path="not-opened.npy",
        width=20,
        height=10,
        fps=10.0,
        color="#123456",
        amplitude=0.8,
        center_line=False,
        content_height=10,
        glow=1.5,
        png_dir="not-created-png",
        prores_path="not-created.mov",
        ffmpeg_threads=7,
        overscan=3,
        supersample=ss,
        pix_fmt=pix_fmt,
        aa_taps=taps,
        plan_path=path,
        geometry="classic_ticks",
        bar_width=2.0,
        bar_gap=12.0,
        bar_count=0,
        bar_fill=0.5,
        bar_align="period",
        bar_alternate=False,
        bar_color_b="#654321",
        bar_center_line_width=0.0,
    )
    monkeypatch.setattr(
        render.np, "load", Mock(return_value=render.np.asarray([[0.1], [0.2], [0.3]]))
    )
    first = Mock(return_value=b"first")
    second = Mock(return_value=b"second")
    monkeypatch.setattr(render, "raster_field_columns", first)

    def encode(frames: Any, **kwargs: Any) -> None:
        assert next(frames) == b"first"
        monkeypatch.setattr(render, "raster_field_columns", second)
        assert list(frames) == [b"second"]
        assert kwargs["png_start_number"] == 2 and kwargs["n_frames"] == 2
        assert kwargs["supersample"] == ss and kwargs["ffmpeg_threads"] == 7
        assert kwargs["pix_fmt"] == pix_fmt
        assert kwargs["color"] == ("#123456" if pix_fmt == "gray" else None)

    encoder = Mock(side_effect=encode)
    monkeypatch.setattr(render, "encode_rgba_stream", encoder)
    assert render.encode_field_chunk(task) == Path("not-created.mov")
    render.np.load.assert_called_once_with("not-opened.npy", mmap_mode="r")
    assert first.call_args.args == ([0.2],) and second.call_args.args == ([0.3],)
    kwargs = first.call_args.kwargs
    assert kwargs["width"] == 26 and kwargs["height"] == 16
    assert kwargs["plan"].path == path and kwargs["plan"].geometry == "classic_ticks"
    assert kwargs["plan"].aa_mode == ("coverage_taps" if taps > 1 and ss == 1 else "physical_ss")
    assert kwargs["bar_style"].count is None
    assert kwargs["bar_style"].color_b == "#654321" and kwargs["center_line"] is False
    encoder.assert_called_once()


@pytest.mark.parametrize("length", [1, 240, 241, 480])
def test_visual_peak_sampling_and_precompute_keep_canonical_columns(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    sequence = list(range(length))
    mapping = Mock()
    mapping.apply.side_effect = lambda frame: frame
    monkeypatch.setattr(
        render, "field_to_columns", Mock(side_effect=lambda field, width: [float(field)])
    )
    monkeypatch.setattr(render, "apply_spectrum_spatial", Mock(side_effect=lambda cols, **kw: cols))
    monkeypatch.setattr(render, "bin_peak", Mock(return_value=0.5))
    assert (
        render._visual_field_peak(
            sequence,
            width=20,
            spatial_sigma=1.25,
            spatial_filter="gaussian",
            mapping=mapping,
        )
        == 0.5
    )
    step = 1 if length <= 240 else max(1, length // 120)
    render.bin_peak.assert_called_once_with([float(i) for i in range(0, length, step)])
    assert mapping.apply.call_count == len(range(0, length, step))
    monkeypatch.setattr(render, "normalize_bins", Mock(side_effect=lambda cols, **kw: cols))
    monkeypatch.setattr(render, "blend_columns", Mock(side_effect=lambda prev, raw, alpha: raw))
    rows = render._precompute_field_columns(
        sequence,
        n_frames=2,
        draw_w=26,
        peak=0.5,
        tau_seconds=0.25,
        fps=10.0,
        soft_clip=False,
        spatial_sigma=1.25,
        spatial_filter="gaussian",
        mapping=mapping,
    )
    assert rows == [[float(i)] for i in range(min(2, length))]
    assert render.normalize_bins.call_count == min(2, length)


def test_live_hook_view_and_payload_alias() -> None:
    hooks: FixedHooks = typed_render
    assert hooks is render and render._fixed_hooks() is hooks
    assert render.FieldChunkTask is render_fixed.FieldChunkTask
    assert render._FIELD_POOL_MIN_FRAMES == render_fixed._FIELD_POOL_MIN_FRAMES == 1800


def test_field_payload_contains_only_existing_scalar_fields() -> None:
    assert [f.name for f in fields(render.FieldChunkTask)] == [
        "chunk_index",
        "n_chunks",
        "first_frame",
        "n_frames",
        "columns_path",
        "width",
        "height",
        "fps",
        "color",
        "amplitude",
        "center_line",
        "content_height",
        "glow",
        "png_dir",
        "prores_path",
        "ffmpeg_threads",
        "overscan",
        "supersample",
        "pix_fmt",
        "aa_taps",
        "plan_path",
        "geometry",
        "bar_width",
        "bar_gap",
        "bar_count",
        "bar_fill",
        "bar_align",
        "bar_alternate",
        "bar_color_b",
        "bar_center_line_width",
    ]
