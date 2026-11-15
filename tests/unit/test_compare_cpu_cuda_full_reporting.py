"""Synthetic reporting contracts only: no native execution or measured performance."""

from __future__ import annotations

import copy
import json
import zipfile
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments_reporting as reporting


def full_fixture(frames: int = 5) -> dict[str, Any]:
    """Match retained worker diagnostics without importing a renderer or Torch."""
    values: dict[str, Any] = {}
    for side in ("A", "B"):
        cuda = side == "B"
        values[side] = {
            "pair": {
                "id": "compare-cpu-cuda-full",
                "repeat": 1,
                "side": side,
                "order": "AB",
                "comparison": "CPU recursive/LUT versus CUDA FIR",
            },
            "status": "SUCCEEDED",
            "actual_action": "PROCESS",
            "throughput_fresh": True,
            "wall_seconds": 2.0 if not cuda else 1.0,
            "cold_process_wall_seconds": 10.0,
            "external_verification_seconds": 0.5,
            "timer": "perf_counter around actual service.render; qualification included",
            "route": "MATCHED_SERIAL_CPU_CUDA_SERVICE",
            "workload": {
                "id": "full",
                "kind": "full",
                "start": None,
                "duration": None,
                "frames": frames,
            },
            "execution_settings": {"python": "same", "ffmpeg": "same", "ffprobe": "same"},
            "experimental_controls": {
                "jobs": 1,
                "finish_lut": not cuda,
                "torch_finish": cuda,
                "backend": "cuda" if cuda else "cpu-lut",
                "matched_cpu_cuda": True,
                "output_mode": "device-rgba" if cuda else None,
                "batch_size": 2 if cuda else None,
                "timing_mode": "ordinary" if cuda else None,
            },
            "validation": {
                "passed": True,
                "frames": frames,
                "silent": True,
                "audio_streams": 0,
                "decoded_rgba_sha256": "decoded-" + side,
                "decoded_alpha_sha256": "alpha-" + side,
                "fps": "60/1",
                "time_base": "1/15360",
                "max_pts_error_seconds": "0",
                "frame_grid_seconds": str(Fraction(frames, 60)),
            },
            "full_source_confirmation": True,
            "full_source_context": {
                "start_seconds": 0.0,
                "duration_seconds": frames / 60,
                "frames": frames,
                "normalization_scope": "complete source",
                "causal_history": "source origin through EOF; no independent intervals",
            },
            "service_result": {
                "analysis": {"encode_workers": 1},
                "normalization": {"mode": "full-source"},
            },
            "same_side_reference": None,
            "output": "absent-synthetic-" + side + ".mov",
            "worker_interpreter": {
                "executable": "same",
                "version": "3.12 fixture",
                "prefix": "same",
            },
            "analysis_context": "full-source",
            "analysis_cache_policy": "disabled identically for matched serial service sides",
            "original_raster_sha256": "same-raster",
            "spec": {"width": 1400, "height": 280, "overscan": 2, "supersample": 2},
            "effective_preset": {"name": "saved-production"},
            "lut_setup": {"status": "succeeded", "qualification": {"passed": True}},
            "qualification": {"passed": True, "gpu_qualified": True},
            "raster_feed": {"frames": frames},
        }
    calls = [
        {
            "ordinal": i,
            "kind": "finish",
            "batch_frames": min(2, frames - 2 * i),
            "batch_capacity": 2,
            "output_mode": "device-rgba",
            "timing_mode": "ordinary",
        }
        for i in range((frames + 1) // 2)
    ]
    values["B"].update(
        finished_rgba_sha256="finished-B",
        worker={
            "device": "cuda:0",
            "device_name": "simulated CUDA, not hardware evidence",
            "output_mode": "device-rgba",
            "batch_size": 2,
            "timing_mode": "ordinary",
            "calls": calls,
        },
    )
    values["B"]["raster_feed"]["batch_calls"] = [
        {"frames": c["batch_frames"], "first_frame": c["ordinal"] * 2, "wall_seconds": 0.01}
        for c in calls
    ]
    count = (frames + 1) // 2
    values["B"]["raster_feed"]["emitted_frames"] = frames
    values["B"]["batch_tail_validation"] = {
        "passed": True,
        "frames": frames,
        "batch_size": 2,
        "batch_count": count,
        "full_batch_count": frames // 2,
        "final_batch_frames": frames - 2 * (count - 1),
        "final_batch_first_frame": 2 * (count - 1),
        "partial_batch_frames": frames % 2,
        "ordering_scope": "all batches in original frame order through EOF",
    }
    return values


def assert_withheld(values: dict[str, Any]) -> None:
    stat = reporting.pair_statistics(values)[0]
    assert stat["validated_paired_n"] == 0 and stat["excluded"]
    assert stat["speedup"] is None
    for side in stat["sides"].values():
        assert side["n"] == 0 and side["total_seconds"] is None
        assert side["median_seconds"] is None


@pytest.mark.parametrize("frames", (4, 5, 23741))
def test_full_n1_admits_complete_pair_and_odd_batch_tail(frames: int) -> None:
    values = full_fixture(frames)
    original = copy.deepcopy(values)
    stat = reporting.pair_statistics(values)[0]
    assert stat["validated_paired_n"] == 1 and not stat["excluded"]
    assert stat["orders"] == ["AB"] and stat["speedup"] is None
    assert stat["execution_order"] == ["A", "B"]
    assert stat["sides"]["A"]["total_seconds"] == 2.0
    assert stat["sides"]["B"]["total_seconds"] == 1.0
    assert all(
        s["n"] == 1
        and s["median_seconds"] is None
        and s["min_seconds"] is None
        and s["max_seconds"] is None
        for s in stat["sides"].values()
    )
    assert "full n1/side" in stat["claim"] and "no medians" in stat["claim"]
    assert values == original


@pytest.mark.parametrize("side", ("A", "B"))
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "FAILED"),
        ("actual_action", "SKIP"),
        ("throughput_fresh", False),
        ("evidence_status", "SALVAGED_UNVERIFIED"),
        ("wall_seconds", True),
        ("wall_seconds", float("nan")),
        ("cold_process_wall_seconds", None),
        ("cold_process_wall_seconds", 1),
        ("external_verification_seconds", 0),
        ("worker_interpreter", None),
        ("analysis_context", "interval-local"),
        ("analysis_cache_policy", "enabled"),
        ("original_raster_sha256", "changed"),
        ("effective_preset", {"name": "changed"}),
        ("spec", {}),
        ("same_side_reference", "short.mov"),
        ("route", "direct-pipeline"),
        ("raster_feed", []),
        ("validation", []),
    ],
)
def test_full_rejects_each_ineligible_member(side: str, field: str, value: Any) -> None:
    values = full_fixture()
    values[side][field] = value
    assert_withheld(values)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("pair", "repeat", 2),
        ("pair", "repeat", True),
        ("pair", "repeat", []),
        ("pair", "order", "BA"),
        ("pair", "comparison", "different"),
        ("workload", "start", 0),
        ("workload", "duration", 32),
        ("workload", "frames", 6),
        ("workload", "kind", "short"),
        ("validation", "passed", False),
        ("validation", "frames", 4),
        ("validation", "decoded_rgba_sha256", None),
        ("validation", "decoded_alpha_sha256", None),
        ("validation", "fps", "30/1"),
        ("validation", "max_pts_error_seconds", "1/60"),
        ("validation", "max_pts_error_seconds", []),
        ("validation", "frame_grid_seconds", "1/60"),
        ("validation", "time_base", "0"),
        ("execution_settings", "ffmpeg", "different"),
        ("execution_settings", "ffprobe", None),
        ("experimental_controls", "batch_size", 1),
        ("experimental_controls", "timing_mode", "diagnostic"),
        ("experimental_controls", "unapproved", True),
        ("qualification", "passed", False),
        ("qualification", "gpu_qualified", False),
        ("worker", "device", "cpu"),
        ("worker", "device_name", ""),
        ("worker", "batch_size", 1),
        ("worker", "calls", []),
        ("raster_feed", "frames", 4),
        ("raster_feed", "batch_calls", None),
    ],
)
def test_full_rejects_changed_context_proofs_or_controls(
    section: str, field: str, value: Any
) -> None:
    values = full_fixture()
    values["B"][section][field] = value
    assert_withheld(values)


