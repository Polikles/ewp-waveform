from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from ewp_waveform.application import benchmark, service
from ewp_waveform.application.render_types import RenderContext, RendererOutcome, RenderOptions
from ewp_waveform.application.timing import PhaseTimes

render_module = importlib.import_module("ewp_waveform.application.render")
REQUIRED = inspect.Parameter.empty
# Literal interface freeze from P3857b6c; do not derive this from the candidate API.
RENDER_PARAMETERS: list[tuple[str, str, str, Any]] = [
    ("job", "POSITIONAL_OR_KEYWORD", "PlannedJob", REQUIRED),
    ("media", "POSITIONAL_OR_KEYWORD", "SourceMedia", REQUIRED),
    ("preset", "POSITIONAL_OR_KEYWORD", "VisualPreset", REQUIRED),
    ("performance", "POSITIONAL_OR_KEYWORD", "PerformanceProfile", REQUIRED),
    ("output_dir", "KEYWORD_ONLY", "Path", REQUIRED),
    ("formats", "KEYWORD_ONLY", "list[str]", REQUIRED),
    ("force", "KEYWORD_ONLY", "bool", REQUIRED),
    ("start", "KEYWORD_ONLY", "float | None", None),
    ("duration", "KEYWORD_ONLY", "float | None", None),
    ("keep_temp", "KEYWORD_ONLY", "bool", False),
    ("fail_after_chunk", "KEYWORD_ONLY", "int | None", None),
    ("progress", "KEYWORD_ONLY", "Callable[[str], None] | None", None),
    ("spectrum_contour", "KEYWORD_ONLY", "bool", False),
    ("spectrum_spatial_scale", "KEYWORD_ONLY", "float", 1.0),
    ("spectrum_spatial_filter", "KEYWORD_ONLY", "str", "box"),
    ("spectrum_n_bands", "KEYWORD_ONLY", "int | None", None),
    ("spectrum_tilt_db_per_octave", "KEYWORD_ONLY", "float", 0.0),
    ("spectrum_compress", "KEYWORD_ONLY", "float", 1.0),
    ("spectrum_recenter", "KEYWORD_ONLY", "bool", False),
    ("spectrum_edge_taper", "KEYWORD_ONLY", "float", 0.0),
    ("visual_geometry", "KEYWORD_ONLY", "str", "spectrum"),
    ("spectrum_layout", "KEYWORD_ONLY", "str", "linear"),
    ("spectrum_slot_sigma", "KEYWORD_ONLY", "float", 0.0),
    ("ribbon_supersample", "KEYWORD_ONLY", "int | None", None),
    ("render_path", "KEYWORD_ONLY", "str | None", None),
    ("render_aa", "KEYWORD_ONLY", "str | None", None),
    ("field_geometry", "KEYWORD_ONLY", "str", "ribbon"),
    ("bar_width", "KEYWORD_ONLY", "float | None", None),
    ("bar_gap", "KEYWORD_ONLY", "float | None", None),
    ("bar_count", "KEYWORD_ONLY", "int | None", None),
    ("bar_fill", "KEYWORD_ONLY", "float | None", None),
    ("bar_align", "KEYWORD_ONLY", "str | None", None),
    ("bar_alternate", "KEYWORD_ONLY", "bool | None", None),
    ("bar_color_b", "KEYWORD_ONLY", "str | None", None),
    ("bar_center_line_width", "KEYWORD_ONLY", "float | None", None),
    ("waveform_color", "KEYWORD_ONLY", "str | None", None),
    ("glow_level", "KEYWORD_ONLY", "str | None", None),
    ("classic_alternate_opacity", "KEYWORD_ONLY", "float | None", None),
    ("phases", "KEYWORD_ONLY", "PhaseTimes | None", None),
]
SERVICE_PARAMETERS: list[tuple[str, str, str, Any]] = [
    ("input_path", "POSITIONAL_OR_KEYWORD", "Path", REQUIRED),
    ("recursive", "KEYWORD_ONLY", "bool", False),
    ("config_path", "KEYWORD_ONLY", "Path | None", None),
    ("preset_name", "KEYWORD_ONLY", "str | None", None),
    ("performance_name", "KEYWORD_ONLY", "str | None", None),
    ("fps_override", "KEYWORD_ONLY", "float | None", None),
    ("output_dir", "KEYWORD_ONLY", "Path | None", None),
    ("formats", "KEYWORD_ONLY", "list[str] | None", None),
    ("force", "KEYWORD_ONLY", "bool", False),
    ("start", "KEYWORD_ONLY", "float | None", None),
    ("duration", "KEYWORD_ONLY", "float | None", None),
    ("keep_temp", "KEYWORD_ONLY", "bool", False),
    ("fail_after_chunk", "KEYWORD_ONLY", "int | None", None),
    ("progress", "KEYWORD_ONLY", "Callable[[str], None] | None", None),
    ("spectrum_contour", "KEYWORD_ONLY", "bool", False),
    ("spectrum_spatial_scale", "KEYWORD_ONLY", "float", 1.0),
    ("spectrum_spatial_filter", "KEYWORD_ONLY", "str", "box"),
    ("spectrum_n_bands", "KEYWORD_ONLY", "int | None", None),
    ("spectrum_tilt_db_per_octave", "KEYWORD_ONLY", "float", 0.0),
    ("spectrum_compress", "KEYWORD_ONLY", "float", 1.0),
    ("spectrum_recenter", "KEYWORD_ONLY", "bool", False),
    ("spectrum_edge_taper", "KEYWORD_ONLY", "float", 0.0),
    ("visual_geometry", "KEYWORD_ONLY", "str", "spectrum"),
    ("spectrum_layout", "KEYWORD_ONLY", "str", "linear"),
    ("spectrum_slot_sigma", "KEYWORD_ONLY", "float", 0.0),
    ("ribbon_supersample", "KEYWORD_ONLY", "int | None", None),
    ("render_path", "KEYWORD_ONLY", "str | None", None),
    ("render_aa", "KEYWORD_ONLY", "str | None", None),
    ("field_geometry", "KEYWORD_ONLY", "str", "ribbon"),
    ("bar_width", "KEYWORD_ONLY", "float | None", None),
    ("bar_gap", "KEYWORD_ONLY", "float | None", None),
    ("bar_count", "KEYWORD_ONLY", "int | None", None),
    ("bar_fill", "KEYWORD_ONLY", "float | None", None),
    ("bar_align", "KEYWORD_ONLY", "str | None", None),
    ("bar_alternate", "KEYWORD_ONLY", "bool | None", None),
    ("bar_color_b", "KEYWORD_ONLY", "str | None", None),
    ("bar_center_line_width", "KEYWORD_ONLY", "float | None", None),
    ("waveform_color", "KEYWORD_ONLY", "str | None", None),
    ("glow_level", "KEYWORD_ONLY", "str | None", None),
    ("classic_alternate_opacity", "KEYWORD_ONLY", "float | None", None),
]
OPTION_NAMES = [row[0] for row in RENDER_PARAMETERS[4:]]


