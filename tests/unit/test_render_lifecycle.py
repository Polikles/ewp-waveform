"""Freeze lifecycle ordering/failure windows, not stronger publication guarantees."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call

import pytest

from ewp_waveform.application.render_lifecycle import LifecycleHooks
from ewp_waveform.application.render_types import RenderContext, RendererOutcome, RenderOptions
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.models import SourceMedia, VisualizationDomain
from ewp_waveform.ffmpeg.encode import EncodeError
from ewp_waveform.ffmpeg.probe import ProbeError
from tests.unit.test_plan import _job

render_module = importlib.import_module("ewp_waveform.application.render")


@pytest.fixture(params=[False, True], ids=["scroll", "fixed"])
def harness(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    source = tmp_path / "source.wav"  # Never opened: media/encoding are stubbed.
    job = _job(source)
    if request.param:
        job = job.model_copy(update={"domain": VisualizationDomain.FREQUENCY})
    context = RenderContext(
        job,
        SourceMedia(
            path=source,
            duration_seconds=1.0,
            sample_rate=8000,
            channels=1,
            codec="pcm_s16le",
            format_name="wav",
            size_bytes=0,
        ),
        load_preset("iuris-spectrum" if request.param else "iuris-default"),
        load_performance("balanced"),
    )
    context.performance.workdirs.update(keep_on_failure=True, keep_on_success=False)
    work = tmp_path / "work"
    work.mkdir()
    (work / "marker").write_text("recoverable", encoding="utf-8")
    mov, png = tmp_path / "out.mov", tmp_path / "png"
    options = RenderOptions(output_dir=tmp_path / "out", formats=["prores4444", "png"], force=False)
    hasher = Mock(return_value="a" * 64)
    monkeypatch.setattr(render_module, "sha256_file", hasher)
    monkeypatch.setattr(render_module, "planned_destinations", Mock(return_value=("sig", mov, png)))
    publisher = Mock(side_effect=lambda path, **kw: (path, False))
    monkeypatch.setattr(render_module, "publish_path", publisher)
    monkeypatch.setattr(render_module, "resolve_workdir", Mock(return_value=work))
    for name in ("reset_workdir", "decode_mono_wav", "encode_rgba_stream", "concat_videos"):
        monkeypatch.setattr(render_module, name, Mock())
    monkeypatch.setattr(render_module, "load_mono_pcm", Mock(return_value=([], 8000)))
    monkeypatch.setattr(
        render_module,
        "resolve_frequency_span_from_pcm",
        Mock(return_value=SimpleNamespace(fmin_hz=20.0, fmax_hz=2000.0, source="auto")),
    )
    monkeypatch.setattr(render_module, "spectrum_peak", Mock(return_value=1.0))
    monkeypatch.setattr(render_module, "iter_spectrum_frames", Mock(return_value=iter(())))
    monkeypatch.setattr(render_module, "load_checkpoint", Mock(return_value=None))
    monkeypatch.setattr(render_module, "plan_chunks", Mock(return_value=[]))
    monkeypatch.setattr(render_module, "_run_scroll_encodes", Mock(return_value=([], 1)))
    mov_report = {"passed": True, "codec": "prores"}
    png_report = {"passed": True, "frames": 60, "format": "png"}
    mov_validator, png_validator = Mock(return_value=mov_report), Mock(return_value=png_report)
    monkeypatch.setattr(render_module, "_validate_mov", mov_validator)
    monkeypatch.setattr(render_module, "_validate_png", png_validator)
    move = Mock()
    monkeypatch.setattr(render_module.shutil, "move", move)
    return SimpleNamespace(
        context=context,
        options=options,
        work=work,
        mov=mov,
        png=png,
        hasher=hasher,
        publisher=publisher,
        mov_validator=mov_validator,
        png_validator=png_validator,
        mov_report=mov_report,
        png_report=png_report,
        move=move,
    )


def _run(harness: SimpleNamespace) -> dict[str, Any]:
    outcome: RendererOutcome = render_module._render_job(harness.context, harness.options)
    return outcome.payload


def test_mov_is_published_before_png_validation_failure(harness: SimpleNamespace) -> None:
    harness.png_validator.return_value = {"passed": False, "frames": 1, "format": "png"}
    events = Mock()
    events.attach_mock(harness.mov_validator, "mov")
    events.attach_mock(harness.png_validator, "png")
    events.attach_mock(harness.move, "move")
    result = _run(harness)
    assert [event[0] for event in events.mock_calls] == ["mov", "move", "png"]
    assert result["job"]["status"] == "FAILED"
    assert result["outputs"] == [{"path": str(harness.mov), "format": "prores4444"}]
    assert result["validation"] == {"passed": False, "codec": "prores"}
    assert result["warnings"][0]["code"] == "E_OUTPUT_VALIDATION"
    assert result["warnings"][0]["message"] == "png sequence failed validation"
    assert result["execution"]["workdir"] == str(harness.work)
    assert harness.work.exists()


@pytest.mark.parametrize("failure", ["mov-invalid", "move-error", "png-probe-error"])
def test_failure_retains_existing_partial_publication_semantics(
    harness: SimpleNamespace, failure: str
) -> None:
    if failure == "mov-invalid":
        harness.mov_validator.return_value = {"passed": False}
    elif failure == "move-error":
        harness.move.side_effect = OSError("move stopped")
    else:
        harness.png_validator.side_effect = ProbeError("png probe stopped")
    result = _run(harness)
    assert result["job"]["status"] == "FAILED"
    assert result["validation"]["passed"] is False
    assert result["outputs"] == (
        [{"path": str(harness.mov), "format": "prores4444"}] if failure == "png-probe-error" else []
    )
    if failure != "png-probe-error":
        harness.png_validator.assert_not_called()
    assert harness.work.exists()


@pytest.mark.parametrize("reused", ["prores4444", "png"])
def test_partial_reuse_keeps_output_order_and_produced_validation(
    harness: SimpleNamespace, reused: str
) -> None:
    harness.publisher.side_effect = lambda path, **kw: (
        path,
        path == (harness.mov if reused == "prores4444" else harness.png),
    )
    result = _run(harness)
    assert result["job"]["status"] == "SUCCEEDED"
    assert [item["format"] for item in result["outputs"]] == (
        ["prores4444", "png"] if reused == "prores4444" else ["png", "prores4444"]
    )
    assert result["validation"] == (
        harness.png_report if reused == "prores4444" else harness.mov_report
    )
    assert result["performance"]["extras"]["reused_output_formats"] == [reused]
    assert not harness.work.exists()
    assert harness.hasher.call_args_list == [call(harness.context.job.path)] * 2


def test_all_reused_outputs_do_not_resolve_work_or_rehash(
    harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.publisher.side_effect = lambda path, **kw: (path, True)
    work_guard = Mock(side_effect=AssertionError("SKIP allocated work"))
    monkeypatch.setattr(render_module, "resolve_workdir", work_guard)
    result = _run(harness)
    assert result["job"]["status"] == "SKIPPED"
    assert result["validation"] is harness.mov_report
    assert [item["format"] for item in result["outputs"]] == ["prores4444", "png"]
    harness.hasher.assert_called_once_with(harness.context.job.path)
    harness.move.assert_not_called()
    work_guard.assert_not_called()


def test_changed_source_preserves_two_diagnostics_and_original_hash(
    harness: SimpleNamespace,
) -> None:
    harness.hasher.side_effect = ["a" * 64, "b" * 64]
    result = _run(harness)
    assert result["job"]["status"] == "FAILED"
    assert result["inputs"][0]["sha256"] == "a" * 64
    assert [item["code"] for item in result["warnings"]] == [
        "E_OUTPUT_VALIDATION",
        "E_RENDERER_CAPABILITY",
    ]
    assert [item["message"] for item in result["warnings"]] == [
        "Source hash changed during render; sources must be immutable.",
        "source mutated",
    ]
    harness.mov_validator.assert_not_called()
    harness.png_validator.assert_not_called()
    harness.move.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("pre-work"), OSError("pre-work")])
def test_destination_errors_stay_outside_render_failure_catch(
    harness: SimpleNamespace, error: Exception
) -> None:
    harness.publisher.side_effect = error
    with pytest.raises(type(error)) as caught:
        _run(harness)
    assert caught.value is error
    harness.hasher.assert_called_once()
    assert harness.work.exists()


@pytest.mark.parametrize("error", [ValueError("unhandled"), KeyboardInterrupt()])
def test_unhandled_errors_do_not_start_failure_cleanup(
    harness: SimpleNamespace, error: BaseException
) -> None:
    harness.mov_validator.side_effect = error
    with pytest.raises(type(error)) as caught:
        _run(harness)
    assert caught.value is error
    assert harness.work.exists()


def test_success_cleanup_reports_none_even_if_ignored_removal_leaves_work(
    harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    remove = Mock()
    monkeypatch.setattr(render_module.shutil, "rmtree", remove)
    result = _run(harness)
    remove.assert_called_once_with(harness.work, ignore_errors=True)
    assert result["job"]["status"] == "SUCCEEDED"
    assert result["execution"]["workdir"] is None
    assert harness.work.exists()


def test_failed_cleanup_checks_actual_remaining_workdir(
    harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.context.performance.workdirs["keep_on_failure"] = False
    harness.mov_validator.side_effect = EncodeError("validation stopped")
    remove = Mock()
    monkeypatch.setattr(render_module.shutil, "rmtree", remove)
    result = _run(harness)
    remove.assert_called_once_with(harness.work, ignore_errors=True)
    assert result["job"]["status"] == "FAILED"
    assert result["execution"]["workdir"] == str(harness.work)


def test_result_helper_is_looked_up_after_skip_progress_callback(
    harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.publisher.side_effect = lambda path, **kw: (path, True)
    payload: dict[str, Any] = {"late": object()}
    builder = Mock(return_value=payload)

    def progress(message: str) -> None:
        if message == "skip: equivalent output already present":
            monkeypatch.setattr(render_module, "_result_payload", builder)

    harness.options = RenderOptions(
        output_dir=harness.options.output_dir,
        formats=harness.options.formats,
        force=False,
        progress=progress,
    )
    assert _run(harness) is payload
    builder.assert_called_once()


@pytest.mark.parametrize("probe", ["mov", "png"])
def test_reuse_probe_exceptions_keep_original_asymmetric_catch(
    harness: SimpleNamespace, probe: str
) -> None:
    harness.publisher.side_effect = lambda path, **kw: (path, True)
    error = OSError("reuse probe stopped")
    if probe == "png":
        harness.png_validator.side_effect = error
        with pytest.raises(OSError) as caught:
            _run(harness)
        assert caught.value is error
        harness.hasher.assert_called_once()
    else:
        harness.mov_validator.side_effect = [error, harness.mov_report]
        result = _run(harness)
        assert result["job"]["status"] == "SUCCEEDED"
        assert [item["format"] for item in result["outputs"]] == ["png", "prores4444"]
        assert harness.mov_validator.call_count == 2


def test_compatibility_publish_forward_uses_live_completion_and_version_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest, version = tmp_path / "out.mov", tmp_path / "out_v009.mov"
    complete = Mock(return_value=False)
    next_path = Mock(return_value=version)
    monkeypatch.setattr(render_module, "output_is_complete", complete)
    monkeypatch.setattr(render_module, "next_version_path", next_path)
    assert render_module.publish_path(dest, force=True) == (dest, False)
    next_path.assert_not_called()
    complete.return_value = True
    assert render_module.publish_path(dest, force=True) == (version, False)
    next_path.assert_called_once_with(dest)


def test_compatibility_mov_validator_forward_uses_live_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stub.mov"
    path.write_bytes(b"stub; probe is mocked")
    info = SimpleNamespace(
        codec_name="prores",
        profile="4444",
        pix_fmt="yuva444p10le",
        width=80,
        height=32,
        nb_frames=3,
        avg_frame_rate="10/1",
        duration_seconds=0.3,
    )
    probe = Mock(return_value=info)
    monkeypatch.setattr(render_module, "probe_video", probe)
    report = render_module._validate_mov(path, width=80, height=32, expected_frames=3, fps=10)
    assert report == {
        "passed": True,
        "codec": "prores",
        "pix_fmt": "yuva444p10le",
        "width": 80,
        "height": 32,
        "frames": 3,
        "duration_seconds": 0.3,
    }
    probe.assert_called_once_with(path, first_frame=True)


def test_live_module_satisfies_typed_lifecycle_hooks() -> None:
    # This assignment is checked by mypy, not hidden by the runtime module cast.
    from ewp_waveform.application import render

    hooks: LifecycleHooks = render
    assert render_module._lifecycle_hooks() is hooks