@pytest.mark.parametrize("change", ("missing-A", "missing-B", "reversed", "duplicate", "repeat2"))
def test_full_requires_exact_two_members_in_execution_order(change: str) -> None:
    values = full_fixture()
    if change.startswith("missing-"):
        del values[change[-1]]
    elif change == "reversed":
        values = dict(reversed(list(values.items())))
    else:
        values["extra"] = copy.deepcopy(values["A"])
        if change == "repeat2":
            values["extra"]["pair"]["repeat"] = 2
    assert_withheld(values)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("worker", "batch_frames", 2),
        ("worker", "ordinal", 0),
        ("worker", "batch_capacity", 1),
        ("worker", "timing_mode", "diagnostic"),
        ("feed", "frames", 2),
    ],
)
def test_full_partial_final_batch_is_not_rounded_up(section: str, field: str, value: Any) -> None:
    values = full_fixture()
    row = (
        values["B"]["worker"]["calls"][-1]
        if section == "worker"
        else (values["B"]["raster_feed"]["batch_calls"][-1])
    )
    row[field] = value
    assert_withheld(values)


def test_full_cpu_qualification_required_and_no_cross_algorithm_oracle() -> None:
    values = full_fixture()
    values["A"]["lut_setup"]["qualification"]["passed"] = False
    assert_withheld(values)
    values["A"]["lut_setup"] = []
    assert_withheld(values)
    values["A"]["lut_setup"] = {"status": "succeeded", "qualification": {"passed": True}}
    assert reporting.pair_statistics(values)[0]["validated_paired_n"] == 1
    assert (
        values["A"]["validation"]["decoded_rgba_sha256"]
        != (values["B"]["validation"]["decoded_rgba_sha256"])
    )


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("full_source_context", "start_seconds", 1),
        ("full_source_context", "duration_seconds", 395.6785),
        ("full_source_context", "duration_seconds", float("inf")),
        ("full_source_context", "duration_seconds", True),
        ("full_source_context", "frames", 4),
        ("full_source_context", "normalization_scope", "interval"),
        ("full_source_context", "causal_history", "independent intervals"),
        ("service_result", "normalization", {}),
        ("service_result", "normalization", {"mode": "different"}),
        ("service_result", "analysis", []),
        ("validation", "silent", False),
        ("validation", "audio_streams", 1),
        ("validation", "audio_streams", False),
        ("batch_tail_validation", "passed", False),
        ("batch_tail_validation", "frames", 4),
        ("batch_tail_validation", "batch_count", 2),
        ("batch_tail_validation", "full_batch_count", 3),
        ("batch_tail_validation", "final_batch_frames", 2),
        ("batch_tail_validation", "final_batch_first_frame", 3),
        ("batch_tail_validation", "partial_batch_frames", 0),
        ("batch_tail_validation", "ordering_scope", None),
        ("raster_feed", "emitted_frames", 4),
        ("experimental_controls", "torch_finish", 1),
        ("experimental_controls", "jobs", True),
    ],
)
def test_full_requires_explicit_context_silence_and_tail_proof(
    section: str,
    field: str,
    value: Any,
) -> None:
    values = full_fixture()
    values["B"][section][field] = value
    assert_withheld(values)


