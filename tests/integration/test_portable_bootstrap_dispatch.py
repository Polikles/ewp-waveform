"""Actual supervised workers from an empty bootstrap; CPU Torch is never CUDA proof."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_stdlib_bootstrap_supervises_worker_failures_and_real_cpu_torch_service(
    tmp_path: Path,
) -> None:
    selected = os.environ.get("EWP_EXPERIMENT_TEST_TORCH_PYTHON")
    if not selected or not Path(selected).is_file():
        pytest.skip("explicit existing CPU Torch interpreter required; no dependency installation")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required")
    bootstrap = tmp_path / "bootstrap"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(bootstrap)
    python = bootstrap / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    program = r"""
import hashlib, importlib.util, json, os, shutil, struct, sys, wave
from pathlib import Path
assert importlib.util.find_spec("numpy") is None
assert importlib.util.find_spec("torch") is None
src, selected, root = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, str(src / "src"))
from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.cuda_combined_experiment import CONTROL, COMBINED
run, media = root / "run", root / "media"
run.mkdir(); media.mkdir()
audio = root / "synthetic.wav"
with wave.open(str(audio), "wb") as stream:
    stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
    stream.writeframes(b"".join(struct.pack("<h", (i * 137 % 24000) - 12000) for i in range(24000)))
before = hashlib.sha256(audio.read_bytes()).hexdigest()
visual = json.loads((src / "examples/experiments/wsl-suite.json").read_text())["visual_overrides"]
config = dict(run=str(run), media=str(media), original_path=os.environ["PATH"],
              audio={"path":str(audio)}, device="CPU TEST ONLY", expected_device="CPU TEST ONLY",
              visual_overrides={**visual, "glow_level":"none"}, python=sys.argv[4],
              limits=dict(growth_bytes=128*1024**2, reserve_bytes=10*1024**3,
                          memory_floor_bytes=256*1024**2, stage_timeout=120))
# These call the real run_experiments.py --_worker and private process supervisor.
missing = app.invoke(config, "empty-worker", {"operation":"qualify-finish", "backend":"numpy"},
                     optional=True, python=sys.executable)
assert missing["status"] == "FAILED"
assert missing["failure"]["missing_module"] == "numpy"
assert missing["failure"]["interpreter"]["executable"] == sys.executable
assert missing["failure"]["stage"] == "worker:qualify-finish"
assert "import numpy" in missing["failure"]["traceback"]
assert missing["command"]["shutdown_verified"]
failed = app.invoke(config, "bad-operation", {"operation":"deliberately-unknown"}, optional=True)
assert failed["failure"]["exception_type"] == "ValueError"
assert failed["failure"]["interpreter"]["executable"] == sys.argv[4]
assert failed["failure"]["stage"] == "worker:deliberately-unknown"
assert failed["command"]["shutdown_verified"]
results = []
for label, options in (("control", CONTROL), ("combined", COMBINED)):
    q = app.invoke(config, label+"-qualify",
                   {"operation":"qualify-finish", "backend":"torch-cpu", **options},
                   python=selected)
    assert q["status"] == "SUCCEEDED" and q["passed"] and not q["gpu_qualified"]
    request = dict(operation="service", torch_finish=True, backend="torch-cpu", jobs=1,
                   ffmpeg=shutil.which("ffmpeg"), ffprobe=shutil.which("ffprobe"),
                   workload=dict(id="synthetic",kind="short",start=0.1,
                                 duration=5/60,frames=5), **options)
    if results:
        request.update(reference=results[0]["output"],
                       expected_raster_sha256=results[0]["original_raster_sha256"],
                       expected_finished_rgba_sha256=results[0]["finished_rgba_sha256"])
    result = app.invoke(config, label+"-service", request, python=selected)
    assert result["command"]["shutdown_verified"]
    assert result["status"] == "SUCCEEDED" and result["validation"]["passed"]
    assert result["validation"]["frames"] == 5
    assert result["qualification"]["passed"] and not result["qualification"]["gpu_qualified"]
    assert result["service_result"]["analysis"]["encode_workers"] == 1
    assert result["route"] == "EXPLICIT_SERIAL_FIR_SERVICE_EXPERIMENT"
    results.append(result)
assert [r["frames"] for r in results[1]["raster_feed"]["batch_calls"]] == [2,2,1]
for key in ("original_raster_sha256", "finished_rgba_sha256"):
    assert results[0][key] == results[1][key]
assert (results[0]["validation"]["decoded_rgba_sha256"]
        == results[1]["validation"]["decoded_rgba_sha256"])
assert hashlib.sha256(audio.read_bytes()).hexdigest() == before
assert "numpy" not in sys.modules and "torch" not in sys.modules
(root / "supervised-proof.json").write_text(json.dumps(dict(
    scope="CPU Torch; NOT CUDA qualification or 4/32s timing", bootstrap=sys.executable,
    selected=selected, missing=missing, failed=failed, results=results), indent=2))
print("actual supervised worker failures and CPU Torch control/combined services passed")
"""
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-B",
            "-c",
            program,
            str(ROOT),
            selected,
            str(tmp_path),
            sys.executable,
        ],
        env={
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        },
        capture_output=True,
        text=True,
        timeout=300,
    )
    (tmp_path / "bootstrap.stdout").write_text(result.stdout)
    (tmp_path / "bootstrap.stderr").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    proof = json.loads((tmp_path / "supervised-proof.json").read_text())
    assert proof["selected"] == selected
    assert proof["bootstrap"] == str(python)
