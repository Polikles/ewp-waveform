"""Full-pair admission/dispatch only: tiny fixtures, not native CUDA evidence."""

from __future__ import annotations

import copy
import os
import shutil
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
    compare_full_campaign,
)
from ewp_waveform.application.portable_experiments_process import ResourceAdmissionError
from ewp_waveform.application.portable_experiments_state import identity, load, save

GIB = 1024**3


def config_fixture() -> dict[str, Any]:
    return {
        "selected": {"tools": {}},
        "smoke": False,
        "compare_cpu_cuda_full": True,
        "compare_cpu_cuda": False,
        "audio": {"sha256": app.DEFAULT_SHA256},
        "cuda_python": "same-selected-worker",
        "cuda_environment": {"verified": True},
        "repeats": 1,
    }


def plan_fixture() -> dict[str, Any]:
    return {
        "status": "SUCCEEDED",
        "source_duration_seconds": 395.6785,
        "workloads": [
            {"id": "full", "kind": "full", "start": None, "duration": None, "frames": 23741}
        ],
    }


def successful(name: str) -> dict[str, Any]:
    return {
        "status": "SUCCEEDED",
        "passed": True,
        "gpu_qualified": True,
        "validation": {"passed": True},
        "original_raster_sha256": "same-raster",
        "output": name + ".mov",
    }


def test_full_exact_two_service_calls_no_short_no_views(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, copy.deepcopy(request), kwargs))
        if name == "audio-plan":
            assert request == {
                "operation": "audio-plan",
                "smoke": False,
                "full_source_confirmation": True,
            }
            return plan_fixture()
        assert kwargs == {"optional": True, "python": "same-selected-worker"}
        return successful(name)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("full mode must not enter shorts, broad campaign or views")

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "make_result_views", forbidden)
    from ewp_waveform.application import cuda_combined_experiment as combined

    monkeypatch.setattr(combined, "compare_campaign", forbidden)
    results = app.execute(config_fixture(), {})
    assert len(results) == len(calls) == 5
    assert [r["operation"] for _, r, _ in calls] == [
        "audio-plan",
        "qualify-lut",
        "qualify-finish",
        "service",
        "service",
    ]
    assert calls[2][1] == {"operation": "qualify-finish", "backend": "cuda", **COMBINED}
    for index, side in ((3, "A"), (4, "B")):
        name, request, _ = calls[index]
        assert name == f"compare-cpu-cuda-full-r01-{side}"
        assert request["pair"]["id"] == "compare-cpu-cuda-full"
        assert request["pair"]["repeat"] == 1 and request["pair"]["order"] == "AB"
        assert request["pair"]["side"] == side
        assert request["workload"] == plan_fixture()["workloads"][0]
        assert request["full_source_confirmation"] is True
        assert request["matched_cpu_cuda"] is True and request["jobs"] == 1
        assert request["visual_overrides"] == {}
        assert request["finish_lut"] is (side == "A")
        assert request["torch_finish"] is (side == "B")
        assert "reference" not in request and "reference_lossless" not in request
        assert "expected_finished_rgba_sha256" not in request
    assert "expected_raster_sha256" not in calls[3][1]
    assert calls[4][1]["expected_raster_sha256"] == "same-raster"