@pytest.mark.parametrize(
    "field", ("full_source_confirmation", "full_source_context", "batch_tail_validation")
)
def test_full_missing_confirmation_proofs_are_not_inferred(field: str) -> None:
    values = full_fixture()
    del values["B"][field]
    assert_withheld(values)


def test_full_exact_source_duration_and_23741_frame_arithmetic() -> None:
    values = full_fixture(23741)
    for r in values.values():
        r["full_source_context"]["duration_seconds"] = 395.6785
    assert reporting.pair_statistics(values)[0]["validated_paired_n"] == 1
    b = values["B"]
    tail = b["batch_tail_validation"]
    assert tail["batch_count"] == len(b["worker"]["calls"]) == 11871
    assert tail["full_batch_count"] == 11870 and tail["final_batch_frames"] == 1
    assert tail["final_batch_first_frame"] == 23740
    assert sum(c["frames"] for c in b["raster_feed"]["batch_calls"]) == 23741
    b["raster_feed"]["batch_calls"][-1]["first_frame"] -= 1
    assert_withheld(values)


@pytest.mark.parametrize("refuse", (False, True))
def test_full_public_report_exports_intact_records_even_when_packet_refused(
    tmp_path: Path,
    refuse: bool,
) -> None:
    values = full_fixture()
    if refuse:
        # Semantic evidence, not a verbose log that structural compaction may excerpt.
        values["A"]["validation"]["retained_semantic_evidence"] = "x" * (2 * 1024**2)
    original = copy.deepcopy(values)
    config = {
        "compare_cpu_cuda": False,
        "compare_cpu_cuda_full": True,
        "repeats": 2,
        "cuda_python": "same",
        "full": False,
    }
    path = reporting.report(tmp_path, "FAILED", "original unrelated failure", config, values)
    full = json.loads(path.with_suffix(".json").read_text())
    critical_path = next(path.parent.glob("measurements-*.json"))
    critical = json.loads(critical_path.read_text())
    diagnostics = json.loads(path.with_name(path.stem + "-diagnostics.json").read_text())
    for exported in (full, critical, diagnostics):
        assert exported["results"] == original
        assert exported["config"]["compare_cpu_cuda_full"] is True
        assert exported["error"] == "original unrelated failure"
        assert exported["pair_statistics"][0]["validated_paired_n"] == 1
    assert values == original
    assert path.with_name(path.stem + "-commands.json").is_file()
    text = path.read_text()
    assert "Observed execution order: A → B" in text
    assert "| A CPU recursive/LUT | SUCCEEDED | 1 | 2.000 | 10.000 | 0.500 |" in text
    assert "| B CUDA FIR RGBA8 batch2 ordinary | SUCCEEDED | 1 | 1.000 |" in text
    assert "max PTS error=0" in text and "PASS (included)" in text
    assert "No speedup claimed" in text and "whole serial-service pipeline contrast" in text
    assert "not counterbalanced" in text and "no medians, winner, extrapolation" in text
    assert "cold worker envelope" in text and "per-encode independent qualification" in text
    assert "never full" not in text and "A median [range]" not in text
    assert "CUDA batch-tail evidence" in text
    if refuse:
        assert full["packaging"]["status"] == diagnostics["packaging"]["status"] == "REFUSED"
        assert "No usable packet claimed" in text
        assert "critical measurements exceed diagnostic packet cap" in text
    else:
        assert full["packaging"]["status"] == "SUCCEEDED"
        with zipfile.ZipFile(full["packaging"]["path"]) as archive:
            saved = json.loads(archive.read("reports/" + critical_path.name))
            assert saved == critical
            assert sum(i.file_size for i in archive.infolist()) <= 2 * 1024**2


@pytest.mark.parametrize("missing", (False, True))
def test_full_report_withholds_comparison_but_keeps_status_rows(
    tmp_path: Path, missing: bool
) -> None:
    values = full_fixture()
    if missing:
        del values["B"]
    else:
        values["B"].update(status="FAILED", validation=None)
    path = reporting.report(
        tmp_path, "FAILED", "worker failed", {"compare_cpu_cuda_full": True}, values
    )
    text = path.read_text()
    assert "Admission: **WITHHELD**" in text and "Comparison withheld:" in text
    assert "| A CPU recursive/LUT | SUCCEEDED | 0 | withheld |" in text
    assert (
        "| B CUDA FIR RGBA8 batch2 ordinary | MISSING |"
        if missing
        else "| B CUDA FIR RGBA8 batch2 ordinary | FAILED |"
    ) in text
    assert json.loads(path.with_suffix(".json").read_text())["results"] == values
