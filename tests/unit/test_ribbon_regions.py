from __future__ import annotations

import math
import pickle
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.cli import app
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import VisualPreset
from ewp_waveform.config.ribbon import apply_public_appearance
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.mapping import MovingMouthMapping, RefinedRibbonMapping


def _frame(center: float, level: float = 0.5) -> AnalysisFrame:
    return AnalysisFrame(
        tuple(0.02 + math.exp(-0.5 * ((j - center) / 3.0) ** 2) for j in range(64)), level
    )


@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
def test_amplitude_field_local_height_width_and_calm_history(detail: str, fps: float) -> None:
    mapping = RefinedRibbonMapping(detail_level=detail, fps=fps)
    left, right = _frame(10.0), _frame(48.0)
    seq = AnalysisSequence((left,) * 50 + (right,) * 60 + (left,) * 50)
    rows = np.asarray([mapping.apply_at(seq, i).amplitude for i in (49, 50, 109)])
    before, after = rows[0], rows[2]
    assert not np.allclose(before / before.max(), after / after.max())
    ratios = after[8:121] / before[8:121]
    assert ratios.min() < 0.5 and ratios.max() > 2.0
    assert (after - before).min() < -0.01 and (after - before).max() > 0.01
    assert np.max(np.abs(rows[1] - before)) < np.max(np.abs(after - before)) / 2
    # Actual half-local-peak widths in separated stationary neighborhoods change.
    widths = []
    for row in (before, after):
        widths.append(
            [np.count_nonzero(part > part.max() * 0.5) for part in np.array_split(row[4:-4], 21)]
        )
    assert any(a != b for a, b in zip(*widths, strict=True))
    halo = math.ceil(mapping.SHAPE_SUPPORT_SECONDS * fps)
    sub = AnalysisSequence(seq.frames[50:])
    assert mapping.apply_at(sub, halo) == mapping.apply_at(seq, 50 + halo)
    assert mapping.n_slots == 129 and len(mapping.LOBE_CENTERS) == 21


def test_speech_gate_homogeneity_and_quiet_baseline() -> None:
    mapping = RefinedRibbonMapping(visual_noise=0.35, noise_seed=1729)
    for center in (0.0, 8.0, 24.0, 40.0, 63.0):
        frame = _frame(center)
        row = np.asarray(mapping.apply(frame).amplitude)
        assert np.all(row[1:-1] > 0.0)
        assert row[0] == row[-1] == 0.0
        loud = AnalysisFrame(tuple(v * 2 for v in frame.bands), 1.0)
        assert mapping.apply(loud).amplitude == pytest.approx(row * 2)
    silence = AnalysisFrame((0.0,) * 64, 0.0)
    seq = AnalysisSequence((_frame(20),) * 50 + (silence,) * 100)
    for i in (50, 70, 149):
        assert mapping.apply_at(seq, i).amplitude == (0.0,) * 129
        assert mapping.idle_at(i).amplitude == (0.0,) * 129
    assert max(mapping.apply(AnalysisFrame((0.0,) * 64, 1.0)).amplitude) > 0.0


