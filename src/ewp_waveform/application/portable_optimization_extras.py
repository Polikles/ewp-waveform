"""Bounded output-preparation and compact-area additions to the existing runner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def compact_render(request: dict[str, Any]) -> dict[str, Any]:
    from ewp_waveform.application.portable_experiments_state import identity
    from ewp_waveform.application.working_area_experiment import render_working_area
    from ewp_waveform.ffmpeg.experiments import Crop
    from ewp_waveform.ffmpeg.working_area import WorkingArea

    w = request["workload"]
    output = Path(request["media"]) / "native.mov"
    result = render_working_area(
        source=Path(request["audio"]),
        start=w["start"],
        duration=w["duration"],
        output=output,
        area=WorkingArea(Crop(*request["crop"]), request["margin"]),
        control=request["control"],
        ffmpeg=request["ffmpeg"],
        ffprobe=request["ffprobe"],
        visual_overrides=request["visual_overrides"],
    )
    return {
        **result,
        "workload": w,
        "wall_seconds": result["pipeline_wall_seconds"],
        "timer": result["pipeline_timer"],
        "route": result["scope"],
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "render_fps": w["frames"] / result["pipeline_wall_seconds"],
        "artifacts": [identity(output)],
        "phase_metrics": result["raster_feed"],
        "visual": "PENDING",
        "studio": "PENDING",
    }


def extras(
    config: dict[str, Any],
    workloads: list[dict[str, Any]],
    step: Callable[..., dict[str, Any]],
    skipped: Callable[[str, str], None],
) -> None:
    """Fresh AB/BA pairs; independent CUDA gates and explicit fixed compact geometry."""
    w = next(w for w in workloads if w["id"] in ("speech", "smoke"))

    def pair(
        label: str, a: dict[str, Any], b: dict[str, Any], *, python: str | None = None
    ) -> None:
        for ordinal in range(1, config["repeats"] + 1):
            order = "AB" if ordinal % 2 else "BA"
            for side in order:
                step(
                    f"{label}-r{ordinal:02d}-{side}",
                    {
                        **(a if side == "A" else b),
                        "workload": w,
                        "pair": {
                            "id": label,
                            "repeat": ordinal,
                            "order": order,
                            "side": side,
                            "comparison": label + "; one named finishing/output variable",
                        },
                    },
                    optional=True,
                    **({"python": python} if python else {}),
                )

    if config.get("optimization", {}).get("compact"):
        # Frozen from the whole local speech control's alpha>0 bounds [13,254]
        # plus8px. Not an automatic universal crop or a threshold change.
        common = {"operation": "compact", "crop": [0, 5, 1400, 258, 1400, 280], "margin": 48}
        pair(
            "opt-crop-output", {**common, "control": "CPU-BASE"}, {**common, "control": "CROP-OUT"}
        )
        pair(
            "opt-crop-working",
            {**common, "control": "CROP-OUT"},
            {**common, "control": "EARLY-AREA"},
        )

    if not config.get("cuda"):
        return
    if not config.get("cuda_environment"):
        skipped("opt-fir-output", "CUDA preparation unavailable: " + str(config.get("cuda_error")))
        return
    python = config["cuda_python"]
    control = {
        "operation": "cuda",
        "backend": "cuda",
        "output_mode": "host-reference",
        "batch_size": 1,
        "timing_mode": "diagnostic",
    }
    variants = [
        ("opt-fir-host-reuse", control, {**control, "output_mode": "host-reuse"}),
        (
            "opt-fir-device-rgba",
            {**control, "output_mode": "host-reuse"},
            {**control, "output_mode": "device-rgba"},
        ),
        (
            "opt-fir-device-alpha8",
            {**control, "output_mode": "host-reuse"},
            {**control, "output_mode": "device-alpha8"},
        ),
        (
            "opt-fir-batch2",
            {**control, "output_mode": "host-reuse"},
            {**control, "output_mode": "host-reuse", "batch_size": 2},
        ),
        (
            "opt-fir-ordinary",
            {**control, "output_mode": "host-reuse"},
            {**control, "output_mode": "host-reuse", "timing_mode": "ordinary"},
        ),
    ]
    gates: dict[tuple[Any, ...], bool] = {}
    for label, a, b in variants:
        ready = True
        for request in (a, b):
            key = (request["output_mode"], request["batch_size"], request["timing_mode"])
            if key not in gates:
                q = step(
                    "opt-fir-qualify-" + "-".join(map(str, key)),
                    {
                        **request,
                        "operation": "qualify-finish",
                    },
                    optional=True,
                    python=python,
                )
                gates[key] = q.get("status") == "SUCCEEDED" and q.get("passed") is True
            ready = ready and gates[key]
        if ready:
            pair(label, a, b, python=python)
        else:
            skipped(label, "selected output/batch/timing CUDA route failed its independent oracle")
