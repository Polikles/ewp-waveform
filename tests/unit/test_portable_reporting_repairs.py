"""Diagnostic export keeps check semantics, not just verbose log head/tails."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any

from ewp_waveform.application import portable_experiments_reporting as reporting


def qualification() -> dict[str, Any]:
    """Synthetic reporting fixture; these are not measured hardware results."""
    command = {
        "argv": ["selected-ffmpeg", "-filter_threads", "1"],
        "returncode": 0,
        "stderr": "begin\n" + "verbose diagnostic\n" * 40000 + "end\n",
        "stderr_path": "retained/blur.stderr",
    }
    return {
        "status": "FAILED",
        "attempt_failures": ["blur"],
        "failure_scope": "OPTIONAL_SCENARIO",
        "independent_dispatch_allowed": True,
        "backends": {
            "tool_paths": {"ffmpeg": "selected-ffmpeg", "ffprobe": "selected-ffprobe"},
            "tool_sha256": {"ffmpeg": "synthetic-hash"},
            "bounds": {"geometries": [[64, 32], [1400, 280]], "frames_per_case": 2},
            "inventory": {"filters": {"status": "PASS", "stdout": "filter inventory\n" * 5000}},
            "device_diagnostic": {"loader": {"status": "PASS", "devices": []}},
            "qualification_scope": "bounded correctness, not performance or visual acceptance",
            "transfer": {"status": "PASS", "cases": {}},
            "blur": {
                "status": "NUMERICAL_MISMATCH",
                "cases": {
                    "64x32": {
                        "status": "NUMERICAL_MISMATCH",
                        "explanation": "Synthetic finite Gaussian mismatch",
                        "command": command,
                        "numerical_oracle": {
                            "maximum_8bit_code_error": 7.0,
                            "mean_absolute_8bit_code_error": 0.75,
                            "tolerance": {
                                "maximum_8bit_code_error": 2.0,
                                "mean_absolute_8bit_code_error": 0.6,
                                "interpretation": "descriptive screen only",
                            },
                        },
                    },
                    "1400x280": {
                        "status": "PASS",
                        "command": command,
                        "numerical_oracle": {
                            "maximum_8bit_code_error": 0.0,
                            "mean_absolute_8bit_code_error": 0.0,
                            "tolerance": {"maximum_8bit_code_error": 2.0},
                        },
                    },
                },
            },
            "prores": {"status": "PASS"},
            "ffv1": {"status": "PASS"},
            "same_build_control": {"status": "PASS", "explanation": "version/config equal"},
            "cpu_controls": {
                "prores/64x32": {"status": "PASS"},
                "ffv1/1400x280": {"status": "PASS"},
            },
            "commands": [command],
        },
    }


def config(media: Path) -> dict[str, Any]:
    return {
        "python": "selected-python",
        "source": {"sha256": "synthetic-source"},
        "media": str(media),
        "smoke": False,
        "preflight_only": True,
        "production32": False,
        "full": False,
        "cuda": False,
        "repeats": 2,
        "limits": {"stage_timeout": 77.0, "growth_bytes": 123456, "reserve_bytes": 654321},
        "future_preparation_policy": {
            "bounds": {"maximum_wall_seconds": 86.0},
            "accounting": {"scope": ["source-worktree", "all-private-media"], "observed": 5},
            "unrecognized_flag": False,
        },
    }


def test_report_separates_observations_checks_and_case_failure(tmp_path: Path) -> None:
    result = qualification()
    path = reporting.report(
        tmp_path / "run",
        "COMPLETE_WITH_OPTIONAL_FAILURES",
        None,
        config(tmp_path / "media"),
        {"backend-qualification": result},
    )
    text = path.read_text()
    assert "UNKNOWN" not in text
    assert "Observations" in text and "not execution qualification" in text
    assert "tool_paths: **" not in text and "bounds: **" not in text
    assert "inventory: **" not in text and "device_diagnostic: **" not in text
    assert "same_build_control" in text and "cpu_controls/prores/64x32" in text
    assert "64x32" in text and "1400x280" in text
    assert "Synthetic finite Gaussian mismatch" in text
    assert "NUMERICAL_MISMATCH" in text and "maximum_8bit_code_error" in text
    assert "0.75" in text and "0.6" in text
    assert "stage_timeout" in text and "77.0" in text
    assert "production32" in text and "False" in text
    assert "failure_scope=OPTIONAL_SCENARIO" in text
    assert "independent_dispatch_allowed=True" in text
    assert "First concrete command failure" not in text  # Exit 0 can fail an oracle.
    assert path.stat().st_size < 16000


def test_structural_export_survives_huge_embedded_stderr(tmp_path: Path) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    result = qualification()
    original = copy.deepcopy(result)
    settings = config(media)
    report = reporting.report(
        run,
        "COMPLETE_WITH_OPTIONAL_FAILURES",
        None,
        settings,
        {"backend-qualification": result},
    )
    full = json.loads(report.with_suffix(".json").read_text())
    assert full["results"]["backend-qualification"] == original
    assert result == original  # Export never mutates authenticated observations.
    packet = next((run / "reports").glob("diagnostics-*.zip"))
    with zipfile.ZipFile(packet) as archive:
        compact_name = "reports/" + report.stem + "-diagnostics.json"
        compact = json.loads(archive.read(compact_name))
        assert compact["config"]["limits"] == settings["limits"]
        assert compact["config"]["production32"] is False
        assert compact["config"] == settings  # Future policy/accounting is not whitelisted away.
        assert compact["results"]["backend-qualification"]["failure_scope"] == "OPTIONAL_SCENARIO"
        assert compact["results"]["backend-qualification"]["independent_dispatch_allowed"] is True
        backends = compact["results"]["backend-qualification"]["backends"]
        assert backends["bounds"] == original["backends"]["bounds"]
        assert backends["qualification_scope"] == original["backends"]["qualification_scope"]
        assert backends["tool_paths"] == original["backends"]["tool_paths"]
        for key, case in original["backends"]["blur"]["cases"].items():
            saved = backends["blur"]["cases"][key]
            assert saved["status"] == case["status"]
            assert saved["numerical_oracle"] == case["numerical_oracle"]
        stderr = backends["blur"]["cases"]["64x32"]["command"]["stderr"]
        assert len(stderr["excerpt"]) <= 1300
        assert report.with_suffix(".json").as_uri() in stderr["full_evidence"]
        assert "64x32" in stderr["full_evidence"]
        assert "retained/blur.stderr" in report.read_text()
        assert sum(item.file_size for item in archive.infolist()) <= 2 * 1024**2
        for name in archive.namelist():
            if name.endswith(".json"):
                json.loads(archive.read(name))


def test_bundle_compacts_actual_qualification_and_step_json(tmp_path: Path) -> None:
    run, media = tmp_path / "run", tmp_path / "media"
    step = run / "steps/backend-qualification"
    step.mkdir(parents=True)
    qualifier = media / "backend-qualification"
    qualifier.mkdir(parents=True)
    value = qualification()
    (step / "value.json").write_text(json.dumps(value))
    (qualifier / "qualification.json").write_text(json.dumps(value["backends"]))
    (run / "events.jsonl").write_text(json.dumps({"event": "FAILED", "value": value}) + "\n")
    (qualifier / "native.mkv").write_bytes(b"excluded media fixture")
    (media / "unrelated.json").write_text('"must not scan"')
    bundle = reporting.diagnostic_bundle(run, tmp_path / "packet.zip", media=media)
    with zipfile.ZipFile(bundle["path"]) as archive:
        step_value = json.loads(archive.read("steps/backend-qualification/value.compact.json"))
        backend_value = json.loads(archive.read("backend-qualification/qualification.compact.json"))
        assert step_value["attempt_failures"] == ["blur"]
        assert backend_value["blur"]["cases"]["64x32"]["explanation"] == (
            "Synthetic finite Gaussian mismatch"
        )
        events = [json.loads(line) for line in archive.read("events.compact.jsonl").splitlines()]
        assert events[0]["value"]["backends"]["blur"]["status"] == "NUMERICAL_MISMATCH"
        scope = json.loads(archive.read("BUNDLE-SCOPE.json"))
        assert any("structural" in item["reason"] for item in scope["omissions"])
        assert not any("native.mkv" in name or "unrelated" in name for name in archive.namelist())
        assert sum(item.file_size for item in archive.infolist()) == bundle["uncompressed_bytes"]


def test_real_failed_check_explains_itself_without_failed_command(tmp_path: Path) -> None:
    results = {
        "backend-qualification": {
            "status": "FAILED",
            "attempt_failures": ["same_build_control"],
            "backends": {
                "same_build_control": {
                    "status": "EXECUTION_ERROR",
                    "ffmpeg_version_and_configuration": ["synthetic-a", "config"],
                    "ffprobe_version_and_configuration": ["synthetic-b", "config"],
                    "explanation": "Observed version/configuration equality",
                },
                "cpu_controls": {},
            },
        },
    }
    path = reporting.report(tmp_path, "COMPLETE_WITH_OPTIONAL_FAILURES", None, None, results)
    text = path.read_text()
    assert "identities are unavailable or unequal" in text
    assert "same_build_control" in text
    assert "UNKNOWN" not in text


def test_finish_qualification_lists_actual_cases_not_availability(tmp_path: Path) -> None:
    results = {
        "finish-qualify-numpy": {
            "status": "SUCCEEDED",
            "passed": True,
            "scope": "independent FIR oracle",
            "cases": [
                {"case": "zero-mask", "geometry": [64, 32], "max_alpha_error": 0.0},
                {"geometry": [64, 32], "worker": None, "spec": {"width": 64}},
            ],
        },
    }
    path = reporting.report(tmp_path, "COMPLETE", None, None, results)
    text = path.read_text()
    assert "zero-mask" in text and "max_alpha_error" in text
    assert "64x32/zero-mask" in text
    assert "OBSERVED (no per-case verdict)" in text
    assert "finish-qualify-numpy/1" not in text  # Geometry/worker metadata is not another check.
    assert "UNKNOWN" not in text


def test_packet_prioritizes_current_semantics_over_bulk_historical_logs(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    for i in range(80):
        (run / f"old-{i:03d}.txt").write_text("old diagnostics\n" * 3000)
    result = qualification()
    result["failure_scope"] = "GLOBAL_PROCESS_OWNERSHIP"
    result["independent_dispatch_allowed"] = False
    path = reporting.report(run, "FAILED", None, config(tmp_path / "media"), {"qualify": result})
    packet = next((run / "reports").glob("diagnostics-*.zip"))
    with zipfile.ZipFile(packet) as archive:
        compact = json.loads(archive.read("reports/" + path.stem + "-diagnostics.json"))
        assert compact["results"]["qualify"]["failure_scope"] == "GLOBAL_PROCESS_OWNERSHIP"
        assert compact["results"]["qualify"]["independent_dispatch_allowed"] is False
        assert compact["results"]["qualify"]["backends"]["blur"]["status"] == "NUMERICAL_MISMATCH"
        assert sum(item.file_size for item in archive.infolist()) <= 2 * 1024**2
        scope = json.loads(archive.read("BUNDLE-SCOPE.json"))
        assert any(item["reason"] == "2MiB packet cap" for item in scope["omissions"])


def test_structured_partial_log_remains_explicit_text_excerpt(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "events.jsonl").write_text(json.dumps({"stderr": "x" * 60000}) + '\n{"partial":')
    value = reporting.diagnostic_bundle(run, tmp_path / "packet.zip")
    with zipfile.ZipFile(value["path"]) as archive:
        assert "events.jsonl.excerpt.txt" in archive.namelist()
        assert "events.compact.jsonl" not in archive.namelist()
        assert b"DIAGNOSTIC EXCERPT" in archive.read("events.jsonl.excerpt.txt")
