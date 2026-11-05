from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import Mock, call

import pytest

from ewp_waveform.application.render_types import RenderContext, RendererOutcome, RenderOptions
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.models import SourceMedia, VisualizationDomain
from tests.unit.test_plan import _job
from tests.unit.test_render_execution_contracts import _overrides

render_module = importlib.import_module("ewp_waveform.application.render")


@pytest.fixture
def context(tmp_path: Path) -> RenderContext:
    source = tmp_path / "s0e00-Test.wav"
    return RenderContext(
        job=_job(source),
        media=SourceMedia(
            path=source,
            duration_seconds=10.0,
            sample_rate=8000,
            channels=1,
            codec="pcm_s16le",
            format_name="wav",
            size_bytes=0,
        ),
        preset=load_preset("iuris-default"),
        performance=load_performance("balanced"),
    )


def test_real_typed_executor_consumes_raw_values_before_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context: RenderContext
) -> None:
    # Invoke the real executor directly: constructing unused DTOs cannot pass this test.
    context = RenderContext(
        context.job.model_copy(update={"domain": VisualizationDomain.FREQUENCY}),
        context.media,
        context.preset,
        context.performance,
    )
    raw = _overrides(tmp_path)
    raw.update(force=False, start=8.0, duration=5.0, glow_level=None)
    options = RenderOptions(**raw)
    recipe = {"recipe": "sentinel"}
    appearance = Mock()
    appearance.identity.return_value = recipe
    resolver = Mock(return_value=appearance)
    monkeypatch.setattr(render_module, "resolve_fixed_axis_appearance", resolver)
    color = Mock(return_value=context.preset)
    glow = Mock(return_value=context.preset)
    opacity = Mock(return_value=context.preset)
    default_glow = Mock(return_value="geometry-default")
    monkeypatch.setattr(render_module, "_with_waveform_color", color)
    monkeypatch.setattr(render_module, "_with_glow_level", glow)
    monkeypatch.setattr(render_module, "_with_classic_alternate_opacity", opacity)
    monkeypatch.setattr(render_module, "default_glow_level", default_glow)
    hasher = Mock(return_value="a" * 64)
    monkeypatch.setattr(render_module, "sha256_file", hasher)
    mov = tmp_path / "existing.mov"
    png = tmp_path / "existing-png"
    destinations = Mock(return_value=("sig", mov, png))
    monkeypatch.setattr(render_module, "planned_destinations", destinations)
    publisher = Mock(side_effect=lambda path, **kw: (path, True))
    monkeypatch.setattr(render_module, "publish_path", publisher)
    monkeypatch.setattr(render_module, "_validate_mov", Mock(return_value={"passed": True}))
    monkeypatch.setattr(render_module, "_validate_png", Mock(return_value={"passed": True}))
    guard = Mock(side_effect=AssertionError("SKIP crossed the work/clock/media boundary"))
    for name in ("resolve_workdir", "PhaseTimes", "decode_mono_wav", "encode_rgba_stream"):
        monkeypatch.setattr(render_module, name, guard)
    payload: dict[str, Any] = {"job": {"status": "SKIPPED"}}
    result = Mock(return_value=payload)
    monkeypatch.setattr(render_module, "_result_payload", result)
    events = Mock()
    for name, mock in (
        ("color", color), ("default_glow", default_glow), ("glow", glow),
        ("opacity", opacity), ("appearance", resolver), ("hash", hasher),
        ("destinations", destinations),
    ):
        events.attach_mock(mock, name)

    outcome = render_module._render_job(context, options)

    assert type(outcome) is RendererOutcome
    assert outcome.payload is payload
    color.assert_called_once_with(context.preset, "#A1B2C3")
    default_glow.assert_called_once_with("mirrored_bars")
    glow.assert_called_once_with(context.preset, "geometry-default")
    opacity.assert_called_once_with(context.preset, 0.375)
    resolver.assert_called_once_with(
        context.preset,
        spectrum_contour=True,
        spectrum_spatial_scale=2.5,
        spectrum_spatial_filter="gaussian",
        spectrum_n_bands=37,
        spectrum_tilt_db_per_octave=-2.25,
        spectrum_compress=0.625,
        spectrum_recenter=True,
        spectrum_edge_taper=0.375,
        visual_geometry="temporal_rms_peak",
        spectrum_layout="field_center_out",
        spectrum_slot_sigma=1.25,
        ribbon_supersample=7,
        render_path="rgba_2d",
        render_aa="coverage_taps",
        field_geometry="mirrored_bars",
        bar_width=5.5,
        bar_gap=3.25,
        bar_count=19,
        bar_fill=0.75,
        bar_align="right",
        bar_alternate=False,
        bar_color_b="#123456",
        bar_center_line_width=2.5,
    )
    assert [item[0] for item in events.mock_calls if "." not in item[0]] == [
        "color", "default_glow", "glow", "opacity", "appearance", "hash", "destinations"
    ]
    assert destinations.call_args.args == (context.job, context.preset)
    assert destinations.call_args.kwargs == {
        "source_sha256": "a" * 64,
        "output_dir": raw["output_dir"],
        "formats": raw["formats"],
        "clip_start": 8.0,
        "clip_duration": 5.0,  # Requested duration, not the EOF-truncated 2 seconds.
        "fixed_axis_recipe": recipe,
    }
    assert destinations.call_args.kwargs["formats"] is raw["formats"]
    publisher.assert_has_calls([call(mov, force=False), call(png, force=False)])
    assert result.call_args.args[:4] == (
        context.job, context.media, context.preset, context.performance
    )
    report = result.call_args.kwargs
    assert report["status"] == "SKIPPED"
    assert report["fixed_axis_recipe"] is recipe
    assert report["outputs"] == [
        {"path": str(mov), "format": "prores4444"},
        {"path": str(png), "format": "png"},
    ]
    assert report["phase_report"] == {
        "extras": {
            "clip_start_seconds": 8.0,
            "effective_audio_seconds": 2.0,
            "expected_frames": 120,
            "reused_output_formats": ["prores4444", "png"],
        }
    }
    assert raw["phases"].snapshot()["counts"] == {}
    assert raw["phases"].extras == {}
    raw["progress"].assert_has_calls([
        call(f"hashing {context.job.path}"), call("skip: equivalent output already present")
    ])
    assert raw["progress"].call_count == 2
    guard.assert_not_called()