def _overrides(tmp_path: Path) -> dict[str, Any]:
    """Independent explicit values; not generated from production fields or defaults."""
    return {
        "output_dir": tmp_path / "explicit-output",
        "formats": ["png", "prores4444", "png"],
        "force": True,
        "start": 2.125,
        "duration": 4.875,
        "keep_temp": True,
        "fail_after_chunk": 0,
        "progress": Mock(),
        "spectrum_contour": True,
        "spectrum_spatial_scale": 2.5,
        "spectrum_spatial_filter": "gaussian",
        "spectrum_n_bands": 37,
        "spectrum_tilt_db_per_octave": -2.25,
        "spectrum_compress": 0.625,
        "spectrum_recenter": True,
        "spectrum_edge_taper": 0.375,
        "visual_geometry": "temporal_rms_peak",
        "spectrum_layout": "field_center_out",
        "spectrum_slot_sigma": 1.25,
        "ribbon_supersample": 7,
        "render_path": "rgba_2d",
        "render_aa": "coverage_taps",
        "field_geometry": "mirrored_bars",
        "bar_width": 5.5,
        "bar_gap": 3.25,
        "bar_count": 19,
        "bar_fill": 0.75,
        "bar_align": "right",
        "bar_alternate": False,
        "bar_color_b": "#123456",
        "bar_center_line_width": 2.5,
        "waveform_color": "#A1B2C3",
        "glow_level": "low",
        "classic_alternate_opacity": 0.375,
        "phases": PhaseTimes(),
    }


