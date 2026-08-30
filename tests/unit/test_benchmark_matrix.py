from pathlib import Path

from ewp_waveform.application.benchmark import apply_overrides, expand_benchmark
from ewp_waveform.config.load import load_benchmark_manifest, load_preset
from ewp_waveform.config.models import (
    BenchmarkInput,
    BenchmarkManifest,
    BenchmarkSection,
    BenchmarkVariant,
)
from ewp_waveform.identity import sha256_file
from ewp_waveform.paths import project_root


def test_example_manifest_loads() -> None:
    path = project_root() / "examples" / "benchmarks" / "benchmark.example.toml"
    manifest = load_benchmark_manifest(path)
    assert manifest.name == "initial-style-and-performance-matrix"
    assert len(manifest.inputs) == 2
    assert len(manifest.variants) == 3
    assert manifest.benchmark.formats == ["prores4444", "png"]


def test_expand_is_cartesian_and_missing_inputs_are_blocked() -> None:
    manifest = BenchmarkManifest(
        schema_version=1,
        name="cart",
        inputs=[
            BenchmarkInput(path="/no/such/a.wav"),
            BenchmarkInput(path="/no/such/b.wav"),
        ],
        variants=[
            BenchmarkVariant(name="canonical", preset="iuris-default"),
            BenchmarkVariant(
                name="filled",
                preset="iuris-default",
                overrides={"style": "filled"},
            ),
        ],
        benchmark=BenchmarkSection(
            renderers=["ffmpeg"],
            formats=["prores4444"],
            performance_profiles=["balanced", "maximum"],
        ),
    )
    cells = expand_benchmark(manifest, manifest_dir=Path("."), output_dir=Path("/tmp/out"))
    assert len(cells) == 8
    assert all(cell.action == "BLOCKED" for cell in cells)
    names = {(cell.input_path.name, cell.variant_name, cell.performance_name) for cell in cells}
    assert ("a.wav", "filled", "maximum") in names


def test_overrides_do_not_write_canonical_preset() -> None:
    preset_path = project_root() / "presets" / "iuris-default.toml"
    before = sha256_file(preset_path)
    base = load_preset("iuris-default")
    clone = apply_overrides(base, {"style": "filled", "glow": "high"}, "filled-high-glow")
    assert clone.waveform.style == "filled"
    glow = clone.effects.get("glow")
    assert isinstance(glow, dict)
    assert glow.get("level") == "high"
    assert clone.name == "iuris-default--filled-high-glow"
    assert load_preset("iuris-default").waveform.style == "mirrored"
    assert sha256_file(preset_path) == before


def test_unknown_override_is_rejected() -> None:
    base = load_preset("iuris-default")
    try:
        apply_overrides(base, {"particles": True}, "bad")
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unsupported_renderer_is_marked() -> None:
    manifest = BenchmarkManifest(
        schema_version=1,
        name="gpu",
        inputs=[BenchmarkInput(path="/no/such.wav")],
        variants=[BenchmarkVariant(name="canonical", preset="iuris-default")],
        benchmark=BenchmarkSection(
            renderers=["custom"],
            formats=["prores4444"],
            performance_profiles=["balanced"],
        ),
    )
    cells = expand_benchmark(manifest, manifest_dir=Path("."), output_dir=Path("/tmp/out"))
    assert cells[0].action == "UNSUPPORTED"