@pytest.mark.parametrize("status", ["FAILED", "SUCCEEDED"])
@pytest.mark.parametrize("keep_temp,policy_keep", [(False, False), (False, True), (True, False)])
@pytest.mark.parametrize("supply_clock", [False, True])
def test_real_typed_terminal_outcomes_keep_payload_clock_and_work_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: RenderContext,
    status: str,
    keep_temp: bool,
    policy_keep: bool,
    supply_clock: bool,
) -> None:
    # Lower execution boundaries are stubbed: this is not a media-equivalence oracle.
    context.performance.workdirs.update(keep_on_failure=policy_keep, keep_on_success=policy_keep)
    work = tmp_path / "work"
    work.mkdir()
    clock = PhaseTimes()
    clock.extras["existing"] = "untouched"
    clock.add("preexisting", 1.25)
    progress = Mock()
    options = RenderOptions(
        output_dir=tmp_path / "out", formats=["png"], force=True,
        start=10.0 if status == "FAILED" else 2.0, duration=4.0,
        keep_temp=keep_temp, fail_after_chunk=0,
        phases=clock if supply_clock else None, progress=progress,
    )
    monkeypatch.setattr(render_module, "sha256_file", Mock(return_value="a" * 64))
    destination = tmp_path / "out" / "frames"
    monkeypatch.setattr(
        render_module, "planned_destinations", Mock(return_value=("sig", None, destination))
    )
    publisher = Mock(return_value=(destination, False))
    monkeypatch.setattr(render_module, "publish_path", publisher)
    work_resolver = Mock(return_value=work)
    monkeypatch.setattr(render_module, "resolve_workdir", work_resolver)
    clock_factory = Mock(
        side_effect=AssertionError("replaced caller clock") if supply_clock else None,
        return_value=clock,
    )
    monkeypatch.setattr(render_module, "PhaseTimes", clock_factory)
    monkeypatch.setattr(render_module, "load_checkpoint", Mock(return_value=None))
    monkeypatch.setattr(render_module, "reset_workdir", Mock())
    monkeypatch.setattr(render_module, "plan_chunks", Mock(return_value=[]))
    encodes = Mock(return_value=([], 1))
    monkeypatch.setattr(render_module, "_run_scroll_encodes", encodes)
    monkeypatch.setattr(render_module, "_validate_png", Mock(return_value={"passed": True}))
    move = Mock()
    monkeypatch.setattr(render_module.shutil, "move", move)
    media_guard = Mock(side_effect=AssertionError("unit boundary attempted media execution"))
    for name in ("decode_mono_wav", "encode_rgba_stream", "_prepare_chunk_envelopes"):
        monkeypatch.setattr(render_module, name, media_guard)
    payload: dict[str, Any] = {"job": {"status": status}, "unmodified": object()}
    result = Mock(return_value=payload)
    monkeypatch.setattr(render_module, "_result_payload", result)

    outcome = render_module._render_job(context, options)

    assert type(outcome) is RendererOutcome
    assert outcome.payload is payload
    work_resolver.assert_called_once()
    assert work_resolver.call_args.args[0] is context.performance
    publisher.assert_called_once_with(destination, force=True)
    report = result.call_args.kwargs
    assert report["status"] == status
    assert report["validation"]["passed"] is (status == "SUCCEEDED")
    assert report["phase_report"] == clock.snapshot()
    if supply_clock:
        clock_factory.assert_not_called()
    else:
        clock_factory.assert_called_once_with()
    assert clock.extras["existing"] == "untouched"
    assert clock.seconds["preexisting"] == 1.25
    assert clock.extras["clip_start_seconds"] == options.start
    assert clock.extras["effective_audio_seconds"] == (0.0 if status == "FAILED" else 4.0)
    assert work.exists() is (keep_temp or policy_keep)
    assert report["workdir"] == (str(work) if keep_temp or policy_keep else None)
    assert result.call_args.args[:4] == (
        context.job, context.media, context.preset, context.performance
    )
    if status == "SUCCEEDED":
        encodes.assert_called_once()
        assert encodes.call_args.kwargs["fail_after_chunk"] == 0
        assert type(encodes.call_args.kwargs["fail_after_chunk"]) is int
        assert encodes.call_args.kwargs["clip_duration"] == 4.0
        assert encodes.call_args.kwargs["preset"] is context.preset
        move.assert_called_once_with(str(work / "png"), str(destination))
    else:
        encodes.assert_not_called()
        move.assert_not_called()
        assert report["warnings"][0].message == "source duration is zero"
    media_guard.assert_not_called()


