"""Pure admission, geometry and descriptive difference contracts."""

from pathlib import Path

import numpy as np
import pytest

from ewp_waveform.application.working_area_experiment import render_working_area
from ewp_waveform.ffmpeg.experiments import Crop
from ewp_waveform.ffmpeg.working_area import WorkingArea, difference_metrics, working_area_graph


def test_metadata_freezes_canvas_horizon_and_placement() -> None:
    area = WorkingArea(Crop(3, 7, 16, 8, 24, 20), 3)
    data = area.record(6, 1, "EARLY-AREA")
    assert data["placement_offset_xy"] == [3, 7]
    assert data["placement"]["horizon_output_y"] == 3.5
    assert data["placement"]["reflection_split_row"] == 10
    assert data["placement"]["frozen_for_whole_clip"]
    assert data["working_padded_y_interval"] == [10, 24]
    assert data["working_width"] == 36
    assert data["production_promotion"] is False
    assert data["visual_acceptance"] == data["resolve_acceptance"] == "PENDING"
    assert area.record(6, 1, "CROP-OUT")["working_padded_y_interval"] == [0, 32]
    baseline = area.record(6, 1, "CPU-BASE")
    assert baseline["placement"]["horizon_output_y"] == 10.5
    assert baseline["placement_offset_xy"] == [0, 0]
    assert baseline["frozen_export_rectangle"]["horizon_output_y"] == 3.5


@pytest.mark.parametrize("margin", [-1, True, 1.5])
def test_explicit_integer_margin(margin: int) -> None:
    with pytest.raises(ValueError, match="integer"):
        WorkingArea(Crop(0, 0, 2, 2, 4, 4), margin)


def test_unsafe_or_no_reduction_refused() -> None:
    crop = Crop(0, 0, 4, 4, 4, 4)
    with pytest.raises(ValueError, match="margin"):
        WorkingArea(crop, 2).domain(6, 1)
    with pytest.raises(ValueError, match="no smaller"):
        WorkingArea(crop, 100).domain(6, 1)
    with pytest.raises(ValueError, match="margin"):
        WorkingArea(crop, 0).domain(0, 0)
    # Post-finish crop does not pretend its margin reduces earlier work.
    assert WorkingArea(crop, 0).record(6, 1, "CROP-OUT")["working_padded_y_interval"] == [0, 16]


def test_only_known_gray_seam_admitted() -> None:
    with pytest.raises(ValueError, match="gray"):
        working_area_graph(
            area=WorkingArea(Crop(0, 0, 2, 2, 8, 8), 3),
            control="EARLY-AREA",
            overscan=4,
            supersample=2,
            glow=1,
            color="#F2C558",
            finish=(0.3, True, 1.25, 0.7, 0.5),
            pix_fmt="rgba",
        )


def test_thresholds_report_faint_loss_without_approval() -> None:
    crop = Crop(1, 1, 2, 2, 4, 4)
    original = np.zeros((4, 4, 4), dtype=np.uint8)
    original[0, 0] = [250, 100, 50, 1]
    original[1:3, 1:3] = [250, 100, 50, 127]
    data = difference_metrics(original.tobytes(), original[1:3, 1:3].tobytes(), crop=crop)
    assert data["inside_alpha_max_error"] == 0
    assert data["outside_crop_alpha_max"] == 1
    assert data["outside_alpha_exceeds_codes"] == {"0": 1, "1": 0, "2": 0, "8": 0, "32": 0}
    assert "no appearance PASS" in data["threshold_semantics"]


def test_invalid_requests_do_not_allocate(tmp_path: Path) -> None:
    output = tmp_path / "never-created" / "out.mov"
    area = WorkingArea(Crop(0, 0, 2, 2, 1400, 280), 48)
    for start, duration in ((-1, 1), (0, 33), (float("nan"), 1), (0, 0)):
        with pytest.raises(ValueError, match="finite"):
            render_working_area(
                source=tmp_path / "a.wav",
                output=output,
                start=start,
                duration=duration,
                area=area,
                control="EARLY-AREA",
            )
    source = tmp_path / "rendered.mov"
    source.write_bytes(b"not an original audio input")
    with pytest.raises(ValueError, match="master"):
        render_working_area(
            source=source, output=output, start=0, duration=0.1, area=area, control="CROP-OUT"
        )
    assert not output.parent.exists()