@pytest.mark.parametrize("side", ("A", "B"))
@pytest.mark.parametrize(
    "failure", ({}, {"status": "FAILED"}, {"status": "SUCCEEDED", "passed": False})
)
def test_missing_failed_qualifier_preserves_independent_side(
    side: str, failure: dict[str, Any]
) -> None:
    calls: list[str] = []
    skips: list[str] = []

    def step(name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        if request["operation"] == ("qualify-lut" if side == "A" else "qualify-finish"):
            return failure
        return successful(name)

    compare_full_campaign(config_fixture(), plan_fixture(), step, lambda n, r: skips.append(n))
    assert skips == [f"compare-cpu-cuda-full-r01-{side}"]
    other = "B" if side == "A" else "A"
    assert [n for n in calls if "r01" in n] == [f"compare-cpu-cuda-full-r01-{other}"]


@pytest.mark.parametrize("unavailable", ("preparation", "gpu-proof"))
def test_cuda_without_gpu_qualification_or_preparation_keeps_cpu(unavailable: str) -> None:
    config = config_fixture()
    if unavailable == "preparation":
        config["cuda_environment"] = None
    calls: list[str] = []
    skips: list[str] = []

    def step(name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        value = successful(name)
        if unavailable == "gpu-proof":
            value["gpu_qualified"] = False
        return value

    compare_full_campaign(config, plan_fixture(), step, lambda n, r: skips.append(n))
    assert calls[-1] == "compare-cpu-cuda-full-r01-A"
    assert skips == ["compare-cpu-cuda-full-r01-B"]


@pytest.mark.parametrize("side", ("A", "B"))
def test_failed_service_does_not_replay_or_block_other_side(side: str) -> None:
    calls: list[str] = []

    def step(name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        return {"status": "FAILED"} if name.endswith("r01-" + side) else successful(name)

    compare_full_campaign(config_fixture(), plan_fixture(), step, lambda *a: None)
    assert calls[-2:] == ["compare-cpu-cuda-full-r01-A", "compare-cpu-cuda-full-r01-B"]


@pytest.mark.parametrize(
    "change", ("sha", "duration", "nan", "missing", "status", "smoke", "short", "frames", "clip")
)
def test_full_plan_refusal_before_qualifications(change: str) -> None:
    config, plan = config_fixture(), plan_fixture()
    if change == "sha":
        config["audio"]["sha256"] = "not-original"
    elif change == "duration":
        plan["source_duration_seconds"] = 32
    elif change == "nan":
        plan["source_duration_seconds"] = float("nan")
    elif change == "missing":
        del plan["source_duration_seconds"]
    elif change == "status":
        plan["status"] = "FAILED"
    elif change == "smoke":
        config["smoke"] = True
    elif change == "frames":
        plan["workloads"][0]["frames"] = 1920
    elif change == "clip":
        plan["workloads"][0]["start"] = 25
    else:
        config["compare_cpu_cuda"] = True

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("qualification/render before full-plan admission")

    with pytest.raises(ValueError, match="full-source plan"):
        compare_full_campaign(config, plan, forbidden, forbidden)


FULL_ARGS = ["--audio", "/not-opened.wav", "--cuda", "--compare-cpu-cuda-full"]


@pytest.mark.parametrize(
    "flags",
    (
        [],
        ["--max-growth-gib", "12"],
        ["--reserve-gib", "10"],
        ["--max-growth-gib", "11.99", "--reserve-gib", "10"],
        ["--max-growth-gib", "12", "--reserve-gib", "9.99"],
        ["--max-growth-gib", "nan", "--reserve-gib", "10"],
        ["--max-growth-gib", "12", "--reserve-gib", "inf"],
    ),
)
def test_explicit_full_capacity_required_before_setup(flags: list[str], monkeypatch: Any) -> None:
    monkeypatch.setattr(app, "prerequisite_admission", lambda *a: pytest.fail("setup reached"))
    with pytest.raises(SystemExit) as exc:
        app.main([*FULL_ARGS, *flags])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "flag",
    (
        ["--compare-cpu-cuda"],
        ["--cpu-smoke"],
        ["--full"],
        ["--reference-only"],
        ["--optimize"],
        ["--optimize-single-file"],
        ["--cuda-combined"],
        ["--preflight-only"],
        ["--setup-only"],
        ["--verify-environment", "/absent"],
        ["--inspect-storage"],
        ["--repeats", "2"],
        ["--resume", "/absent"],
    ),
)
def test_full_standalone_cli_refusals(flag: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app.main([*FULL_ARGS, "--max-growth-gib=12", "--reserve-gib=10", *flag])
    assert exc.value.code == 2


def test_full_requires_cuda() -> None:
    with pytest.raises(SystemExit) as exc:
        app.main(
            [arg for arg in FULL_ARGS if arg != "--cuda"]
            + ["--max-growth-gib=12", "--reserve-gib=10"]
        )
    assert exc.value.code == 2


def test_pair_admission_aggregate_same_filesystem(tmp_path: Path, monkeypatch: Any) -> None:
    args = app.parser().parse_args(["--max-growth-gib=12", "--reserve-gib=10"])
    run, media = tmp_path / "evidence", tmp_path / "media"
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=22 * GIB))
    admitted = app.admit_full_cpu_cuda(args, run, media)
    assert admitted["allocations_bytes"] == {
        "control": 3 * GIB,
        "candidate": 3 * GIB,
        "simultaneous_work": 3 * GIB,
        "logs_verification": GIB,
        "headroom": 2 * GIB,
    }
    assert admitted["required_growth_bytes"] == 12 * GIB
    assert admitted["placements"][0]["required_bytes"] == 12 * GIB
    assert "not continuous quota" in admitted["scope"]
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=22 * GIB - 1))
    with pytest.raises(ResourceAdmissionError, match="placement"):
        app.admit_full_cpu_cuda(args, run, media)