def _request(tmp_path: Path) -> dict[str, Any]:
    return {"output_dir": tmp_path / "output", "formats": [], "force": False}


def _assert_options(options: RenderOptions, request: dict[str, Any]) -> None:
    assert [field.name for field in fields(options)] == OPTION_NAMES
    for name, _, _, default in RENDER_PARAMETERS[4:]:
        expected = request.get(name, default)
        actual = getattr(options, name)
        assert type(actual) is type(expected), name
        assert actual == expected, name
        if name in request:
            assert actual is expected, name


def test_literal_legacy_signatures_and_defaults() -> None:
    for function, expected, result in (
        (render_module.render_job, RENDER_PARAMETERS, "dict[str, Any]"),
        (service.render, SERVICE_PARAMETERS, "list[dict[str, object]]"),
        (render_module._render_options_from_legacy, RENDER_PARAMETERS[4:], "RenderOptions"),
    ):
        signature = inspect.signature(function)
        actual = [
            (p.name, p.kind.name, p.annotation, p.default) for p in signature.parameters.values()
        ]
        # FR-LOOK-CONTROLS/AMPLITUDE/REFLECTION add keyword-only controls to
        # the service only. Keep every frozen legacy parameter/type/default exact.
        if function is service.render:
            expected = [
                *expected,
                ("detail_level", "KEYWORD_ONLY", "str | None", None),
                ("amplitude", "KEYWORD_ONLY", "float | None", None),
                ("stroke_width", "KEYWORD_ONLY", "float | None", None),
                ("visual_noise", "KEYWORD_ONLY", "float | None", None),
                ("idle_activity", "KEYWORD_ONLY", "float | None", None),
                ("noise_rate", "KEYWORD_ONLY", "float | None", None),
                ("noise_seed", "KEYWORD_ONLY", "int | None", None),
                ("reflection_opacity", "KEYWORD_ONLY", "float | None", None),
                ("center_line", "KEYWORD_ONLY", "bool | None", None),
                ("center_line_extent", "KEYWORD_ONLY", "float | None", None),
                ("center_line_opacity", "KEYWORD_ONLY", "float | None", None),
                ("background_mode", "KEYWORD_ONLY", "str | None", None),
                ("color_mode", "KEYWORD_ONLY", "str | None", None),
            ]
        # The opt-in experiment bridge is an intentional 0.3.0 API addition.
        # Keep every pre-existing parameter/type/default exact above, and require
        # the only new public parameter to remain keyword-only and inactive by default.
        if function in (render_module.render_job, service.render):
            expected = [*expected, ("experiment", "KEYWORD_ONLY", "ServiceExperiment | None", None)]
        assert actual == expected
        for got, want in zip(actual, expected, strict=True):
            assert type(got[3]) is type(want[3])  # False must not silently become 0.
        assert signature.return_annotation == result
    assert vars(benchmark)["render_job"] is render_module.render_job
    assert vars(service)["render_job"] is render_module.render_job
    executor_signature = inspect.signature(render_module._render_job)
    assert [
        (p.name, p.kind.name, p.annotation, p.default)
        for p in executor_signature.parameters.values()
    ] == [
        ("context", "POSITIONAL_OR_KEYWORD", "RenderContext", REQUIRED),
        ("options", "POSITIONAL_OR_KEYWORD", "RenderOptions", REQUIRED),
        ("experiment", "KEYWORD_ONLY", "ServiceExperiment | None", None),
    ]
    assert executor_signature.return_annotation == "RendererOutcome"