def test_seed_absolute_time_worker_order_and_smooth_noise_boundaries() -> None:
    mapping = RefinedRibbonMapping(visual_noise=0.35, noise_seed=1729, audio_start_seconds=25.0)
    seq = AnalysisSequence(tuple(_frame(10 + i % 40) for i in range(120)))
    expected = [mapping.apply_at(seq, i) for i in range(len(seq))]
    clone = pickle.loads(pickle.dumps(mapping))
    order = list(range(60, 120)) + list(reversed(range(60)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        actual = list(pool.map(lambda i: clone.apply_at(seq, i), order))
    assert actual == [expected[i] for i in order]
    start = RefinedRibbonMapping(noise_seed=1729, audio_start_seconds=0.0)
    for channel in range(21):
        for seconds in (25.0, 25.5, 26.0, 32.5):
            assert mapping.noise_at(channel, seconds) == start.noise_at(channel, seconds)
        boundary = 4 / mapping.noise_rate
        assert (
            abs(
                mapping.noise_at(channel, boundary - 1e-5)
                - mapping.noise_at(channel, boundary + 1e-5)
            )
            < 1e-8
        )
    # Same absolute time, independently constructed/partitioned idle evaluation.
    idle_a = RefinedRibbonMapping(idle_activity=0.035, noise_seed=1729, audio_start_seconds=25)
    idle_b = RefinedRibbonMapping(idle_activity=0.035, noise_seed=1729, audio_start_seconds=0)
    for i in (0, 30, 60, 90):
        assert idle_a.idle_at(i) == idle_b.idle_at(i + 1500)
    assert max(idle_a.idle_at(0).amplitude) < 0.035
    assert idle_a.idle_at(0) != idle_a.idle_at(60)
    assert mapping.apply_at(seq, 80) != RefinedRibbonMapping(
        visual_noise=0.35, noise_seed=1730, audio_start_seconds=25
    ).apply_at(seq, 80)
    zero_a = RefinedRibbonMapping(noise_seed=1)
    zero_b = RefinedRibbonMapping(noise_seed=2)
    assert zero_a.apply_at(seq, 80) == zero_b.apply_at(seq, 80)


@pytest.mark.parametrize(
    "key,value",
    [
        ("visual_noise", -0.01),
        ("visual_noise", 1.01),
        ("visual_noise", True),
        ("visual_noise", float("nan")),
        ("idle_activity", 0.151),
        ("idle_activity", -1),
        ("idle_activity", False),
        ("noise_rate", 0.09),
        ("noise_rate", 3.01),
        ("noise_rate", float("inf")),
        ("noise_seed", -1),
        ("noise_seed", 2147483648),
        ("noise_seed", True),
        ("noise_seed", 2.0),
    ],
)
def test_motion_control_rejections(key: str, value: object) -> None:
    data = load_preset("iuris-ribbon-refined").model_dump()
    data["signal"][key] = value
    with pytest.raises(ValueError):
        VisualPreset.model_validate(data)


def test_public_motion_effective_identity_and_legacy_preservation() -> None:
    preset = load_preset("iuris-ribbon-refined")
    recipe = resolve_fixed_axis_appearance(preset).identity()
    assert recipe["mapping_revision"] == 7
    assert preset.signal["visual_noise"] == preset.signal["idle_activity"] == 0
    assert recipe["noise_rate"] == 0.8 and recipe["noise_seed"] == 0
    original = render_signature(
        source_sha256="fixture", preset=preset, fps=60, fixed_axis_recipe=recipe
    )
    for key, value in (
        ("visual_noise", 0.35),
        ("idle_activity", 0.035),
        ("noise_rate", 1.2),
        ("noise_seed", 1729),
    ):
        override: dict[str, Any] = {key: value}
        changed = apply_public_appearance(preset, **override)
        assert changed.signal[key] == value
        new_recipe = resolve_fixed_axis_appearance(changed).identity()
        assert new_recipe[key] == value
        assert (
            render_signature(
                source_sha256="fixture", preset=changed, fps=60, fixed_axis_recipe=new_recipe
            )
            != original
        )
        assert preset.signal[key] != value
    for name in ("iuris-moving-mouth", "iuris-default", "iuris-ribbon-fixed"):
        old = load_preset(name)
        assert "visual_noise" not in old.signal
        with pytest.raises(ValueError, match="filled-ribbon-v2"):
            apply_public_appearance(old, visual_noise=0)
    assert (
        resolve_fixed_axis_appearance(load_preset("iuris-moving-mouth")).identity()[
            "mapping_revision"
        ]
        == 4
    )
    assert not issubclass(RefinedRibbonMapping, MovingMouthMapping)


def test_cli_exposes_motion_controls() -> None:
    runner = CliRunner()
    for command in ("dry-run", "render", "preview"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert "--visual-noise" in result.stdout and "--noise-seed" in result.stdout