def test_pair_admission_split_filesystems(tmp_path: Path, monkeypatch: Any) -> None:
    args = app.parser().parse_args(["--max-growth-gib=12", "--reserve-gib=10"])
    run, media = tmp_path / "evidence", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    real_stat = Path.stat

    def stat(path: Path, *a: Any, **kw: Any) -> Any:
        if path in (run, media):
            return SimpleNamespace(st_dev=1 if path == run else 2)
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(Path, "stat", stat)
    free = {run: 11 * GIB, media: 21 * GIB}
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=free[p]))
    assert len(app.admit_full_cpu_cuda(args, run, media)["placements"]) == 2
    # A large evidence disk must not lend capacity to a full media disk.
    free[run], free[media] = 100 * GIB, 21 * GIB - 1
    with pytest.raises(ResourceAdmissionError, match="placement"):
        app.admit_full_cpu_cuda(args, run, media)
    free[run], free[media] = 11 * GIB - 1, 100 * GIB
    with pytest.raises(ResourceAdmissionError, match="placement"):
        app.admit_full_cpu_cuda(args, run, media)


def test_full_capacity_refused_before_inventory_bootstrap(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(app, "prerequisite_admission", lambda *a: None)
    monkeypatch.setattr(app, "outside_git", lambda *a: None)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=20 * GIB))
    for name in ("original_inventory", "freeze", "select_python", "dependency_policy"):
        monkeypatch.setattr(app, name, lambda *a, **kw: pytest.fail("bootstrap reached"))
    from ewp_waveform.application.portable_experiments_reporting import report

    monkeypatch.setattr(app, "report", report)
    assert (
        app.main(
            [*FULL_ARGS, "--max-growth-gib=12", "--reserve-gib=10", "--output-root", str(tmp_path)]
        )
        == 1
    )
    reports = [
        p
        for p in tmp_path.rglob("report-*.json")
        if not p.stem.endswith(("-commands", "-diagnostics"))
    ]
    import json

    value = json.loads(reports[0].read_text())
    assert value["status"] == "REFUSED_RESOURCE_LIMIT"
    assert value["failure"]["stage"] == "startup:full-pair-admission"


@pytest.mark.parametrize("cls", (TorchServiceExperiment, SerialLUTServiceExperiment))
def test_full_adapter_strict_opt_in_saved_preset_and_encode_guard(cls: Any) -> None:
    from ewp_waveform.config.load import load_preset

    preset = load_preset(str(app.ROOT / "presets/iuris-ribbon-refined-production.toml"))
    job = SimpleNamespace(domain=SimpleNamespace(value="frequency"), fps=60)
    kwargs = {"expected_preset": preset.model_dump(mode="json")}
    cls(**kwargs).validate(job, preset, ["prores4444"], 32)
    with pytest.raises(ValueError):
        cls(**kwargs).validate(job, preset, ["prores4444"], None)
    with pytest.raises(ValueError):
        cls(**kwargs).validate(job, preset, ["prores4444"], 395.6785)
    full = cls(**kwargs, full_source_confirmation=True)
    full.validate(job, preset, ["prores4444"], None)
    with pytest.raises(ValueError):
        full.validate(job, preset, ["prores4444"], 32)
    with pytest.raises(ValueError):
        cls(full_source_confirmation=True).validate(job, preset, ["prores4444"], None)
    with pytest.raises(ValueError, match="strict bool"):
        cls(**kwargs, full_source_confirmation=1).validate(job, preset, ["prores4444"], None)
    geometry = {"n_frames": 23741, "width": 1400, "height": 280, "fps": 60}
    full.validate_full_encode(geometry)
    for key, invalid in (("n_frames", 1920), ("width", 64), ("height", 32), ("fps", 30)):
        with pytest.raises(ValueError, match="23741"):
            full.encode(
                lambda *a, **kw: pytest.fail("encoder reached"),
                iter(()),
                {**geometry, key: invalid},
            )


