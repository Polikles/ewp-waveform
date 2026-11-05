from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from ewp_waveform.application import benchmark, service
from ewp_waveform.application.benchmark import BenchmarkCell
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.config.models import ApplicationConfig, BenchmarkManifest, BenchmarkSection
from ewp_waveform.domain.diagnostics import CapabilityLevel, Diagnostic, DiagnosticCode, Severity
from ewp_waveform.domain.models import SourceMedia
from tests.unit.test_render_execution_contracts import OPTION_NAMES, _overrides

render_module = importlib.import_module("ewp_waveform.application.render")


@pytest.mark.parametrize("formats", [None, [], ["png", "prores4444", "png"]])
@pytest.mark.parametrize("explicit_selection", [False, True])
@pytest.mark.parametrize("configured_recursive", [False, True])
@pytest.mark.parametrize("requested_recursive", [False, True])
def test_service_forwards_all_34_shared_options_and_retains_result_mutation_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    formats: list[str] | None,
    explicit_selection: bool,
    configured_recursive: bool,
    requested_recursive: bool,
) -> None:
    source = tmp_path / "s0e00-Test.wav"
    # output_root distinguishes files from directory inputs without probing media.
    source.write_bytes(b"unit boundary stub; not decoded")
    config_path = tmp_path / "selected.toml"
    config = ApplicationConfig.model_validate({
        "defaults": {"preset": "configured-preset", "performance": "configured-performance"},
        "input": {"recursive": configured_recursive, "follow_symlinks": True},
        "output": {"directory_name": "configured-output", "formats": ["png"]},
    })
    config_loader = Mock(return_value=config)
    monkeypatch.setattr(service, "load_application_config", config_loader)
    preset = load_preset("iuris-default")
    performance = load_performance("balanced")
    preset_loader = Mock(return_value=preset)
    performance_loader = Mock(return_value=performance)
    monkeypatch.setattr(service, "load_preset", preset_loader)
    monkeypatch.setattr(service, "load_performance", performance_loader)
    discovery = Mock(return_value=[source])
    monkeypatch.setattr(service, "discover_paths", discovery)
    media = SourceMedia(
        path=source, duration_seconds=10, sample_rate=8000, channels=1,
        codec="pcm_s16le", format_name="wav", size_bytes=0,
    )
    monkeypatch.setattr(service, "probe_media", Mock(return_value=media))
    monkeypatch.setattr(
        service, "capability_for_preset", Mock(return_value=(CapabilityLevel.LIMITED, ""))
    )
    warning = Diagnostic(
        code=DiagnosticCode.W_OUTPUT_SPACE, severity=Severity.WARNING, message="test warning"
    )
    space_warning = Mock(return_value=warning)
    monkeypatch.setattr(service, "_output_space_warning", space_warning)
    payload: dict[str, Any] = {
        "job": {"status": "SUCCEEDED"}, "warnings": [{"existing": "preserved"}]
    }
    legacy_entry = Mock(return_value=payload)
    monkeypatch.setattr(service, "render_job", legacy_entry)
    typed_guard = Mock(side_effect=AssertionError("service bypassed its render_job seam"))
    monkeypatch.setattr(render_module, "_render_job", typed_guard)
    summary_path: Path | None = None

    def summarize(items: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        assert len(items) == 1
        assert items[0] is payload
        assert "result_json" in items[0]
        assert "run_json" not in items[0]
        return {"run_id": "contract"}

    summary_builder = Mock(side_effect=summarize)
    monkeypatch.setattr(service, "build_run_summary", summary_builder)

    def write_summary(summary: dict[str, Any], path: Path) -> Path:
        nonlocal summary_path
        assert summary == {"run_id": "contract"}
        summary_path = path
        return path

    summary_writer = Mock(side_effect=write_summary)
    monkeypatch.setattr(service, "write_run_summary", summary_writer)
    request = _overrides(tmp_path)
    del request["phases"]
    request["formats"] = formats
    request["output_dir"] = tmp_path / "explicit-output" if explicit_selection else None
    selectors: dict[str, Any] = {
        "recursive": requested_recursive,
        "config_path": config_path,
        "preset_name": "explicit-preset" if explicit_selection else None,
        "performance_name": "explicit-performance" if explicit_selection else None,
        "fps_override": 24.0 if explicit_selection else None,
    }

    returned = service.render(source, **request, **selectors)

    assert returned == [payload]
    assert returned[0] is payload
    config_loader.assert_called_once_with(config_path)
    discovery.assert_called_once_with(
        source, recursive=requested_recursive or configured_recursive, follow_symlinks=True
    )
    preset_loader.assert_called_once_with(
        "explicit-preset" if explicit_selection else "configured-preset"
    )
    assert performance_loader.call_count == 2  # dry_run resolution, then existing render lookup.
    expected_performance = (
        "explicit-performance" if explicit_selection else "configured-performance"
    )
    assert all(
        item.args == (expected_performance,) for item in performance_loader.call_args_list
    )
    legacy_entry.assert_called_once()
    args = legacy_entry.call_args.args
    assert len(args) == 4
    job, got_media, got_preset, got_performance = args
    assert got_media is media
    assert got_preset is preset
    assert got_performance is performance
    assert job.fps == (24.0 if explicit_selection else preset.canvas.fps)
    assert job.path == source
    forwarded = legacy_entry.call_args.kwargs
    assert len(forwarded) == 34
    assert set(forwarded) == set(OPTION_NAMES) - {"phases"}
    root = tmp_path / ("explicit-output" if explicit_selection else "configured-output")
    selected_formats = formats if formats else config.output.formats
    expected = dict(request)
    expected.update(output_dir=root, formats=selected_formats)
    assert forwarded == expected
    for name in set(expected) - {"output_dir", "formats"}:
        assert forwarded[name] is expected[name], name
    assert forwarded["formats"] is selected_formats
    space_warning.assert_called_once_with(root, preset, selected_formats, 4.875)
    request["progress"].assert_called_once_with("W_OUTPUT_SPACE: test warning")
    assert payload["warnings"] == [{"existing": "preserved"}, warning.model_dump(mode="json")]
    result_path = root / job.project_id / f"{source.stem}_{preset.name}_results.json"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved == {"job": {"status": "SUCCEEDED"}, "warnings": payload["warnings"]}
    assert "result_json" not in saved
    assert "run_json" not in saved
    assert payload["result_json"] == str(result_path)
    assert summary_path == root / "run_contract_results.json"
    assert payload["run_json"] == str(summary_path)
    summary_builder.assert_called_once()
    summary_writer.assert_called_once()
    typed_guard.assert_not_called()


def test_benchmark_still_calls_its_imported_legacy_patch_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preset = load_preset("iuris-default")
    cell = BenchmarkCell(
        tmp_path / "s0e00-Test.wav", "v", "ffmpeg", "balanced", ["png"], preset,
        "PROCESS", output_dir=tmp_path / "cell" / "output", duration_seconds=10,
        start=2.0, duration=3.0,
    )
    manifest = BenchmarkManifest(
        schema_version=1, name="contract", inputs=[], variants=[],
        benchmark=BenchmarkSection(renderers=["ffmpeg"], formats=["png"]),
    )
    monkeypatch.setattr(benchmark, "load_and_expand", Mock(return_value=(manifest, [cell])))
    media = Mock()
    monkeypatch.setattr(benchmark, "probe_media", Mock(return_value=media))
    error = ValueError("legacy patch seam reached")
    legacy_entry = Mock(side_effect=error)
    monkeypatch.setattr(benchmark, "render_job", legacy_entry)
    typed_guard = Mock(side_effect=AssertionError("benchmark bypassed legacy seam"))
    monkeypatch.setattr(render_module, "_render_job", typed_guard)
    with pytest.raises(ValueError) as caught:
        benchmark.run_benchmark(tmp_path / "manifest.toml", output_dir=tmp_path / "out")
    assert caught.value is error
    legacy_entry.assert_called_once()
    assert legacy_entry.call_args.args[1] is media
    assert legacy_entry.call_args.args[2] is preset
    assert legacy_entry.call_args.kwargs == {
        "output_dir": cell.output_dir, "formats": cell.formats, "force": False,
        "start": 2.0, "duration": 3.0,
    }
    typed_guard.assert_not_called()
