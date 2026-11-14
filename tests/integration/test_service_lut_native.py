from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import render as render_module
from ewp_waveform.application.results import result_payload_errors
from ewp_waveform.application.service import render
from ewp_waveform.ffmpeg import ribbon_lut
from ewp_waveform.identity import sha256_file
from tests.integration.test_render import NO_CHUNKS, _job_status, _write
from tests.integration.test_ribbon_controls import _preset
from tests.integration.test_ribbon_fixed_profile_render import _output, _signature, _source
from tests.render_oracles import assert_prores_contract, decoded_prores_frames


@pytest.mark.parametrize("render_path,line", [("mask_fast", True), ("rgba_2d", False)])
def test_service_serial_and_spawn_lut_exactness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, render_path: str, line: bool
) -> None:
    source = tmp_path / "s0e00-Lut.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    preset = _preset(tmp_path)
    common: dict[str, Any] = dict(
        preset_name=str(preset),
        formats=["prores4444"],
        render_path=render_path,
        render_aa="physical_ss",
        start=0.1,
        duration=0.6,
        center_line=line,
        stroke_width=3,
        center_line_extent=0.73,
        center_line_opacity=0.6,
    )
    work_root = tmp_path / "owned-work"
    base_text = NO_CHUNKS.replace("[workdirs]", f'[workdirs]\nroot = "{work_root}"')
    baseline_profile = _write(tmp_path / "geq.toml", base_text)
    lut_profile = _write(
        tmp_path / "lut.toml",
        base_text.replace("[processing]", "[processing]\nribbon_finish_lut = true"),
    )
    pool_profile = _write(
        tmp_path / "pool.toml", lut_profile.read_text().replace("jobs = 1", "jobs = 2")
    )
    baseline: dict[str, Any] = render(
        source, **common, performance_name=str(baseline_profile), output_dir=tmp_path / "geq"
    )[0]
    serial: dict[str, Any] = render(
        source, **common, performance_name=str(lut_profile), output_dir=tmp_path / "lut"
    )[0]
    # Only test admission changes: the production 1800-frame threshold stays untouched.
    monkeypatch.setattr(render_module, "_FIELD_POOL_MIN_FRAMES", 1)
    pooled: dict[str, Any] = render(
        source, **common, performance_name=str(pool_profile), output_dir=tmp_path / "pool"
    )[0]
    expected = decoded_prores_frames(_output(baseline, "mov"), width=160, height=160)
    assert len(expected) == 6 and expected[0] != expected[-1]
    for payload in (baseline, serial, pooled):
        assert _job_status(payload) == "SUCCEEDED", payload
        assert result_payload_errors(payload) == []
        assert _signature(payload) == _signature(baseline)
        mov = _output(payload, "mov")
        assert_prores_contract(mov, width=160, height=160, fps=10, frame_count=6)
        assert decoded_prores_frames(mov, width=160, height=160) == expected
    assert pooled["analysis"]["encode_workers"] == 2
    assert serial["analysis"]["encode_workers"] == 1
    serial_diag = serial["performance"]["extras"]["ribbon_finish_lut"]
    workers = pooled["performance"]["extras"]["ribbon_finish_lut_workers"]
    assert [(r["first_frame"], r["n_frames"]) for r in workers] == [(0, 3), (3, 3)]
    diagnostics = [serial_diag, *(r["diagnostic"] for r in workers)]
    for diagnostic in diagnostics:
        assert diagnostic["status"] == "succeeded"
        assert diagnostic["qualification"]["passed"] is True
        assert len(diagnostic["qualification"]["cases"]) == 6
        assert diagnostic["temporary_masks_removed"] is True
        assert not Path(diagnostic["prepared"]["mask_path"]).exists()
        assert diagnostic["setup_seconds"] >= diagnostic["qualification_seconds"] > 0
        assert diagnostic["service_encode_seconds_including_setup"] >= diagnostic["setup_seconds"]
        assert "lut2=" in diagnostic["argv"][diagnostic["argv"].index("-filter_complex") + 1]
    assert len({r["prepared"]["mask_path"] for r in diagnostics}) == 3
    assert serial_diag["pid"] == os.getpid()
    assert all(r["diagnostic"]["pid"] != os.getpid() for r in workers)
    assert not list(work_root.rglob("*.pgm"))
    assert not list(work_root.rglob("*.ribbon-lut.json"))
    assert (sha256_file(source), source.stat().st_mtime_ns) == before


def test_failed_service_qualification_retains_failure_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "s0e00-FailLut.wav"
    _source(source)
    # No runtime or feed launch is admitted after a known-false gate.
    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", lambda *args: {"passed": False})
    performance = _write(
        tmp_path / "fail.toml",
        NO_CHUNKS.replace("[processing]", "[processing]\nribbon_finish_lut = true").replace(
            "[workdirs]", f'[workdirs]\nroot = "{tmp_path / "work"}"'
        ),
    )
    payload: dict[str, Any] = render(
        source,
        preset_name=str(_preset(tmp_path)),
        performance_name=str(performance),
        output_dir=tmp_path / "out",
        formats=["prores4444"],
        duration=0.2,
    )[0]
    assert _job_status(payload) == "FAILED"
    record = payload["performance"]["extras"]["ribbon_finish_lut"]
    assert record["status"] == "failed" and record["temporary_masks_removed"]
    assert record["qualification"]["passed"] is False
    assert not list((tmp_path / "out").rglob("*.mov"))
    sidecars = list((tmp_path / "work").rglob("*.ribbon-lut.json"))
    assert len(sidecars) == 1 and json.loads(sidecars[0].read_text()) == record
