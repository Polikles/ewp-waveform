"""Characterize static dispatch/forwarding without decoding, rendering or encoding."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import subprocess
import sys
from collections.abc import MutableMapping
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType
from typing import cast
from unittest.mock import Mock, call

import pytest
from tests.unit.test_plan import _job

from ewp_waveform.application import render_fixed, render_scroll
from ewp_waveform.application.errors import AppError
from ewp_waveform.application.render_lifecycle import RenderLifecycle
from ewp_waveform.application.render_pipelines import (
    BUILTIN_PIPELINES,
    PipelineHooks,
    PipelineRun,
    RenderPipeline,
    select_pipeline,
)
from ewp_waveform.application.render_types import RenderContext, RenderOptions
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.diagnostics import DiagnosticCode
from ewp_waveform.domain.models import SourceMedia


@pytest.fixture
def state(tmp_path: Path) -> PipelineRun:
    source = tmp_path / "never-opened.wav"
    return PipelineRun(
        context=RenderContext(
            _job(source),
            SourceMedia(
                path=source,
                duration_seconds=10.0,
                sample_rate=8000,
                channels=1,
                codec="pcm_s16le",
                format_name="wav",
                size_bytes=0,
            ),
            load_preset("iuris-default"),
            load_performance("balanced"),
        ),
        appearance=Mock(),
        spectrum_contour=False,
        ribbon_ss=0,
        source_sha="raw-sha",
        sig="raw-signature",
        clip_start=0.0,
        clip_duration=0.125,
        expected_frames=3,
        work=tmp_path / "work",
        producing_mov=True,
        producing_png=True,
        glow=0.0,
        threads=0,
        fail_after_chunk=0,
        note=Mock(),
        lifecycle=cast(RenderLifecycle, Mock()),
        analysis={},
        normalization={},
        warnings=[],
        resume_history=[],
        clock=PhaseTimes(),
    )


def test_builtins_and_adapters_are_immutable() -> None:
    assert isinstance(BUILTIN_PIPELINES, MappingProxyType)
    assert tuple(BUILTIN_PIPELINES) == ("frequency", "time")
    mutable = cast(MutableMapping[str, RenderPipeline], BUILTIN_PIPELINES)
    with pytest.raises(TypeError):
        mutable["new"] = BUILTIN_PIPELINES["time"]
    with pytest.raises(TypeError):
        del mutable["time"]
    for pipeline in BUILTIN_PIPELINES.values():
        assert not hasattr(pipeline, "__dict__")
        for attribute in ("prepare", "run"):
            with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
                setattr(pipeline, attribute, Mock())


@pytest.mark.parametrize("domain", ["time", "", "Frequency", "legacy-invalid", "playhead"])
def test_nonfrequency_selection_retains_internal_else_fallback(domain: str) -> None:
    assert select_pipeline(domain) is BUILTIN_PIPELINES["time"]
    assert select_pipeline("frequency") is BUILTIN_PIPELINES["frequency"]


def test_preparation_forwards_original_options_and_live_hooks(
    state: PipelineRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = Mock()
    options = RenderOptions(
        output_dir=state.work,
        formats=["png", "png"],
        force=False,
        duration=None,
        spectrum_n_bands=None,
        bar_alternate=False,
        bar_count=0,
        ribbon_supersample=0,
    )
    pipeline = select_pipeline("frequency")
    first, second = Mock(return_value=Mock()), Mock(return_value=Mock())
    for resolver in (first, second):
        monkeypatch.setattr(render_fixed, "resolve_fixed_options", resolver)
        result = pipeline.prepare(hooks, state.context.preset, options)
        assert result is resolver.return_value
        resolver.assert_called_once_with(
            hooks._fixed_hooks.return_value, state.context.preset, options
        )
        assert resolver.call_args.args[2] is options
    assert hooks._fixed_hooks.call_count == 2
    hooks.reset_mock()
    assert select_pipeline("time").prepare(hooks, state.context.preset, options) is None
    assert hooks.mock_calls == []


@pytest.mark.parametrize("domain", ["frequency", "time"])
def test_execution_forwards_every_original_argument_by_identity(
    state: PipelineRun, monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    hooks = Mock()
    common = {
        "job": state.context.job,
        "preset": state.context.preset,
        "performance": state.context.performance,
        "source_sha": state.source_sha,
        "clip_start": state.clip_start,
        "clip_duration": state.clip_duration,
        "expected_frames": state.expected_frames,
        "work": state.work,
        "producing_mov": state.producing_mov,
        "producing_png": state.producing_png,
        "glow": state.glow,
        "threads": state.threads,
        "note": state.note,
        "analysis": state.analysis,
        "normalization": state.normalization,
        "clock": state.clock,
    }
    runner = Mock(return_value=(None, None))
    if domain == "frequency":
        monkeypatch.setattr(render_fixed, "run_fixed_pipeline", runner)
        common.update(
            media=state.context.media,
            appearance=state.appearance,
            spectrum_contour=state.spectrum_contour,
            ribbon_ss=state.ribbon_ss,
            lifecycle=state.lifecycle,
        )
        selected_hooks = hooks._fixed_hooks.return_value
    else:
        monkeypatch.setattr(render_scroll, "run_scroll_pipeline", runner)
        common.update(
            sig=state.sig,
            fail_after_chunk=state.fail_after_chunk,
            warnings=state.warnings,
            resume_history=state.resume_history,
        )
        selected_hooks = hooks._scroll_hooks.return_value
    pipeline = select_pipeline(domain)
    pipeline.run(hooks, state)
    runner.assert_called_once_with(selected_hooks, **common)
    for name, value in common.items():
        assert runner.call_args.kwargs[name] is value
    # Replacing a module helper after selection must not leave a captured callback.
    replacement = Mock(return_value=(None, None))
    module = render_fixed if domain == "frequency" else render_scroll
    name = "run_fixed_pipeline" if domain == "frequency" else "run_scroll_pipeline"
    monkeypatch.setattr(module, name, replacement)
    pipeline.run(hooks, state)
    replacement.assert_called_once_with(selected_hooks, **common)
    assert runner.call_count == 1


@pytest.mark.parametrize("mov,png", [(False, False), (True, False), (False, True), (True, True)])
def test_scroll_invocation_and_publication_order(
    state: PipelineRun, monkeypatch: pytest.MonkeyPatch, mov: bool, png: bool
) -> None:
    events = Mock()
    mov_path = state.work / "out.mov" if mov else None
    png_path = state.work / "png" if png else None
    runner = Mock(return_value=(mov_path, png_path))
    monkeypatch.setattr(render_scroll, "run_scroll_pipeline", runner)
    hooks = Mock()
    lifecycle = Mock()
    events.attach_mock(runner, "run")
    events.attach_mock(lifecycle, "publication")
    state = replace(state, lifecycle=cast(RenderLifecycle, lifecycle))
    select_pipeline("time").run(hooks, state)
    expected = [call.run(hooks._scroll_hooks.return_value, **runner.call_args.kwargs)]
    if mov:
        expected.append(
            call.publication.publish_mov(
                mov_path, failure_message="scroll output failed validation"
            )
        )
    if png:
        expected.append(call.publication.publish_png(png_path))
    assert events.mock_calls == expected


@pytest.mark.parametrize("domain", ["frequency", "time"])
def test_adapters_leave_partial_reports_and_original_exception_untouched(
    state: PipelineRun, monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    error = RuntimeError("original failure")

    def fail(*args: object, **kwargs: object) -> None:
        assert kwargs["analysis"] is state.analysis
        state.analysis["partial"] = False
        raise error

    module = render_fixed if domain == "frequency" else render_scroll
    name = "run_fixed_pipeline" if domain == "frequency" else "run_scroll_pipeline"
    monkeypatch.setattr(module, name, fail)
    with pytest.raises(RuntimeError) as caught:
        select_pipeline(domain).run(Mock(), state)
    assert caught.value is error
    assert state.analysis == {"partial": False}
    assert cast(Mock, state.lifecycle).mock_calls == []


def test_missing_fixed_appearance_asserts_before_hook_lookup(state: PipelineRun) -> None:
    hooks = Mock()
    with pytest.raises(AssertionError):
        select_pipeline("frequency").run(hooks, replace(state, appearance=None))
    assert hooks.mock_calls == []


@pytest.mark.parametrize(
    "kind,message",
    [
        ("particles", "Particles are unsupported in the FFmpeg MVP."),
        ("playhead", "Playhead envelope is deferred."),
    ],
)
def test_unsupported_service_paths_reject_before_pipeline_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, message: str
) -> None:
    service = importlib.import_module("ewp_waveform.application.service")
    render = importlib.import_module("ewp_waveform.application.render")
    preset = load_preset("iuris-default")
    if kind == "particles":
        preset = preset.model_copy(update={"effects": {"particles": {"enabled": True}}})
    else:
        preset = preset.model_copy(
            update={"waveform": preset.waveform.model_copy(update={"time_mode": "playhead"})}
        )
    monkeypatch.setattr(service, "dry_run", Mock(return_value=(Mock(), preset, [], [])))
    guard = Mock(side_effect=AssertionError("unsupported request crossed dispatch"))
    monkeypatch.setattr(render, "select_pipeline", guard)
    monkeypatch.setattr(service, "render_job", guard)
    monkeypatch.setattr(service, "probe_media", guard)
    with pytest.raises(AppError) as caught:
        service.render(tmp_path / "never-opened.wav")
    assert str(caught.value) == message
    assert caught.value.diagnostic is not None
    assert caught.value.diagnostic.code == DiagnosticCode.E_RENDERER_CAPABILITY
    guard.assert_not_called()


def test_registry_import_does_not_import_dispatcher_back() -> None:
    module = importlib.import_module("ewp_waveform.application.render_pipelines")
    source_root = Path(inspect.getfile(module)).resolve().parents[2]
    code = (
        "import sys; from ewp_waveform.application import render_pipelines; "
        "assert 'ewp_waveform.application.render' not in sys.modules; "
        "import ewp_waveform.application.render; "
        "assert render_pipelines.select_pipeline('time') is "
        "render_pipelines.BUILTIN_PIPELINES['time']"
    )
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(source_root)}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # A static guard also keeps the live-hook boundary explicit.
    tree = ast.parse(inspect.getsource(module))
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "ewp_waveform.application.render"
        for node in ast.walk(tree)
    )
    assert set(PipelineHooks.__dict__) >= {"_fixed_hooks", "_scroll_hooks"}
