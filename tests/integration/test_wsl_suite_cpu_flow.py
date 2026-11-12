"""Parent-owned tiny media integration. Explicit opt-in; never run by author lane.

Uses a fresh manifest with 32MiB growth allowance, not production admission mocks.
Run from a clean committed checkout with EWP_SUITE_MEDIA_TESTS=1; all generated
files belong under pytest's explicit outside-Git --basetemp.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("EWP_SUITE_MEDIA_TESTS") != "1",
    reason="parent-owned media execution requires explicit opt-in",
)
ROOT = Path(__file__).resolve().parents[2]


def test_suite_real_cpu_cli_resume_fixture_views(tmp_path: Path) -> None:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    assert ffmpeg and ffprobe
    # Deliberately selected VM/host CPU build is supplemental, never pinned9.0.2 GPU qualification.
    audio = tmp_path / "tiny.wav"
    with wave.open(str(audio), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframes(
            b"".join(
                struct.pack("<h", int(14000 * math.sin(2 * math.pi * 330 * i / 48000)))
                for i in range(4800)
            )
        )
    manifest = json.loads((ROOT / "examples/experiments/wsl-suite.json").read_text())
    manifest.update(
        input_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),
        source_duration_seconds=0.1,
        workloads=[{"id": "tiny", "kind": "short", "start": 0.0, "duration": 0.1, "frames": 6}],
        cells=[
            {"id": "tiny-B", "scenario": "B", "workload": "tiny"},
            {"id": "tiny-F0", "scenario": "F0", "workload": "tiny"},
        ],
    )
    limits = manifest["limits"]
    limits.update(
        attempts=12,
        seconds=300.0,
        attempt_seconds=120.0,
        growth_bytes=32 * 1024**2,
        reserve_bytes=10 * 1024**3,
        memory_floor_bytes=32 * 1024**2,
    )
    for value in limits["estimates"].values():
        value.update(growth_bytes=4 * 1024**2, memory_bytes=128 * 1024**2, seconds=30.0)
    path = tmp_path / "tiny-manifest.json"
    path.write_text(json.dumps(manifest))
    run, media = tmp_path / "evidence", tmp_path / "media"
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    def cli(*args: str) -> dict[str, Any]:
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts/experiment_suite.py"), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert p.returncode == 0, p.stdout + "\n" + p.stderr
        return cast(dict[str, Any], json.loads(p.stdout))

    cli(
        "prepare",
        "--run",
        str(run),
        "--media-root",
        str(media),
        "--manifest",
        str(path),
        "--audio",
        str(audio),
        "--ffmpeg",
        str(Path(ffmpeg).resolve()),
        "--ffprobe",
        str(Path(ffprobe).resolve()),
        "--source-commit",
        commit,
    )
    session = json.loads((run / "session.json").read_text())
    assert session["build_qualification"] == "CPU_SUPPLEMENTAL_UNPINNED"
    cli("preflight", "--run", str(run))
    assert cli("batch", "--run", str(run))["status"] == "TECHNICAL_COMPLETE"
    before = (run / "ledger.jsonl").read_bytes()
    cli("resume", "--run", str(run))
    assert (run / "ledger.jsonl").read_bytes() == before
    assert cli("views", "--run", str(run))["status"] == "TECHNICAL_COMPLETE"
    exported = cli("export", "--run", str(run))
    data = json.loads(Path(exported["json"]).read_text())
    assert data["fresh_measurements_added_by_export"] == 0
    assert data["visual"] == data["studio"] == "PENDING"
    for cell in data["cells"]:
        assert cell["result"]["validation"]["passed"]
        assert cell["result"]["validation"]["frames"] == 6
    f0 = next(c for c in data["cells"] if c["scenario"] == "F0")
    assert f0["result"]["validation"]["lossless_against_preencode"]
    native = Path(f0["result"]["output"])
    assert native.suffix == ".mkv"
    roles = {a["role"] for r in data["attempts"].values() for a in r.get("artifacts", [])}
    assert {
        "TESTED_NATIVE_MASTER",
        "COMPARISON_PROXY_NOT_NATIVE_FFV1",
        "OPAQUE_VIEW_CHECKER",
    } <= roles
    # Mutation invalidates resume without replay; preserve resulting diagnostics.
    with native.open("ab") as stream:
        stream.write(b"mutation-test")
    failed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/experiment_suite.py"), "resume", "--run", str(run)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert failed.returncode == 2 and "mutation" in failed.stderr
    assert sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file()) < 40 * 1024**2
