"""New named campaigns retain strict matched-pair statistics after integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from ewp_waveform.application.cuda_combined_experiment import COMBINED, CONTROL
from ewp_waveform.application.portable_experiments_reporting import pair_statistics


@pytest.mark.parametrize(
    "group,controls",
    [
        ("single-file-short-lut", {"finish_lut": True}),
        ("single-file-lut32", {"finish_lut": True}),
        ("single-file-jobs32", {"jobs": 1}),
        ("cuda-combined-short", COMBINED),
        ("cuda-combined-service32", COMBINED),
    ],
)
def test_new_pairs_accept_only_named_changes(group: str, controls: dict[str, Any]) -> None:
    records = {}
    for repeat, order in [(1, "AB"), (2, "BA")]:
        for side in order:
            records[f"{repeat}-{side}"] = {
                "status": "SUCCEEDED",
                "actual_action": "PROCESS",
                "throughput_fresh": True,
                "validation": {"passed": True, "frames": 240},
                "wall_seconds": 2.0,
                "timer": "same timer",
                "route": "same route",
                "workload": {"start": 25.0, "duration": 4.0, "frames": 240},
                "execution_settings": {"python": "same", "ffmpeg": "same", "source": "same"},
                "experimental_controls": dict(CONTROL if group.startswith("cuda") else {})
                if side == "A"
                else controls,
                "pair": {
                    "id": group,
                    "repeat": repeat,
                    "side": side,
                    "order": order,
                    "comparison": "fixture, not timing",
                },
            }
    statistics = pair_statistics(records)
    assert statistics[0]["validated_paired_n"] == 2
    assert not statistics[0]["excluded"]
    broken = deepcopy(records)
    broken["1-B"]["experimental_controls"] = {**controls, "undeclared": True}
    assert pair_statistics(broken)[0]["validated_paired_n"] == 1
    assert (
        pair_statistics(broken)[0]["excluded"][0]["reason"]
        == "undeclared experimental control changes"
    )


def test_combined_control_keeps_proven_reusable_host_assembly() -> None:
    assert CONTROL == {"output_mode": "host-reuse", "batch_size": 1, "timing_mode": "diagnostic"}
    assert COMBINED == {"output_mode": "device-rgba", "batch_size": 2, "timing_mode": "ordinary"}
