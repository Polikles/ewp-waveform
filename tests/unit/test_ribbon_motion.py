from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.application import render as pipeline
from ewp_waveform.application import service
from ewp_waveform.cli import app
from ewp_waveform.visual.mapping import RefinedRibbonMapping


@pytest.mark.parametrize("command", ["dry-run", "render", "preview"])
def test_cli_motion_forwarding(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def stop(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise ValueError("captured")

    monkeypatch.setattr(service, "plan_jobs" if command == "dry-run" else "render", stop)
    CliRunner().invoke(
        app,
        [
            command,
            "source.wav",
            "--preset",
            "iuris-ribbon-refined",
            "--visual-noise",
            "0.35",
            "--idle-activity",
            "0.035",
            "--noise-rate",
            "0.8",
            "--noise-seed",
            "1729",
        ],
    )
    assert {k: seen[k] for k in ("visual_noise", "idle_activity", "noise_rate", "noise_seed")} == {
        "visual_noise": 0.35,
        "idle_activity": 0.035,
        "noise_rate": 0.8,
        "noise_seed": 1729,
    }


def test_idle_not_amplified_by_quiet_normalization_and_canonical_partitions() -> None:
    frames = tuple(AnalysisFrame((0.0,) * 64, 0.0) for _ in range(120))
    sequence = AnalysisSequence(frames)
    off = RefinedRibbonMapping(audio_start_seconds=25)
    on = RefinedRibbonMapping(idle_activity=0.035, noise_seed=1729, audio_start_seconds=25)
    options: dict[str, Any] = dict(
        n_frames=120,
        draw_w=300,
        peak=1e-12,
        tau_seconds=0.06,
        fps=60,
        soft_clip=True,
        spatial_sigma=1.2,
        spatial_filter="gaussian",
    )
    off_rows = pipeline._precompute_field_columns(sequence, mapping=off, **options)
    on_rows = pipeline._precompute_field_columns(sequence, mapping=on, **options)
    assert np.max(off_rows) == 0
    assert 0 < np.max(on_rows) < 0.035
    assert not np.array_equal(on_rows[0], on_rows[-1])
    # Pool workers receive these canonical columns, not their own time/RNG state.
    ordered = np.asarray(on_rows)
    reconstructed = np.concatenate([ordered[60:120], ordered[:60]])
    assert np.array_equal(reconstructed[60:], ordered[:60])
    assert np.array_equal(reconstructed[:60], ordered[60:])


def test_motion_schema_consistency_when_prepared_validator_available() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from ewp_waveform.config.load import load_preset
    from ewp_waveform.paths import project_root

    schema = json.loads((Path(project_root()) / "schemas/preset.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    raw = load_preset("iuris-ribbon-refined").model_dump(exclude_none=True)
    validator.validate(raw)
