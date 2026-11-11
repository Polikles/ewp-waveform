"""Safety/identity tests; no generated media under the evidence namespace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ewp_waveform.application import experiments as app
from ewp_waveform.ffmpeg import experiments as ff


def example() -> dict:
    return {
        "schema_version": 1,
        "design_sha256": "a" * 64,
        "candidates": ["CROP-OUT", "PRORES-Q4"],
        "workloads": [{"id": "SPEECH4", "start": 25, "duration": 4}],
        "limits": {
            "attempts": 36,
            "seconds": 1800,
            "growth_bytes": 2 * app.GIB,
            "reserve_bytes": 10 * app.GIB,
        },
        "catalog": [],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        {"duration": 0},
        {"duration": 32},
        {"duration": True},
        {"duration": float("nan")},
        {"start": -1},
        {"start": "25"},
        {"id": "PRODUCTION32"},
        {"typo": 1},
    ],
)
def test_short_manifest_fail_closed(tmp_path: Path, mutation: dict) -> None:
    data = example()
    data["workloads"][0].update(mutation)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        app.manifest(path)
    assert not (tmp_path / "session.json").exists()


def test_manifest_valid_and_unknown_adapter_refused(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    data = example()
    path.write_text(json.dumps(data))
    assert app.manifest(path)["candidates"] == data["candidates"]
    data["candidates"] = ["GPU-PRORES"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        app.manifest(path)


def test_ledger_detects_corruption_and_partial_writes(tmp_path: Path) -> None:
    ledger = app.Ledger(tmp_path)
    ledger.append("STARTED", "a")
    assert ledger.read()[0]["cell"] == "a"
    with ledger.path.open("a") as stream:
        stream.write('{"partial":')
    with pytest.raises(ValueError):
        ledger.read()


def test_uncertain_start_consumed_never_reexecuted(tmp_path: Path) -> None:
    ledger = app.Ledger(tmp_path)
    ledger.append("STARTED", "uncertain")
    with pytest.raises(ValueError, match="uncertain"):
        app.readback(ledger, "uncertain")
    with pytest.raises(ValueError, match="uncertain"):
        app.bounded_worker(
            tmp_path, tmp_path / "media", {"id": "different"}, app.Limits(), starting_bytes=0
        )
    assert len(ledger.read()) == 1


def test_completed_readback_hashes_and_is_not_throughput(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    artifact = tmp_path / "text-artifact.txt"
    artifact.write_text("retained")
    app.save_new(path, {"artifacts": [app.artifact(artifact)]})
    ledger = app.Ledger(tmp_path)
    ledger.append("STARTED", "done")
    ledger.append(
        "FINISHED",
        "done",
        status="TECHNICAL_PASS",
        result_path=str(path),
        result_sha256=app.sha(path),
    )
    assert app.readback(ledger, "done")
    assert ledger.read()[-1]["throughput_fresh"] is False
    artifact.write_text("changed")
    with pytest.raises(ValueError, match="artifact changed"):
        app.readback(ledger, "done")
    assert len([r for r in ledger.read() if r["event"] == "STARTED"]) == 1


def test_failed_start_remains_hold(tmp_path: Path) -> None:
    ledger = app.Ledger(tmp_path)
    ledger.append("STARTED", "bad")
    ledger.append("FINISHED", "bad", status="FAILED")
    with pytest.raises(ValueError, match="failed consumed"):
        app.readback(ledger, "bad")


def test_exclusive_lock_retention(tmp_path: Path) -> None:
    ledger = app.Ledger(tmp_path)
    with ledger.locked(), pytest.raises(FileExistsError), ledger.locked():
        pass
    assert not (tmp_path / "active.lock").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": 37},
        {"seconds": 1801},
        {"growth_bytes": 3 * app.GIB},
        {"reserve_bytes": 9 * app.GIB},
    ],
)
def test_budget_cannot_expand(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        app.Limits(**kwargs)


def test_exact_argv_and_config_allowlists() -> None:
    crop = ff.Crop(0, 2, 16, 12, 16, 16)
    base = ff.codec_argv(
        "/encoder",
        Path("same.rgba"),
        Path("a.mov"),
        width=16,
        height=16,
        fps="60/1",
        candidate="CPU-BASE",
        crop=crop,
    )
    for candidate in ("CROP-OUT", "PRORES-Q4", "ENC-FFV1"):
        argv = ff.codec_argv(
            "/encoder",
            Path("same.rgba"),
            Path("b.mov"),
            width=16,
            height=16,
            fps="60/1",
            candidate=candidate,
            crop=crop,
        )
        ff.check_command_diff(base, argv, candidate)
        settings = ff.codec_settings(candidate, crop)
        ff.check_effective_diff(ff.codec_settings("CPU-BASE", crop), settings, candidate)
        argv.insert(-1, "-unrelated-option")
        with pytest.raises(ValueError):
            ff.check_command_diff(base, argv, candidate)
        settings["unrelated_factor"] = 1
        with pytest.raises(ValueError):
            ff.check_effective_diff(ff.codec_settings("CPU-BASE", crop), settings, candidate)


def test_crop_after_finish_original_geometry() -> None:
    original = [
        "ffmpeg",
        "-i",
        "-",
        "-filter_complex",
        "[0:v]scale=16:16,gblur=sigma=4,crop=16:16:8:8[vout]",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "a.mov",
    ]
    c = ff.Crop(0, 4, 16, 8, 16, 16)
    out = ff.experiment_argv(original, ff.EncodeExperiment("CROP-OUT", c))
    assert (
        "gblur=sigma=4,crop=16:16:8:8,crop=16:8:0:4:exact=1[vout]"
        in out[out.index("-filter_complex") + 1]
    )
    assert c.record()["horizon_original_y"] == 7.5
    assert c.record()["horizon_output_y"] == 3.5
    assert original[-1] == out[-1]


def test_gpu_recipes_are_not_cpu_fallbacks() -> None:
    for name in ff.GPU_ADAPTERS:
        argv = ff.gpu_probe_argv("ffmpeg", name, Path("outside.mkv"))
        assert "-init_hw_device" in argv and "vulkan=vk" in argv
        assert "hwupload" in argv[argv.index("-vf") + 1]
    with pytest.raises(ValueError):
        ff.EncodeExperiment("GPU-PRORES")


def test_no_simultaneous_png_opt_in(tmp_path: Path) -> None:
    from ewp_waveform.ffmpeg.encode import encode_rgba_stream

    with pytest.raises(ValueError, match="never simultaneous PNG"):
        encode_rgba_stream(
            [],
            width=16,
            height=16,
            fps=60,
            glow=0,
            png_dir=tmp_path / "png",
            prores_path=tmp_path / "a.mov",
            experiment=ff.EncodeExperiment("PRORES-Q4"),
        )
    assert list(tmp_path.iterdir()) == []


def test_generated_paths_never_in_git_or_evidence(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="outside Git"):
        app.validate_roots(tmp_path / "run", tmp_path / "media")
    with pytest.raises(ValueError, match="disjoint"):
        app.validate_roots(tmp_path, tmp_path / "media")


def test_gpu_envelope_refused_before_cpu_or_filesystem_effects(tmp_path: Path, monkeypatch) -> None:
    envelope = tmp_path / "gpu-envelope.json"
    app.save_new(
        envelope, {"target": "WSL_GPU", "adapters": ["GPU-TRANSFER"], "limits": example()["limits"]}
    )
    monkeypatch.setattr(app.platform, "release", lambda: "Linux-VM-not-WSL")

    def unexpected(*args, **kwargs):
        pytest.fail("tool discovery/probes must not run on invalid GPU target")

    monkeypatch.setattr(app, "tool_identity", unexpected)
    with pytest.raises(ValueError, match="same-WSL"):
        app.preflight(
            tmp_path / "run", tmp_path / "media", enable=["PRORES-Q4"], gpu_envelope=envelope
        )
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "media").exists()


def test_runtime_timeout_records_consumed_failure_and_kills_tree(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    counter = iter([0.0, 2.0, 2.1])
    monkeypatch.setattr(app.time, "perf_counter", lambda: next(counter))
    monkeypatch.setattr(app, "available_memory_bytes", lambda: 2 * app.GIB)

    class Process:
        returncode = None

        def __init__(self, *args, **kwargs):
            assert kwargs.get("start_new_session") is True or "creationflags" in kwargs

        def poll(self):
            return self.returncode

    killed = []

    def kill(proc):
        killed.append(proc)
        proc.returncode = -9

    monkeypatch.setattr(app.subprocess, "Popen", Process)
    monkeypatch.setattr(app, "stop_tree", kill)
    result = app.bounded_worker(
        tmp_path,
        media,
        {"id": "timeout", "result": str(tmp_path / "missing-result.json")},
        app.Limits(seconds=1),
        starting_bytes=0,
    )
    assert result["error"] == "TIME_LIMIT" and len(killed) == 1
    records = app.Ledger(tmp_path).read()
    assert records[-1]["event"] == "FINISHED" and records[-1]["status"] == "FAILED"
    with pytest.raises(ValueError, match="consumed"):
        app.bounded_worker(tmp_path, media, {"id": "timeout"}, app.Limits(), starting_bytes=0)


def test_worker_replay_refused_without_admitted_parent(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    app.save_new(request, {"launcher_pid": -1})
    with pytest.raises(ValueError, match="admitted live parent"):
        app.worker(request)


def test_process_tree_kill_real_child(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    if os.name != "posix":
        pytest.skip("POSIX process-tree behavior; Windows path requires target validation")
    with (tmp_path / "child.stdout.txt").open("wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=out,
            stderr=out,
            start_new_session=True,
        )
        app.stop_tree(proc)
    assert proc.poll() is not None and proc.returncode < 0