def test_adapter_and_executor_use_explicit_complete_typed_mapping() -> None:
    adapter = ast.parse(inspect.getsource(render_module._render_options_from_legacy)).body[0]
    assert isinstance(adapter, ast.FunctionDef)
    assert len(adapter.body) == 2  # Docstring plus the explicit constructor return.
    returned = adapter.body[-1]
    assert isinstance(returned, ast.Return)
    assert isinstance(returned.value, ast.Call)
    assert isinstance(returned.value.func, ast.Name)
    assert returned.value.func.id == "RenderOptions"
    assert returned.value.args == []
    assert [keyword.arg for keyword in returned.value.keywords] == OPTION_NAMES
    for keyword in returned.value.keywords:
        assert isinstance(keyword.value, ast.Name)
        assert keyword.value.id == keyword.arg
    executor = ast.parse(inspect.getsource(render_module._render_job)).body[0]
    assert isinstance(executor, ast.FunctionDef)
    names = ["job", "media", "preset", "performance", *OPTION_NAMES]
    assert len(executor.body) > len(names)
    for index, name in enumerate(names):
        binding = executor.body[index]
        assert isinstance(binding, ast.Assign)
        assert len(binding.targets) == 1
        target = binding.targets[0]
        assert isinstance(target, ast.Name)
        assert target.id == name
        assert isinstance(binding.value, ast.Attribute)
        assert binding.value.attr == name
        assert isinstance(binding.value.value, ast.Name)
        assert binding.value.value.id == ("context" if index < 4 else "options")


@pytest.mark.parametrize(
    "formats",
    [
        [],
        ["png"],
        ["prores4444"],
        ["png", "prores4444"],
        ["prores4444", "png"],
        ["png", "png"],
        ["PNG", "legacy-invalid", "png"],
    ],
)
def test_adapter_keeps_format_order_duplicates_case_and_invalid_tokens(
    tmp_path: Path, formats: list[str]
) -> None:
    options = render_module._render_options_from_legacy(
        output_dir=tmp_path / "out", formats=formats, force=False
    )
    assert options.formats is formats


def test_dataclass_fields_annotations_and_defaults_match_literal_contract(tmp_path: Path) -> None:
    assert [field.name for field in fields(RenderContext)] == [
        "job",
        "media",
        "preset",
        "performance",
    ]
    assert [field.type for field in fields(RenderContext)] == [
        "PlannedJob",
        "SourceMedia",
        "VisualPreset",
        "PerformanceProfile",
    ]
    assert [(field.name, field.type) for field in fields(RenderOptions)] == [
        (name, annotation) for name, _, annotation, _ in RENDER_PARAMETERS[4:]
    ]
    assert [(field.name, field.type) for field in fields(RendererOutcome)] == [
        ("payload", "dict[str, Any]")
    ]
    request = _request(tmp_path)
    _assert_options(RenderOptions(**request), request)
    for name in ("output_dir", "formats", "force"):
        request = _request(tmp_path)
        del request[name]
        with pytest.raises(TypeError):
            RenderOptions(**request)
        with pytest.raises(TypeError):
            render_module._render_options_from_legacy(**request)


def test_adapter_preserves_every_default(tmp_path: Path) -> None:
    request = _request(tmp_path)
    _assert_options(render_module._render_options_from_legacy(**request), request)


@pytest.mark.parametrize("name", OPTION_NAMES)
def test_adapter_each_independent_override(tmp_path: Path, name: str) -> None:
    request = _request(tmp_path)
    request[name] = _overrides(tmp_path)[name]
    _assert_options(render_module._render_options_from_legacy(**request), request)


def test_adapter_all_overrides_and_no_extra_keys(tmp_path: Path) -> None:
    request = _overrides(tmp_path)
    assert set(request) == set(OPTION_NAMES)
    _assert_options(render_module._render_options_from_legacy(**request), request)
    with pytest.raises(TypeError):
        render_module._render_options_from_legacy(**request, unknown_option=True)


