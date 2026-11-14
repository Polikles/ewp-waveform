from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import render as render_module
from ewp_waveform.application.service import render
from ewp_waveform.identity import sha256_file
from tests.integration.test_render import NO_CHUNKS, _job_status, _write
from tests.integration.test_ribbon_controls import _preset
from tests.integration.test_ribbon_fixed_profile_render import _output, _signature, _source
from tests.render_oracles import assert_prores_contract, decoded_prores_frames


@pytest.mark.parametrize("lut,path", [(False, "mask_fast"), (True, "rgba_2d")])
def test_actual_service_pipeline_five_frames_exact(tmp_path: Path, lut: bool, path: str) -> None:
    source = tmp_path / "s0e00-Pipeline.wav"
    _source(source)
    before = (sha256_file(source), source.stat().st_mtime_ns)
    preset = _preset(tmp_path)
    base = NO_CHUNKS.replace("[workdirs]", f'[workdirs]\nroot = "{tmp_path / "work"}"')
    if lut:
        base = base.replace("[processing]", "[processing]\nribbon_finish_lut=true")
    profiles = [
        _write(tmp_path / "serial.toml", base),
        _write(
            tmp_path / "prefetch.toml",
            base.replace("[processing]", "[processing]\nribbon_frame_prefetch=true"),
        ),
    ]
    results = []
    for i, profile in enumerate(profiles):
        payload: dict[str, Any] = render(
            source,
            preset_name=str(preset),
            performance_name=str(profile),
            output_dir=tmp_path / f"out-{i}",
            formats=["prores4444"],
            render_path=path,
            render_aa="physical_ss",
            start=0.1,
            duration=0.5,
        )[0]
        assert _job_status(payload) == "SUCCEEDED", payload
        mov = _output(payload, "mov")
        assert_prores_contract(mov, width=160, height=160, fps=10, frame_count=5)
        results.append(payload)
    baseline, pipelined = results
    expected = decoded_prores_frames(_output(baseline, "mov"), width=160, height=160)
    assert len(expected) == 5 and expected[0] != expected[-1]
    assert decoded_prores_frames(_output(pipelined, "mov"), width=160, height=160) == expected
    assert _signature(baseline) == _signature(pipelined)
    assert "ribbon_frame_prefetch" not in baseline["performance"]["extras"]
    assert pipelined["performance"]["extras"]["ribbon_frame_prefetch"]["max_pending_frames"] == 1
    assert (sha256_file(source), source.stat().st_mtime_ns) == before
    assert not any(t.name.startswith("ribbon-frame") for t in threading.enumerate())


@pytest.mark.parametrize("lut", [False, True])
def test_actual_producer_failure_preserves_stderr_and_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lut: bool
) -> None:
    source = tmp_path / "s0e00-PipelineFail.wav"
    _source(source)
    original = render_module.iter_field_frames

    def fail(*args: Any, **kwargs: Any) -> Iterator[bytes]:
        frames = original(*args, **kwargs)
        yield next(frames)
        yield b"\x00"  # Deliberately incomplete raw frame: real FFmpeg stderr on EOF.
        raise RuntimeError("pipeline producer witness")

    monkeypatch.setattr(render_module, "iter_field_frames", fail)
    profile = _write(
        tmp_path / "prefetch.toml",
        NO_CHUNKS.replace(
            "[processing]",
            f"[processing]\nribbon_frame_prefetch=true\nribbon_finish_lut={str(lut).lower()}",
        ).replace("[workdirs]", f'[workdirs]\nroot = "{tmp_path / "work"}"'),
    )
    result: dict[str, Any] = render(
        source,
        preset_name=str(_preset(tmp_path)),
        performance_name=str(profile),
        output_dir=tmp_path / "out",
        formats=["prores4444"],
        duration=0.5,
    )[0]
    assert _job_status(result) == "FAILED", result
    assert "pipeline producer witness" in json.dumps(result)
    if lut:
        diagnostic = result["performance"]["extras"]["ribbon_finish_lut"]
        assert "pipeline producer witness" in diagnostic["error"]
        assert "rawvideo" in diagnostic["stderr"] and diagnostic["temporary_masks_removed"]
        sidecars = list((tmp_path / "work").rglob("*.ribbon-lut.json"))
        assert len(sidecars) == 1 and json.loads(sidecars[0].read_text()) == diagnostic
    else:
        sidecars = list((tmp_path / "work").rglob("ribbon-feed.stderr"))
        assert len(sidecars) == 1 and "rawvideo" in sidecars[0].read_text()
    assert not any(t.name.startswith("ribbon-frame") for t in threading.enumerate())
