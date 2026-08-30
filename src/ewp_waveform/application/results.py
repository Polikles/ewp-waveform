"""Result JSON validation and run-level summaries (docs/07)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ewp_waveform import __version__

RESULT_REQUIRED_KEYS = (
    "schema_version",
    "tool",
    "job",
    "renderer",
    "project",
    "inputs",
    "resolved_visual_config",
    "resolved_performance_config",
    "warnings",
    "outputs",
    "validation",
    "timestamps",
)

JOB_REQUIRED_KEYS = ("job_id", "status", "render_signature", "seed")


def result_payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in RESULT_REQUIRED_KEYS:
        if key not in payload:
            errors.append(f"missing {key}")
    job = payload.get("job")
    if not isinstance(job, dict):
        errors.append("job must be an object")
    else:
        for key in JOB_REQUIRED_KEYS:
            if key not in job:
                errors.append(f"missing job.{key}")
    validation = payload.get("validation")
    if not isinstance(validation, dict) or "passed" not in validation:
        errors.append("validation.passed is required")
    timestamps = payload.get("timestamps")
    if (
        not isinstance(timestamps, dict)
        or "started_at" not in timestamps
        or "completed_at" not in timestamps
    ):
        errors.append("timestamps.started_at and timestamps.completed_at are required")
    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append("inputs must be a non-empty array")
    return errors


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_run_summary(
    results: list[dict[str, Any]],
    *,
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    succeeded = 0
    skipped = 0
    failed = 0
    jobs: list[dict[str, Any]] = []
    for payload in results:
        job = payload.get("job")
        status = "UNKNOWN"
        job_id = None
        if isinstance(job, dict):
            status = str(job.get("status") or "UNKNOWN")
            job_id = job.get("job_id")
        if status == "SUCCEEDED":
            succeeded += 1
        elif status == "SKIPPED":
            skipped += 1
        elif status == "FAILED":
            failed += 1
        jobs.append(
            {
                "job_id": job_id,
                "status": status,
                "result_json": payload.get("result_json"),
            }
        )
    run_id = started_at.replace("-", "").replace(":", "")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "tool": {"name": "ewp-waveform", "version": __version__},
        "counts": {
            "jobs": len(results),
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
        },
        "jobs": jobs,
        "timestamps": {"started_at": started_at, "completed_at": completed_at},
    }


def write_run_summary(summary: dict[str, Any], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return dest
