"""Focused CPU/CUDA dispatch and strict statistics; simulations are not GPU proof."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.cuda_combined_experiment import (
    COMBINED,
    SerialLUTServiceExperiment,
    TorchServiceExperiment,
    compare_campaign,
)
from ewp_waveform.application.portable_experiments_reporting import pair_statistics


def simulated_campaign(failure: str = "", smoke: bool = False) -> tuple[list[Any], list[str]]:
    calls: list[Any] = []
    skips: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"optional": True, "python": "selected-cuda-python"}
        calls.append((name, request))
        return {
            "status": "FAILED" if failure and failure in name else "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "output": name + ".mov",
            "original_raster_sha256": "shared-raster",
            "finished_rgba_sha256": "cuda-finished",
            "validation": {"passed": True},
        }

    compare_campaign(
        {
            "cuda_python": "selected-cuda-python",
            "repeats": 2,
            "cuda_environment": None if failure == "preparation" else {"verified": True},
        },
        [
            {
                "id": "smoke" if smoke else "speech",
                "kind": "short",
                "start": 25,
                "duration": 4,
                "frames": 240,
            }
        ],
        step,
        lambda name, reason: skips.append(name),
    )
    return calls, skips


def test_focused_exact_eight_renders_abba_same_side_oracles() -> None:
    calls, skips = simulated_campaign()
    assert not skips
    assert [r["operation"] for _, r in calls[:2]] == ["qualify-lut", "qualify-finish"]
    assert calls[1][1] == {"operation": "qualify-finish", "backend": "cuda", **COMBINED}
    renders = calls[2:]
    assert len(renders) == 8
    for group, duration in ((renders[:4], 4), (renders[4:], 32)):
        assert [r["pair"]["side"] for _, r in group] == list("ABBA")
        for _, r in group:
            assert r["operation"] == "service" and r["jobs"] == 1
            assert r["matched_cpu_cuda"] and r["visual_overrides"] == {}
            assert r["workload"]["duration"] == duration
            assert r["finish_lut"] is (r["pair"]["side"] == "A")
            assert r["torch_finish"] is (r["pair"]["side"] == "B")
        assert "reference" not in group[0][1] and "reference" not in group[1][1]
        assert group[2][1]["reference"] == group[1][0] + ".mov"
        assert group[3][1]["reference"] == group[0][0] + ".mov"
        assert all(r["expected_raster_sha256"] == "shared-raster" for _, r in group[1:])
        assert group[2][1]["expected_finished_rgba_sha256"] == "cuda-finished"
        assert all("expected_finished_rgba_sha256" not in group[i][1] for i in (0, 1, 3))
        assert "not isolated kernel speedup" in group[0][1]["pair"]["comparison"]


@pytest.mark.parametrize(
    "failure,side",
    [
        ("cuda-qualification", "A"),
        ("preparation", "A"),
        ("lut-qualification", "B"),
        ("short-r01-B", "A"),
        ("short-r01-A", "B"),
        ("short-r02-B", "A"),
        ("short-r02-A", "B"),
    ],
)
def test_independent_failures_preserve_other_short_side_and_block32(
    failure: str, side: str
) -> None:
    calls, skips = simulated_campaign(failure)
    renders = [(n, r) for n, r in calls if r["operation"] == "service"]
    assert sum(r["pair"]["side"] == side for _, r in renders) == 2
    assert not any("service32-r" in n for n, _ in renders)
    assert "compare-cpu-cuda-service32" in skips


def test_smoke_never_expands_to32() -> None:
    calls, skips = simulated_campaign(smoke=True)
    assert len(calls) == 6 and "compare-cpu-cuda-service32" in skips


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--full"],
        ["--reference-only"],
        ["--optimize"],
        ["--optimize-single-file"],
        ["--cuda-combined"],
        ["--preflight-only"],
        ["--repeats", "4"],
        ["--resume", "/not-opened"],
    ],
)
def test_cli_refuses_conflicting_modes_before_setup(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app.main(["--cpu-smoke", "--compare-cpu-cuda", *([] if not flags else ["--cuda"]), *flags])
    assert exc.value.code == 2


def test_integrated_dispatch_only_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(name)
        if name == "audio-plan":
            return {"workloads": [{"id": "speech", "kind": "short", "duration": 4}]}
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "output": name,
            "original_raster_sha256": "r",
            "finished_rgba_sha256": "f",
            "validation": {"passed": True},
        }

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "make_result_views", lambda results, step: results)
    app.execute(
        {
            "selected": {"tools": {}},
            "smoke": False,
            "compare_cpu_cuda": True,
            "cuda_python": "fixture",
            "cuda_environment": {"verified": True},
            "repeats": 2,
        },
        {},
    )
    assert len(seen) == 11
    assert all(n == "audio-plan" or n.startswith("compare-cpu-cuda-") for n in seen)


@pytest.mark.parametrize("adapter", [SerialLUTServiceExperiment, TorchServiceExperiment])
def test_identical_cache_disabled_hooks(adapter: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("cache access forbidden on either side")

    original = SimpleNamespace(
        load_analysis_cache=forbidden, store_analysis_cache=forbidden, _job_workers=lambda p: 1
    )
    wrapped = (
        adapter().pipeline_hooks(SimpleNamespace(_fixed_hooks=lambda: original))._fixed_hooks()
    )
    assert wrapped.load_analysis_cache("key") is None
    assert wrapped.store_analysis_cache("key", "data") is None
    assert wrapped._job_workers(None) == 1


def test_bootstrap_scheduling_is_stdlib_only() -> None:
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'torch', 'numpy', 'pydantic', 'scipy', 'typer'}:
            raise RuntimeError('optional import reached bootstrap: ' + fullname)
sys.meta_path.insert(0, Block())
from ewp_waveform.application.portable_experiments import parser
from ewp_waveform.application.cuda_combined_experiment import compare_campaign
assert parser().parse_args(['--compare-cpu-cuda', '--cuda']).compare_cpu_cuda
calls=[]
def step(name, req, **kw):
    calls.append(req)
    return {'status':'SUCCEEDED','passed':True,'gpu_qualified':True,'output':name,
            'original_raster_sha256':'r','finished_rgba_sha256':'f','validation':{'passed':True}}
compare_campaign({'repeats':2,'cuda_python':sys.executable,'cuda_environment':{'verified':True}},
                 [{'id':'speech'}],step,
                 lambda *a: None)
assert len([r for r in calls if r['operation']=='service']) == 8
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(app.ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stderr


def report_fixture() -> dict[str, Any]:
    calls, _ = simulated_campaign()
    values = {}
    for name, req in calls[2:6]:
        side, repeat = req["pair"]["side"], req["pair"]["repeat"]
        values[name] = {
            "pair": req["pair"],
            "status": "SUCCEEDED",
            "actual_action": "PROCESS",
            "throughput_fresh": True,
            "wall_seconds": 2.0 if side == "A" else 1.0,
            "timer": "same service.render",
            "route": "MATCHED_SERIAL_CPU_CUDA_SERVICE",
            "workload": req["workload"],
            "execution_settings": {"python": "same", "ffmpeg": "same"},
            "experimental_controls": {
                k: req.get(k)
                for k in (
                    "jobs",
                    "finish_lut",
                    "torch_finish",
                    "backend",
                    "output_mode",
                    "batch_size",
                    "timing_mode",
                    "matched_cpu_cuda",
                )
            },
            "validation": {
                "passed": True,
                "frames": 240,
                "decoded_rgba_sha256": "decoded-" + side,
                "lossless_against_reference_master": repeat == 2,
            },
            "same_side_reference": req.get("reference"),
            "output": name + ".mov",
            "worker_interpreter": {
                "executable": "same",
                "version": "3.12 fixture",
                "prefix": "same",
            },
            "analysis_context": "interval-local",
            "analysis_cache_policy": "disabled identically for matched serial service sides",
            "original_raster_sha256": "r",
            "spec": {"geometry": "same"},
            "effective_preset": {"name": "production"},
            "lut_setup": {"status": "succeeded", "qualification": {"passed": True}},
            "qualification": {"passed": True, "gpu_qualified": True},
            "worker": {"device": "cuda:0", "device_name": "fixture CUDA (simulated)"},
            "finished_rgba_sha256": "finished-" + side,
        }
    return values


def test_report_admits_algorithm_contrast_not_cross_algorithm_identity() -> None:
    stats = pair_statistics(report_fixture())[0]
    assert stats["validated_paired_n"] == 2 and stats["excluded"] == []
    assert stats["speedup"] is None
    assert "combined pipeline contrast" in stats["claim"]


@pytest.mark.parametrize(
    "change", ["python", "cache", "raster", "controls", "decoded", "reference", "qualification"]
)
def test_report_rejects_unmatched_or_unproven_pairs(change: str) -> None:
    values = copy.deepcopy(report_fixture())
    b = values["compare-cpu-cuda-short-r02-B"]
    if change == "python":
        b["execution_settings"]["python"] = "different"
    elif change == "cache":
        b["analysis_cache_policy"] = "enabled"
    elif change == "raster":
        b["original_raster_sha256"] = "different"
    elif change == "controls":
        b["experimental_controls"]["batch_size"] = 1
    elif change == "decoded":
        b["validation"]["decoded_rgba_sha256"] = "different"
    elif change == "reference":
        b["same_side_reference"] = "compare-cpu-cuda-short-r01-A.mov"
    else:
        b["qualification"]["gpu_qualified"] = False
    stats = pair_statistics(values)[0]
    assert stats["validated_paired_n"] == 0 and stats["excluded"]
    assert all(s["n"] == 0 and s["median_seconds"] is None for s in stats["sides"].values())


def test_worker_refuses_unbounded_matched_before_outputs(tmp_path: Path) -> None:
    from ewp_waveform.application.portable_experiments_worker import service_render

    for overrides in (
        {"workload": {"kind": "full", "duration": None}},
        {"workload": {"kind": "service32", "duration": 33}},
        {"visual_overrides": {"color_mode": "auto"}},
        {"jobs": 2},
    ):
        with pytest.raises(ValueError, match="matched CPU/CUDA"):
            service_render(
                {
                    "matched_cpu_cuda": True,
                    "finish_lut": True,
                    "jobs": 1,
                    "visual_overrides": {},
                    "media": str(tmp_path / "absent"),
                    "workload": {"kind": "short", "duration": 4},
                    **overrides,
                }
            )
    assert not (tmp_path / "absent").exists()


def test_report_explains_matched_service_scope_and_worker_interpreter(tmp_path: Path) -> None:
    from ewp_waveform.application.portable_experiments_reporting import report

    path = report(
        tmp_path,
        "COMPLETE",
        None,
        {"compare_cpu_cuda": True, "cuda_python": "same-matched-interpreter"},
        report_fixture(),
    )
    text = path.read_text()
    assert "whole serial-service pipeline contrast" in text
    assert "Matched CPU and CUDA worker Python: `same-matched-interpreter`" in text
    assert "First A and first B are verified standalone" in text
    assert "original-raster hashing overhead is included on both sides" in text
    assert "Stock service versus the custom FIR pipeline also changes wrapper" not in text


@pytest.mark.parametrize("ordinal", (1, 2))
@pytest.mark.parametrize("side", ("A", "B"))
@pytest.mark.parametrize("change", ("failed", "validation", "salvaged", "wall", "qualification"))
def test_report_requires_all_four_eligible_members(ordinal: int, side: str, change: str) -> None:
    values = report_fixture()
    item = values[f"compare-cpu-cuda-short-r{ordinal:02d}-{side}"]
    if change == "failed":
        item.update(status="FAILED", throughput_fresh=False)
    elif change == "validation":
        item["validation"]["passed"] = False
    elif change == "salvaged":
        item["evidence_status"] = "SALVAGED_UNVERIFIED"
    elif change == "wall":
        item["wall_seconds"] = None
    elif side == "A":
        item["lut_setup"]["qualification"]["passed"] = False
    else:
        item["qualification"]["passed"] = False
    stats = pair_statistics(values)[0]
    assert stats["validated_paired_n"] == 0 and stats["excluded"]
    assert all(s["n"] == 0 and s["median_seconds"] is None for s in stats["sides"].values())


@pytest.mark.parametrize(
    "change", ("interpreter", "context", "interpreter-string", "interpreter-field")
)
def test_report_rejects_observed_identity_drift_across_ordinals(change: str) -> None:
    values = report_fixture()
    for name, item in values.items():
        if "r02" not in name:
            continue
        if change == "interpreter":
            item["worker_interpreter"]["executable"] = "another observed Python"
        elif change == "context":
            item["analysis_context"] = "changed observed context"
        elif change == "interpreter-string":
            item["worker_interpreter"] = "not an inventory"
        else:
            item["worker_interpreter"]["version"] = ""
    stats = pair_statistics(values)[0]
    assert stats["validated_paired_n"] == 0 and stats["excluded"]


@pytest.mark.parametrize(
    "field",
    (
        "lut_setup",
        "lut_qualification",
        "qualification",
        "validation",
        "worker",
        "experimental_controls",
        "worker_interpreter",
    ),
)
@pytest.mark.parametrize("malformed", (None, [], "invalid"))
def test_malformed_matched_proofs_preserve_failure_and_report_companions(
    tmp_path: Path, field: str, malformed: Any
) -> None:
    import json

    from ewp_waveform.application.portable_experiments_reporting import report

    values = report_fixture()
    side = "B" if field in ("qualification", "worker") else "A"
    item = values["compare-cpu-cuda-short-r01-" + side]
    if field == "lut_qualification":
        item["lut_setup"]["qualification"] = malformed
    else:
        item[field] = malformed
    original = copy.deepcopy(values)
    path = report(tmp_path, "FAILED", "original worker failure", {"compare_cpu_cuda": True}, values)
    assert path.is_file()
    full = json.loads(path.with_suffix(".json").read_text())
    assert full["error"] == "original worker failure" and full["status"] == "FAILED"
    assert full["results"] == original and values == original
    assert full["pair_statistics"][0]["validated_paired_n"] == 0
    assert full["pair_statistics"][0]["excluded"]
    assert list(path.parent.glob("measurements-*.json"))
    assert path.with_name(path.stem + "-diagnostics.json").is_file()
