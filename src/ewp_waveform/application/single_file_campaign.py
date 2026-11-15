"""Targeted current-code single-file campaigns, not the historical negative matrix."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ewp_waveform.application.portable_experiments_diagnostics import failure_stage


def campaign(
    config: dict[str, Any],
    workloads: list[dict[str, Any]],
    step: Callable[..., dict[str, Any]],
    skipped: Callable[[str, str], None],
) -> None:
    """Independent CPU jobs policy and LUT; optional CUDA combined service follows."""
    short = next(w for w in workloads if w["id"] in ("speech", "smoke"))
    service = {"operation": "service", "jobs": 1}

    def pair(
        label: str,
        workload: dict[str, Any],
        a: dict[str, Any],
        b: dict[str, Any],
        comparison: str,
    ) -> tuple[bool, bool]:
        first: dict[str, Any] = {}
        values: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
        for repeat in range(1, config["repeats"] + 1):
            order = "AB" if repeat % 2 else "BA"
            for side in order:
                name = f"{label}-r{repeat:02d}-{side}"
                control_valid = (
                    first.get("status") == "SUCCEEDED"
                    and first.get("validation", {}).get("passed") is True
                )
                if side == "B" and not control_valid:
                    skipped(name, "matched service control unavailable")
                    values[side].append({"status": "SKIPPED"})
                    continue
                request_operation = (a if side == "A" else b)["operation"]
                request = {
                    **(a if side == "A" else b),
                    "workload": workload,
                    "pair": {
                        "id": label,
                        "repeat": repeat,
                        "order": order,
                        "side": side,
                        "comparison": comparison
                        + (
                            "; actual service.render includes per-encode setup/qualification, "
                            "validation/publication"
                            if request_operation == "service"
                            else "; direct pipeline includes selected finishing preparation; "
                            "no service publication"
                        ),
                    },
                }
                if control_valid:
                    request.update(reference=first["output"], reference_lossless=True)
                    if request["operation"] == "direct":
                        request["expected_raster_sha256"] = first["original_raster_sha256"]
                value = step(name, request, optional=True)
                values[side].append(value)
                if not first and side == "A":
                    first = value
        passed = [
            len(values[side]) == config["repeats"]
            and all(
                v.get("status") == "SUCCEEDED" and v.get("validation", {}).get("passed") is True
                for v in values[side]
            )
            for side in ("A", "B")
        ]
        return passed[0], passed[1]

    lut = step("single-file-lut-qualification", {"operation": "qualify-lut"}, optional=True)
    lut_ready = lut.get("status") == "SUCCEEDED" and lut.get("passed") is True
    if lut_ready:
        pair(
            "single-file-direct-lut",
            short,
            {"operation": "direct", "codec": "prores"},
            {"operation": "direct", "codec": "prores", "finish_lut": True},
            "matched direct production pipeline GEQ vs LUT; repaired executable alias seam; "
            "not service publication",
        )
        short_control, short_candidate = pair(
            "single-file-short-lut",
            short,
            service,
            {**service, "finish_lut": True},
            "same serial jobs1 GEQ vs qualified LUT finishing",
        )
    else:
        # A LUT refusal is not a jobs-policy refusal. Retain independent GEQ short
        # admission without launching the old codec/filter/compact matrices.
        value = step("single-file-short-geq", {**service, "workload": short}, optional=True)
        short_control = (
            value.get("status") == "SUCCEEDED" and value.get("validation", {}).get("passed") is True
        )
        short_candidate = False
        skipped("single-file-short-lut", "LUT qualification failed; independent GEQ policy remains")
    if short["id"] != "smoke" and short_control:
        medium = {
            "id": "service32",
            "kind": "service32",
            "start": 25.0,
            "duration": 32.0,
            "frames": 1920,
        }
        pair(
            "single-file-jobs32",
            medium,
            {**service, "jobs": 2},
            service,
            "current-code GEQ jobs2 vs jobs1; worker policy contrast, not LUT speedup",
        )
        if lut_ready and short_candidate:
            pair(
                "single-file-lut32",
                medium,
                service,
                {**service, "finish_lut": True},
                "same serial jobs1 service32 GEQ vs qualified LUT finishing",
            )
        else:
            skipped("single-file-lut32", "requires complete matched GEQ/LUT short pairs")
    else:
        skipped("single-file-jobs32", "requires original-input successful GEQ short controls")
        skipped("single-file-lut32", "requires original-input complete matched short pairs")
    if config.get("cuda"):
        with failure_stage("campaign:cuda-combined"):
            from ewp_waveform.application.cuda_combined_experiment import campaign as cuda_campaign

            cuda_campaign({**config, "cuda_combined_service32": True}, workloads, step, skipped)