@pytest.mark.parametrize("name", OPTION_NAMES)
@pytest.mark.parametrize("raw", [None, False, 0, -1, "legacy-invalid", object()])
def test_adapter_never_coerces_even_legacy_invalid_raw_values(
    tmp_path: Path, name: str, raw: Any
) -> None:
    # Runtime acceptance remains at the old use sites, not in nominal typed transport.
    request = _request(tmp_path)
    request[name] = raw
    options = render_module._render_options_from_legacy(**request)
    _assert_options(options, request)
    assert getattr(options, name) is raw


@pytest.mark.parametrize("selection", ["defaults", "all", *OPTION_NAMES])
def test_wrapper_uses_typed_boundary_for_every_keyword(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    request = _request(tmp_path)
    if selection == "all":
        request = _overrides(tmp_path)
    elif selection != "defaults":
        request[selection] = _overrides(tmp_path)[selection]
    references = (object(), object(), object(), object())
    payload: dict[str, Any] = {"mutable": []}
    executor = Mock(return_value=RendererOutcome(payload))
    monkeypatch.setattr(render_module, "_render_job", executor)
    actual = render_module.render_job(*references, **request)
    assert actual is payload
    executor.assert_called_once()
    context, options = executor.call_args.args
    assert type(context) is RenderContext
    assert type(options) is RenderOptions
    for name, value in zip(("job", "media", "preset", "performance"), references, strict=True):
        assert getattr(context, name) is value
    _assert_options(options, request)
    actual["after_return"] = True
    assert payload["after_return"] is True


@pytest.mark.parametrize("status", ["SKIPPED", "FAILED", "SUCCEEDED"])
def test_wrapper_returns_identical_outcome_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    payload: dict[str, Any] = {"job": {"status": status}, "extra": object()}
    executor = Mock(return_value=RendererOutcome(payload))
    monkeypatch.setattr(render_module, "_render_job", executor)
    assert render_module.render_job(*[object()] * 4, **_request(tmp_path)) is payload


@pytest.mark.parametrize("error", [ValueError("raw"), RuntimeError("escape"), OSError("io")])
def test_wrapper_does_not_intercept_or_rebuild_escaping_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    executor = Mock(side_effect=error)
    monkeypatch.setattr(render_module, "_render_job", executor)
    with pytest.raises(type(error)) as caught:
        render_module.render_job(*[object()] * 4, **_request(tmp_path))
    assert caught.value is error


def test_frozen_contracts_are_shallow_and_keep_reference_identity(tmp_path: Path) -> None:
    request = _overrides(tmp_path)
    options = RenderOptions(**request)
    references: list[Any] = [object() for _ in range(4)]
    context = RenderContext(*references)
    payload: dict[str, Any] = {}
    outcome = RendererOutcome(payload)
    for instance, name in ((options, "formats"), (context, "job"), (outcome, "payload")):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, name, None)
    request["formats"].append("legacy-invalid")
    request["phases"].extras["sentinel"] = 0
    payload["new"] = False
    assert options.formats is request["formats"]
    assert options.formats[-1] == "legacy-invalid"
    assert options.progress is request["progress"]
    assert options.phases is request["phases"]
    assert options.phases is not None
    assert options.phases.extras["sentinel"] == 0
    assert outcome.payload is payload
    assert outcome.payload["new"] is False


def test_contract_module_has_no_renderer_or_domain_reverse_dependencies() -> None:
    module = importlib.import_module("ewp_waveform.application.render_types")
    tree = ast.parse(inspect.getsource(module))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {
        "__future__",
        "collections.abc",
        "dataclasses",
        "pathlib",
        "typing",
        "ewp_waveform.application.timing",
        "ewp_waveform.config.models",
        "ewp_waveform.domain.models",
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert {node.name for node in classes} == {"RenderOptions", "RenderContext", "RendererOutcome"}
    assert all(not node.bases for node in classes)
    assert not any(isinstance(node, ast.FunctionDef) for cls in classes for node in cls.body)
    domain_dir = Path(inspect.getfile(module)).parents[1] / "domain"
    for path in domain_dir.glob("*.py"):
        domain = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(domain):
            if isinstance(node, ast.ImportFrom):
                assert "render_types" not in (node.module or ""), path
            elif isinstance(node, ast.Import):
                assert all("render_types" not in item.name for item in node.names), path
