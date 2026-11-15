"""Real dependency-empty bootstrap processes; callback results are scheduling simulation."""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.portable_experiments_diagnostics import (
    exception_diagnostic,
    failure_stage,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def stdlib_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("stdlib-bootstrap")
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(root)
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


@pytest.mark.parametrize("scope", ["single-file", "cuda-only", "cuda-short-only"])
def test_empty_bootstrap_dispatches_combined_without_render_imports(
    stdlib_python: Path, scope: str
) -> None:
    # Neither inherited PYTHONPATH nor the test runner's populated site-packages
    # can make this pass accidentally. Block imports as well as observing modules.
    program = r"""
import importlib.abc, importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
assert importlib.util.find_spec("numpy") is None
assert importlib.util.find_spec("torch") is None
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"numpy", "torch", "pydantic", "typer"}:
            raise AssertionError("bootstrap attempted optional import: " + fullname)
sys.meta_path.insert(0, NoOptional())
from ewp_waveform.application import portable_experiments as app
calls = []
def simulated(config, name, request, **kwargs):
    calls.append([name, request, kwargs])
    if name == "audio-plan":
        return {"workloads": [{"id":"speech", "kind":"short", "start":25,
                              "duration":4, "frames":240}]}
    return dict(status="SUCCEEDED", passed=True, gpu_qualified=True,
                validation={"passed":True}, output="SIMULATED.mov",
                original_raster_sha256="r", finished_rgba_sha256="f")
app.invoke = simulated
app.make_result_views = lambda results, step: results
app.skip = lambda *args: {"status":"SKIPPED"}
flags = (["--optimize-single-file", "--cuda"] if sys.argv[2] == "single-file"
         else ["--cuda", "--cuda-combined"])
if sys.argv[2] == "cuda-only":
    flags.append("--cuda-combined-service32")
args = app.parser().parse_args(["--audio", "/not-opened.wav", *flags])
config = dict(selected={"tools":{}}, smoke=False, cuda=args.cuda,
              cuda_environment={"simulation":True}, cuda_python="selected-worker",
              repeats=args.repeats, cuda_combined_service32=args.cuda_combined_service32,
              optimize_single_file=args.optimize_single_file, cuda_combined=args.cuda_combined)
app.execute(config, {})
assert not any(m.split(".")[0] in {"numpy","torch","pydantic","typer"} for m in sys.modules)
print(json.dumps(calls))
"""
    result = subprocess.run(
        [str(stdlib_python), "-I", "-B", "-c", program, str(ROOT / "src"), scope],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)
    cuda = [(name, request, kwargs) for name, request, kwargs in calls if name.startswith("cuda-")]
    assert [n for n, _, _ in cuda[:2]] == [
        "cuda-combined-qualify-control",
        "cuda-combined-qualify-candidate",
    ]
    assert all(kwargs == {"optional": True, "python": "selected-worker"} for _, _, kwargs in cuda)
    durations = (4,) if scope == "cuda-short-only" else (4, 32)
    for duration in durations:
        pair = [r for _, r, _ in cuda[2:] if r["workload"]["duration"] == duration]
        assert [r["pair"]["side"] for r in pair] == list("ABBA")
        assert all(
            r["operation"] == "service" and r["jobs"] == 1 and r["torch_finish"] for r in pair
        )
    assert len(cuda) == 2 + 4 * len(durations)
    if scope != "single-file":
        assert len(calls) == 1 + len(cuda)  # Only audio-plan + CUDA, no CPU/Vulkan matrix.


def test_nested_failure_stage_preserves_type_traceback_and_chained_cause() -> None:
    try:
        with failure_stage("outer"), failure_stage("campaign:cuda-combined"):
            try:
                raise ValueError("original")
            except ValueError as cause:
                raise ModuleNotFoundError("missing numerical closure", name="numpy") from cause
    except ModuleNotFoundError as exc:
        value = exception_diagnostic(exc, stage="fallback")
    assert value["stage"] == "campaign:cuda-combined"
    assert value["exception_type"] == "ModuleNotFoundError"
    assert value["missing_module"] == "numpy"
    assert value["interpreter"]["executable"] == sys.executable
    assert "ValueError: original" in value["traceback"]
    assert "direct cause" in value["traceback"]
    assert value["failing_frame"]["function"] == (
        "test_nested_failure_stage_preserves_type_traceback_and_chained_cause"
    )


def test_main_failure_retains_structured_bootstrap_evidence_in_all_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(args: Any) -> None:
        raise ModuleNotFoundError("bootstrap missing numpy", name="numpy")

    monkeypatch.setattr(app, "prerequisite_admission", refuse)
    assert app.main(["--cpu-smoke", "--output-root", str(tmp_path)]) == 1
    roots = list(tmp_path.glob("refused-*"))
    assert len(roots) == 1
    failure = json.loads((roots[0] / "failure.json").read_text())
    assert failure["stage"] == "startup:prerequisites"
    assert failure["interpreter"]["executable"] == sys.executable
    assert failure["missing_module"] == "numpy"
    assert "in refuse" in failure["traceback"]
    reports = list((roots[0] / "reports").glob("*.json"))
    exports = [p for p in reports if not p.name.endswith("-commands.json")]
    assert len(exports) == 3
    assert all(json.loads(path.read_text())["failure"] == failure for path in exports)
    with zipfile.ZipFile(next((roots[0] / "reports").glob("*.zip"))) as packet:
        for name in packet.namelist():
            if name.startswith("reports/") and name.endswith("-diagnostics.json"):
                assert json.loads(packet.read(name))["failure"] == failure
                break
        else:
            pytest.fail("diagnostic packet omitted structured failure")


@pytest.mark.parametrize("single_file", [True, False])
def test_main_combined_import_failure_records_campaign_not_last_cpu_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, single_file: bool
) -> None:
    real_import = builtins.__import__

    def broken_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "ewp_waveform.application.cuda_combined_experiment":
            raise ModuleNotFoundError("simulated future import regression", name="numpy")
        return real_import(name, *args, **kwargs)

    def freeze(args: Any, run: Path, media: Path, original: Any) -> dict[str, Any]:
        return {
            "run": str(run),
            "media": str(media),
            "selected": {"tools": {}},
            "smoke": False,
            "repeats": 2,
            "limits": {},
            "cuda": True,
            "optimize_single_file": single_file,
            "cuda_combined": not single_file,
        }

    def simulated(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        if name == "audio-plan":
            return {"workloads": [{"id": "speech"}]}
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "validation": {"passed": True},
            "output": "SIMULATED.mov",
            "original_raster_sha256": "r",
        }

    monkeypatch.setattr(app, "prerequisite_admission", lambda args: None)
    monkeypatch.setattr(app, "original_inventory", lambda *args: {})
    monkeypatch.setattr(app, "freeze", freeze)
    monkeypatch.setattr(app, "check_budget", lambda *args: {})
    monkeypatch.setattr(app, "invoke", simulated)
    monkeypatch.setattr(builtins, "__import__", broken_import)
    flags = ["--optimize-single-file"] if single_file else ["--cuda-combined"]
    assert app.main(["--cpu-smoke", "--cuda", *flags, "--output-root", str(tmp_path)]) == 1
    failure = json.loads(next(tmp_path.glob("run-*/failure.json")).read_text())
    assert failure["stage"] == "campaign:cuda-combined"
    assert failure["interpreter"]["executable"] == sys.executable
    assert failure["failing_frame"]["function"] == "broken_import"
    assert "campaign as cuda_campaign" in failure["traceback"]
