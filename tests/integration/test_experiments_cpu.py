"""Real tiny CPU codecs + production service; never a private-input campaign.

Set EWP_EXPERIMENT_TEST_MEDIA to an owned OUTSIDE-GIT media parent. Every test
allocates a unique retained subdirectory. tmp_path holds only text/log evidence.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import uuid
import wave
from pathlib import Path
from typing import Any, cast

import pytest

from ewp_waveform.application import experiments as app


def cli(run: Path, *args: str) -> dict[str, Any]:
    command = [sys.executable, "-m", "ewp_waveform.application.experiments", *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    ident = uuid.uuid4().hex[:8]
    (run / f"cli-{ident}.stdout.txt").write_text(result.stdout)
    (run / f"cli-{ident}.stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_experiments_real_cpu_shared_fixture_service_and_resume(tmp_path: Path) -> None:
    raw_media = os.environ.get("EWP_EXPERIMENT_TEST_MEDIA")
    if not raw_media:
        pytest.skip("explicit outside-Git synthetic media destination required")
    media = Path(raw_media) / ("integration-" + uuid.uuid4().hex)
    media.mkdir(parents=True)
    audio = media / "synthetic.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(i * 2 * math.pi * 220 / 48000)))
                for i in range(9600)
            )
        )
    before = app.sha(audio)
    enabled = ["--enable", "CROP-OUT", "--enable", "PRORES-Q4", "--enable", "ENC-FFV1"]
    pf = cli(tmp_path, "preflight", "--run", str(tmp_path), "--media-root", str(media), *enabled)
    assert pf["adapters"]["CPU-BASE"]["status"] == "READY"
    assert pf["adapters"]["CROP-OUT"]["status"] == "READY"
    assert pf["adapters"]["PRORES-Q4"]["status"] == "READY"
    assert pf["adapters"]["ENC-FFV1"]["status"] == "READY"
    assert all(p["status"] == "SKIP" for p in pf["gpu"].values())
    manifest = {
        "schema_version": 1,
        "design_sha256": app.DESIGN_SHA256,
        "candidates": ["CROP-OUT", "PRORES-Q4"],
        "workloads": [{"id": "SPEECH4", "start": 0.05, "duration": 0.05}],
        "limits": {
            "attempts": 36,
            "seconds": 1800,
            "growth_bytes": 2 * app.GIB,
            "reserve_bytes": 10 * app.GIB,
        },
        "catalog": [],
        "visual_overrides": dict(app.VISUAL),
        "viewing_background": "#081018",
    }
    mpath = tmp_path / "tiny.json"
    app.save_new(mpath, manifest)
    plan = cli(
        tmp_path,
        "prepare",
        "--run",
        str(tmp_path),
        "--media-root",
        str(media),
        "--manifest",
        str(mpath),
        "--audio",
        str(audio),
        "--input-sha256",
        before,
        "--preflight",
        pf["preflight"],
        "--enable",
        "CROP-OUT",
        "--enable",
        "PRORES-Q4",
    )
    assert len(plan["cells"]) == 8
    # Exercise one first, then resume/batch remaining identities without repetition.
    cli(tmp_path, "one", "--run", str(tmp_path), "--cell", plan["cells"][0]["id"])
    result = cli(tmp_path, "batch", "--run", str(tmp_path))
    assert result["cell_count"] == 8
    assert all(c["status"] == "TECHNICAL_PASS" for c in result["cells"])
    assert result["render_fixture_attempts"] == 13  # 4 probes + 1 fixture + 8 cells
    scopes = {c["result"]["scope"] for c in result["cells"]}
    assert len(scopes) == 2 and any("SERVICE" in scope for scope in scopes)
    records = app.Ledger(tmp_path).read()
    assert len([r for r in records if r["event"] == "PAIR_VERIFIED"]) == 4
    finished_ids = [r["cell"] for r in records if r["event"] == "STARTED"]
    assert len(finished_ids) == len(set(finished_ids))
    for c in result["cells"]:
        r = c["result"]
        assert r["validation"]["frames"] == 3
        assert r["validation"]["alpha_min"] == 0
        assert 0 < r["validation"]["alpha_max"] <= 255
        assert r["validation"]["visual_review"] == "PENDING"
        if c["scope"] == "service":
            assert r["service_result"]["analysis"]["encode_workers"] == 1
            assert r["service_result"]["validation"]["passed"]
        if c["variant"] == "CROP-OUT":
            assert r["crop_transform"]["canvas_width"] == 1400
            assert r["crop_transform"]["canvas_height"] == 280
    views = cli(tmp_path, "views", "--run", str(tmp_path))
    assert views["view_attempts"] == 8
    assert views["render_fixture_attempts"] == 13
    assert views["viewing_status"] == "COMPLETE"
    assert {a["role"] for a in views["artifact_index"] if a.get("role")} >= {
        "MASTER",
        "COMPARISON_MOV",
        "COMPOSITED_MP4",
    }
    assert cli(tmp_path, "views", "--run", str(tmp_path))["view_attempts"] == 8
    again = cli(tmp_path, "resume", "--run", str(tmp_path))
    assert again["render_fixture_attempts"] == result["render_fixture_attempts"]
    assert again["speedup"] is None
    assert app.sha(audio) == before
    # A completed altered master is a HOLD, not a hidden retry or fresh sample.
    master = Path(result["cells"][0]["result"]["artifacts"][0]["path"])
    with master.open("ab") as stream:
        stream.write(b"tampered")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ewp_waveform.application.experiments",
            "resume",
            "--run",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2 and "artifact changed" in proc.stderr
    assert len([r for r in app.Ledger(tmp_path).read() if r["event"] == "STARTED"]) == 21
    (tmp_path / "retained-synthetic-media.json").write_text(json.dumps({"media": str(media)}))
