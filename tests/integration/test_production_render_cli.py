"""Tiny real ordinary-CLI publication, not an original-input/full performance run."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import wave
from array import array
from pathlib import Path

from ewp_waveform.application import production_render as production
from ewp_waveform.application.portable_experiments_state import identity, verify
from ewp_waveform.application.results import result_payload_errors
from tests.render_oracles import assert_prores_contract, decoded_prores_frames


def test_ordinary_production_launcher_publishes_six_frames(tmp_path: Path) -> None:
    source = tmp_path / "s0e00-Ordinary.wav"
    samples = array("h", (round(15000 * math.sin(i * math.tau * 440 / 48000)) for i in range(4800)))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(source), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(samples.tobytes())
    before = identity(source), source.stat().st_mtime_ns
    media = tmp_path / "media"
    evidence = Path(os.environ.get("EWP_PRODUCTION_TEST_EVIDENCE", str(tmp_path / "logs")))
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    assert ffmpeg and ffprobe
    command = [
        sys.executable,
        str(production.DRIVER),
        "--audio",
        str(source),
        "--python",
        sys.executable,
        "--ffmpeg",
        ffmpeg,
        "--ffprobe",
        ffprobe,
        "--output-root",
        str(media),
        "--evidence-root",
        str(evidence),
        "--max-growth-gib",
        "0.0625",
        "--timeout-seconds",
        "90",
    ]
    observed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert observed.returncode == 0, observed.stdout + observed.stderr
    summary = json.loads((evidence / "publication.json").read_text())
    assert summary["source_unchanged"] and summary["lut_qualified"]
    assert summary["encode_workers"] == 1
    payload = json.loads(Path(summary["result_json"]).read_text())
    assert result_payload_errors(payload) == []
    assert payload["job"]["status"] == "SUCCEEDED"
    mov = Path(summary["output"]["path"])
    assert_prores_contract(mov, width=1400, height=280, fps=60, frame_count=6)
    frames = decoded_prores_frames(mov, width=1400, height=280)
    assert len(frames) == 6
    # Decode actual content, not merely an alpha-capable pixel-format label.
    alpha = frames[0][3::4]
    assert min(alpha) == 0 and max(alpha) > 0 and any(0 < a < 255 for a in alpha)
    diagnostic = payload["performance"]["extras"]["ribbon_finish_lut"]
    recipe = payload["resolved_visual_config"]["fixed_axis_recipe"]
    assert recipe["mapping_revision"] == 7
    assert recipe["aa_mode"] == "physical_ss" and recipe["supersample"] == 2
    assert recipe["noise_seed"] == 1729 and recipe["visual_noise"] == 0.35
    assert recipe["reflection_opacity"] == 0.45 and recipe["center_line"] is True
    assert payload["resolved_performance_config"]["ffmpeg_threads"] == 0
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-of", "json", str(mov)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert [stream["codec_type"] for stream in json.loads(probe.stdout)["streams"]] == ["video"]
    assert diagnostic["qualification"]["passed"]
    argv = diagnostic["argv"]
    assert "lut2=" in argv[argv.index("-filter_complex") + 1]
    assert "3000x380" in argv
    assert payload["analysis"]["encode_workers"] == 1
    request = json.loads((evidence / "request.json").read_text())
    assert request["argv"][1:4] == ["-m", "ewp_waveform", "render"]
    assert not {"--full", "--force", "--start", "--duration", "--cuda"}.intersection(
        request["argv"]
    )
    assert (identity(source), source.stat().st_mtime_ns) == before
    assert not list((media / "work").rglob("*.pgm"))
    assert not list((media / "work").rglob("*.mov"))
    assert not (evidence / "failure.json").exists()
    # The exact same explicit roots must refuse and preserve every retained byte.
    held = {
        str(p): identity(p) for root in (media, evidence) for p in root.rglob("*") if p.is_file()
    }
    refused = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    assert refused.returncode == 2 and "already exists" in refused.stderr
    for item in held.values():
        verify(item)
