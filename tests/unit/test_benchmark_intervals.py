from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ewp_waveform.application import benchmark
from ewp_waveform.application.benchmark import expand_benchmark
from ewp_waveform.application.estimate import estimate_output_mb
from ewp_waveform.config.load import load_benchmark_manifest
from ewp_waveform.config.models import (
    ApplicationConfig,
    BenchmarkInput,
    BenchmarkManifest,
    BenchmarkSection,
    BenchmarkVariant,
)
from ewp_waveform.paths import project_root


def test_manifest_retains_numeric_intervals_and_legacy_defaults(tmp_path: Path) -> None:
    path = tmp_path / "interval.toml"
    path.write_text(
        'schema_version = 1\nname = "clip"\n'
        '[[inputs]]\npath = "a.wav"\nstart = 25.125\nduration = 8\n'
        '[[inputs]]\npath = "b.wav"\n'
        '[[variants]]\nname = "v"\npreset = "iuris-default"\n'
        '[benchmark]\nrenderers = ["ffmpeg"]\nformats = ["png"]\n',
        encoding="utf-8",
    )
    manifest = load_benchmark_manifest(path)
    assert manifest.inputs[0].start == 25.125
    assert manifest.inputs[0].duration == 8.0
    assert manifest.inputs[1].start is None
    assert manifest.inputs[1].duration is None


@pytest.mark.parametrize(
    "bounds",
    [
        {"start": -0.1},
        {"start": float("nan")},
        {"start": float("inf")},
        {"start": -float("inf")},
        {"duration": float("nan")},
        {"duration": float("inf")},
        {"duration": -float("inf")},
        {"duration": 0},
        {"duration": -1},
        {"start": True},
        {"duration": False},
        {"start": "25"},
        {"duration": "8"},
        {"start_seconds": 25},
        {"duraton": 8},
    ],
)
def test_invalid_benchmark_input_does_not_silently_expand(bounds: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BenchmarkInput.model_validate({"path": "a.wav", **bounds})
    # Do not globally tighten unrelated configuration models.
    assert ApplicationConfig.model_validate({"unrelated_extension": True}).schema_version == 1


def test_benchmark_input_schema_matches_interval_contract() -> None:
    schema = json.loads((project_root() / "schemas/benchmark.schema.json").read_text())
    item = schema["properties"]["inputs"]["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["start"] == {"type": "number", "minimum": 0}
    assert item["properties"]["duration"] == {"type": "number", "exclusiveMinimum": 0}


@pytest.mark.parametrize(
    "start,duration,effective_start,effective_duration",
    [(None, None, 0, 10), (1.125, 2.25, 1.125, 2.25), (8, 5, 8, 2), (8, None, 8, 2)],
)
def test_planning_uses_effective_estimate_and_requested_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start: float | None,
    duration: float | None,
    effective_start: float,
    effective_duration: float,
) -> None:
    source = tmp_path / "s0e00-Test.wav"
    source.write_bytes(b"probe stub")
    monkeypatch.setattr(benchmark, "probe_media", lambda _: SimpleNamespace(duration_seconds=10))
    manifest = BenchmarkManifest(
        schema_version=1,
        name="clip",
        inputs=[BenchmarkInput(path=str(source), start=start, duration=duration)],
        variants=[BenchmarkVariant(name="v", preset="iuris-default")],
        benchmark=BenchmarkSection(renderers=["ffmpeg"], formats=["png"], dry_run_estimates=True),
    )
    out = tmp_path / "out"
    cell = expand_benchmark(manifest, manifest_dir=tmp_path, output_dir=out)[0]
    assert cell.action == "PROCESS"
    assert cell.duration_seconds == 10  # source duration compatibility field
    assert (cell.start, cell.duration) == (start, duration)
    assert cell.effective_start_seconds == effective_start
    assert cell.effective_duration_seconds == effective_duration
    assert cell.estimated_output_mb == estimate_output_mb(
        effective_duration, cell.preset, cell.formats
    )
    assert cell.png_path is not None
    # Same ordinal/root: different intervals cannot reuse the first destination.
    other = manifest.model_copy(deep=True)
    other.inputs[0] = BenchmarkInput(path=str(source), start=0.5, duration=1)
    changed = expand_benchmark(other, manifest_dir=tmp_path, output_dir=out)[0]
    assert changed.png_path != cell.png_path
    assert not out.exists()


@pytest.mark.parametrize("start", [10, 10.1])
def test_empty_effective_interval_is_rejected_during_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start: float
) -> None:
    source = tmp_path / "s0e00-Test.wav"
    source.write_bytes(b"probe stub")
    monkeypatch.setattr(benchmark, "probe_media", lambda _: SimpleNamespace(duration_seconds=10))
    manifest = BenchmarkManifest(
        schema_version=1,
        name="empty",
        inputs=[BenchmarkInput(path=str(source), start=start, duration=1)],
        variants=[BenchmarkVariant(name="v", preset="iuris-default")],
        benchmark=BenchmarkSection(renderers=["ffmpeg"], formats=["png"]),
    )
    with pytest.raises(ValueError, match="no renderable duration"):
        expand_benchmark(manifest, manifest_dir=tmp_path, output_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()
