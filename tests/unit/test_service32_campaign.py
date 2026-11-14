from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application.portable_experiments_optimize import campaign
from ewp_waveform.application.portable_experiments_worker import performance_file


def test_service_profile_generation_changes_only_selected_execution_flag(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    before = tomllib.loads(performance_file(a).read_text())
    after = tomllib.loads(performance_file(b, finish_lut=True).read_text())
    assert before["processing"].pop("ribbon_finish_lut") is False
    assert after["processing"].pop("ribbon_finish_lut") is True
    assert before["processing"] == after["processing"]
    assert after["processing"]["jobs"] == 2
    with pytest.raises(ValueError, match="strict bool"):
        performance_file(a, finish_lut="true")  # type: ignore[arg-type]


@pytest.mark.parametrize("qualified", [True, False])
def test_counterbalanced_service32_uses_actual_service_and_matched_oracle(qualified: bool) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    skipped: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        return {
            "status": "SUCCEEDED",
            "passed": qualified,
            "output": "control.mov",
            "original_raster_sha256": "spy-not-performance",
        }

    campaign(
        {
            "optimization": {
                "service32": True,
                "encoder_threads": 2,
                "filter_threads": 1,
                "async_depth": None,
            },
            "repeats": 2,
        },
        [{"id": "speech", "start": 25.0, "duration": 4.0, "frames": 240}],
        step,
        lambda n, r: skipped.append(n),
        {},
    )
    cells = [(n, v) for n, v in calls if n.startswith("opt-service-lut32-r")]
    if not qualified:
        assert not cells and "opt-service-lut32" in skipped
        return
    assert [v["pair"]["side"] for _, v in cells] == ["A", "B", "B", "A"]
    for _, request in cells:
        assert request["operation"] == "service"
        assert request["workload"] == {
            "id": "production32",
            "kind": "production32",
            "start": 25.0,
            "duration": 32.0,
            "frames": 1920,
        }
        if request.get("finish_lut"):
            assert request["reference"] == "control.mov"
        assert "variant" not in request