@pytest.mark.parametrize("target", ("source", "audio", "ffmpeg", "ffprobe"))
@pytest.mark.parametrize("when", ("before-A", "after-A", "before-B"))
def test_full_identity_mutation_stops_dispatch(
    tmp_path: Path, monkeypatch: Any, target: str, when: str
) -> None:
    # Real tiny frozen bytes; a mocked supervised worker does no rendering/CUDA.
    fixtures = {
        name: tmp_path / (name + ".txt") for name in ("source", "audio", "ffmpeg", "ffprobe")
    }
    for name, path in fixtures.items():
        path.write_text("frozen fixture " + name)
    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    monkeypatch.setattr(app, "source_identity", lambda root: identity(fixtures["source"]))
    monkeypatch.setattr(app, "check_budget", lambda *a: {})
    config = {
        **config_fixture(),
        "source": identity(fixtures["source"]),
        "audio": identity(fixtures["audio"]),
        "run": str(run),
        "media": str(media),
        "original_path": "fixture",
        "device": "fixture",
        "expected_device": "fixture",
        "visual_overrides": {},
        "python": sys.executable,
        "selected": {"tools": {n: identity(fixtures[n]) for n in ("ffmpeg", "ffprobe")}},
        "limits": {"stage_timeout": 30},
    }
    worker_starts: list[str] = []

    def mutate() -> None:
        fixtures[target].write_text("changed fixture " + target)

    def run_command(argv: list[str], root: Path, **kwargs: Any) -> dict[str, Any]:
        request = load(Path(argv[-1]))
        worker_starts.append(Path(request["evidence"]).name)
        save(Path(request["result_path"]), successful(worker_starts[-1]))
        if when == "after-A":
            mutate()
        return {
            "returncode": 0,
            "error": None,
            "shutdown_verified": True,
            "argv": argv,
            "wall_seconds": 0.01,
        }

    monkeypatch.setattr(app, "run_command", run_command)

    def step(name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        if request["operation"] != "service":
            return successful(name)
        value = app.invoke(config, name, request, **kwargs)
        proof = value["full_service_identity_verification"]
        assert all(proof[k]["passed"] for k in ("before", "after"))
        assert "outside service and cold" in proof["before"]["scope"]
        assert value["experimental_controls"]["full_source_confirmation"] is True
        if when == "before-B":
            mutate()
        return value

    if when == "before-A":
        mutate()
    with pytest.raises(ValueError, match="changed"):
        compare_full_campaign(config_fixture(), plan_fixture(), step, lambda *a: None)
    assert worker_starts == ([] if when == "before-A" else ["compare-cpu-cuda-full-r01-A"])


def test_full_bootstrap_stdlib_only() -> None:
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'torch','numpy','pydantic','scipy','typer'}:
            raise RuntimeError('nonstdlib bootstrap import: ' + fullname)
sys.meta_path.insert(0, Block())
from ewp_waveform.application.portable_experiments import parser, DEFAULT_SHA256
from ewp_waveform.application.cuda_combined_experiment import compare_full_campaign
assert parser().parse_args(['--compare-cpu-cuda-full','--cuda']).compare_cpu_cuda_full
calls=[]
def step(name, req, **kw):
    calls.append(req)
    return {'status':'SUCCEEDED','passed':True,'gpu_qualified':True,'validation':{'passed':True},
            'original_raster_sha256':'r'}
compare_full_campaign({'compare_cpu_cuda_full':True,'compare_cpu_cuda':False,
                      'audio':{'sha256':DEFAULT_SHA256},'cuda_python':sys.executable,
                      'cuda_environment':{'verified':True}},
                     {'status':'SUCCEEDED','source_duration_seconds':395.6785,
                      'workloads':[{'id':'full','kind':'full','start':None,'duration':None,
                                    'frames':23741}]}, step,
                     lambda *a: None)
assert [r['operation'] for r in calls] == ['qualify-lut','qualify-finish','service','service']
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(app.ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
