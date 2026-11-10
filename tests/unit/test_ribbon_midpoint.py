from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from ewp_waveform.analysis.frames import AnalysisFrame
from ewp_waveform.application.appearance import resolve_fixed_axis_appearance
from ewp_waveform.config.load import load_preset
from ewp_waveform.identity import render_signature
from ewp_waveform.visual.mapping import RefinedRibbonMapping
from ewp_waveform.visual.ribbon import field_to_columns


@pytest.mark.parametrize("detail", ["smooth", "balanced", "detailed"])
def test_spectral_neighbors_cross_fixed_midpoint_without_radial_split(detail: str) -> None:
    mapping = RefinedRibbonMapping(detail_level=detail)
    centers = [sum(j * w for j, w in enumerate(row)) for row in mapping.fine_weights]
    assert all(a < b for a, b in pairwise(centers))
    assert centers[32] == pytest.approx(31.5)
    # A middle-band feature forms one local middle region, not distant twins.
    bands = [0.0] * 64
    bands[31] = bands[32] = 1.0
    frame = AnalysisFrame.from_bands(bands)
    slots = np.asarray(mapping.apply(frame).amplitude)
    assert abs(int(slots.argmax()) - 32) <= 1
    columns = np.asarray(field_to_columns(mapping.apply(frame), 1400))
    assert abs(int(columns.argmax()) - 699.5) < 24
    assert np.all(np.diff(columns[:680]) >= -1e-10)
    assert np.all(np.diff(columns[720:]) <= 1e-10)
    # Repeated/louder/quiet inputs cannot move the fixed map or create activity.
    before = mapping.fine_weights
    assert mapping.apply(frame) == mapping.apply(frame)
    louder = mapping.apply(AnalysisFrame.from_bands([2 * v for v in bands]))
    assert louder.amplitude == pytest.approx(2 * slots)
    assert mapping.apply(AnalysisFrame((0.0,) * 64, overall_level=1.0)).amplitude == (0.0,) * 65
    assert mapping.fine_weights is before


@pytest.mark.parametrize("band", [8, 24, 40, 56])
def test_off_midpoint_audio_stays_off_midpoint_with_stationary_coordinates(band: int) -> None:
    mapping = RefinedRibbonMapping(detail_level="detailed")
    bands = [0.0] * 64
    bands[band] = 1.0
    slots = np.asarray(mapping.apply(AnalysisFrame.from_bands(bands)).amplitude)
    assert abs(int(slots.argmax()) - band * 64 / 63) <= 1
    assert slots[0] == slots[-1] == 0.0


def test_mapping_revision_invalidates_old_output_without_changing_v1_identity() -> None:
    preset = load_preset("iuris-ribbon-refined")
    recipe = resolve_fixed_axis_appearance(preset).identity()
    assert recipe["mapping_revision"] == 3
    old = dict(recipe, mapping_revision=2)
    common = dict(source_sha256="fixture", preset=preset, fps=60)
    assert render_signature(**common, fixed_axis_recipe=recipe) != render_signature(
        **common, fixed_axis_recipe=old
    )
    v1 = resolve_fixed_axis_appearance(load_preset("iuris-ribbon-fixed")).identity()
    assert "mapping_revision" not in v1