@pytest.mark.parametrize("when", ["hash", "progress"])
def test_real_typed_executor_preserves_pre_try_exception_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context: RenderContext, when: str
) -> None:
    error = RuntimeError("outside the original catch region")
    hasher = Mock(side_effect=error if when == "hash" else None, return_value="a" * 64)
    progress = Mock(side_effect=error if when == "progress" else None)
    monkeypatch.setattr(render_module, "sha256_file", hasher)
    work_guard = Mock(side_effect=AssertionError("escaped error reached workdir"))
    monkeypatch.setattr(render_module, "resolve_workdir", work_guard)
    options = RenderOptions(
        output_dir=tmp_path / "out", formats=["png"], force=False, progress=progress
    )
    with pytest.raises(RuntimeError) as caught:
        render_module._render_job(context, options)
    assert caught.value is error
    work_guard.assert_not_called()
    if when == "progress":
        hasher.assert_not_called()
    assert not options.output_dir.exists()


@pytest.mark.parametrize(
    "start,duration,effective_start,effective_duration,identity_duration,frames",
    [
        (None, None, 0.0, 10.0, None, 600),
        (0.0, 0.0, 0.0, 10.0, None, 600),
        (-2.0, -3.0, 0.0, 10.0, None, 600),
        (2.0, None, 2.0, 8.0, None, 480),
        (2.0, 0.0, 2.0, 8.0, None, 480),
        (2.0, -1.0, 2.0, 8.0, None, 480),
        (2.0, 3.0, 2.0, 3.0, 3.0, 180),
        (8.0, 5.0, 8.0, 2.0, 5.0, 120),
        (10.0, 1.0, 10.0, 0.0, 1.0, 1),
        (11.0, None, 11.0, 0.0, None, 1),
    ],
)
def test_typed_clip_values_keep_legacy_effective_and_requested_identity_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: RenderContext,
    start: float | None,
    duration: float | None,
    effective_start: float,
    effective_duration: float,
    identity_duration: float | None,
    frames: int,
) -> None:
    # Stub only output reuse to inspect transport through the real clip/identity code.
    png = tmp_path / "reused-png"
    destinations = Mock(return_value=("sig", None, png))
    monkeypatch.setattr(render_module, "planned_destinations", destinations)
    monkeypatch.setattr(render_module, "publish_path", Mock(return_value=(png, True)))
    monkeypatch.setattr(render_module, "_validate_png", Mock(return_value={"passed": True}))
    monkeypatch.setattr(render_module, "sha256_file", Mock(return_value="a" * 64))
    result = Mock(return_value={})
    monkeypatch.setattr(render_module, "_result_payload", result)
    work_guard = Mock(side_effect=AssertionError("reuse unexpectedly started execution"))
    monkeypatch.setattr(render_module, "resolve_workdir", work_guard)
    options = RenderOptions(
        output_dir=tmp_path / "out", formats=["png"], force=False,
        start=start, duration=duration, progress=None,
    )

    outcome = render_module._render_job(context, options)

    assert outcome.payload is result.return_value
    assert destinations.call_args.kwargs["clip_start"] == effective_start
    assert destinations.call_args.kwargs["clip_duration"] == identity_duration
    extras = result.call_args.kwargs["phase_report"]["extras"]
    assert extras["clip_start_seconds"] == effective_start
    assert extras["effective_audio_seconds"] == effective_duration
    assert extras["expected_frames"] == frames
    assert options.start is start
    assert options.duration is duration
    work_guard.assert_not_called()
