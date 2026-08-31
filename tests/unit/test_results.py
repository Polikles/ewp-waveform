import json
from pathlib import Path

from ewp_waveform.application.results import (
    RESULT_REQUIRED_KEYS,
    build_run_summary,
    elapsed_seconds,
    result_payload_errors,
)
from ewp_waveform.paths import project_root


def test_example_result_has_required_keys() -> None:
    path = project_root() / "examples" / "results.example.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert result_payload_errors(payload) == []
    for key in RESULT_REQUIRED_KEYS:
        assert key in payload


def test_missing_job_signature_is_an_error() -> None:
    errors = result_payload_errors(
        {
            "schema_version": 1,
            "tool": {},
            "job": {"job_id": "x", "status": "SUCCEEDED", "seed": 0},
            "renderer": {},
            "project": {},
            "inputs": [{}],
            "resolved_visual_config": {},
            "resolved_performance_config": {},
            "warnings": [],
            "outputs": [],
            "validation": {"passed": True},
            "timestamps": {"started_at": "Z", "completed_at": "Z"},
        }
    )
    assert "missing job.render_signature" in errors


def test_run_summary_counts(tmp_path: Path) -> None:
    results = [
        {"job": {"job_id": "a", "status": "SUCCEEDED"}, "result_json": str(tmp_path / "a.json")},
        {"job": {"job_id": "b", "status": "SKIPPED"}, "result_json": str(tmp_path / "b.json")},
        {"job": {"job_id": "c", "status": "FAILED"}, "result_json": str(tmp_path / "c.json")},
    ]
    summary = build_run_summary(
        results,
        started_at="2026-08-30T00:00:00Z",
        completed_at="2026-08-30T00:00:01Z",
    )
    assert summary["counts"] == {"jobs": 3, "succeeded": 1, "skipped": 1, "failed": 1}
    assert summary["run_id"] == "20260830T000000Z"
    assert summary["timestamps"]["duration_seconds"] == 1.0


def test_elapsed_seconds_parses_zulu() -> None:
    assert elapsed_seconds("2026-08-30T00:00:00Z", "2026-08-30T00:01:30Z") == 90.0
