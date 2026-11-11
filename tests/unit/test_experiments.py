"""Safety/identity tests; no generated media under the evidence namespace."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import experiments as app
from ewp_waveform.ffmpeg import experiments as ff


def example() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "design_sha256": app.DESIGN_SHA256,
        "candidates": ["CROP-OUT", "PRORES-Q4"],
        "workloads": [{"id": "SPEECH4", "start": 25, "duration": 4}],
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
def test_short_manifest_fail_closed(tmp_path: Path, mutation: dict[str, Any]) -> None:
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
def test_budget_cannot_expand(kwargs: dict[str, Any]) -> None:
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
    assert c.record()["horizon_original_y"] == 8.5
    assert c.record()["horizon_output_y"] == 4.5
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


def test_gpu_envelope_refused_before_cpu_or_filesystem_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = tmp_path / "gpu-envelope.json"
    app.save_new(
        envelope, {"target": "WSL_GPU", "adapters": ["GPU-TRANSFER"], "limits": example()["limits"]}
    )
    monkeypatch.setattr(platform, "release", lambda: "Linux-VM-not-WSL")

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("tool discovery/probes must not run on invalid GPU target")

    monkeypatch.setattr(app, "tool_identity", unexpected)
    with pytest.raises(ValueError, match="same-WSL"):
        app.preflight(
            tmp_path / "run", tmp_path / "media", enable=["PRORES-Q4"], gpu_envelope=envelope
        )
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "media").exists()


def test_runtime_timeout_records_consumed_failure_and_kills_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    counter = iter([0.0, 2.0, 2.1])
    monkeypatch.setattr(time, "perf_counter", lambda: next(counter))
    monkeypatch.setattr(app, "available_memory_bytes", lambda: 2 * app.GIB)

    class Process:
        returncode: int | None = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            assert kwargs.get("start_new_session") is True or "creationflags" in kwargs

        def poll(self) -> int | None:
            return self.returncode

    killed: list[Process] = []

    def kill(proc: Process) -> None:
        killed.append(proc)
        proc.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", Process)
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


def test_numpy_metrics_exact_scalar_semantics() -> None:
    import numpy as np

    rng = np.random.default_rng(1729)
    for width, height in ((1, 1), (32, 20), (18, 34)):
        for quiet in (False, True):
            a = bytearray(rng.integers(0, 256, (height, width, 4), dtype=np.uint8).tobytes())
            b = bytearray(rng.integers(0, 256, (height, width, 4), dtype=np.uint8).tobytes())
            if quiet:
                a[3::4] = bytes(width * height)
                b[3::4] = bytes(width * height)
            expected = dict.fromkeys(
                (
                    "union_count",
                    "alpha_error",
                    "rgb_error",
                    "edge_error",
                    "edge_n",
                    "halo_error",
                    "halo_n",
                    "081018",
                    "F0F0F0",
                    "checkerboard",
                ),
                0,
            )
            for p in range(0, len(a), 4):
                aa, ba = a[p + 3], b[p + 3]
                if not (aa or ba):
                    continue
                expected["union_count"] += 1
                delta = abs(aa - ba)
                expected["alpha_error"] += delta
                expected["rgb_error"] += sum(abs(a[p + c] - b[p + c]) for c in range(3))
                if 0 < aa < 255:
                    expected["edge_error"] += delta
                    expected["edge_n"] += 1
                if 0 < aa < 32:
                    expected["halo_error"] += delta
                    expected["halo_n"] += 1
                px = p // 4
                checker = 224 if (px % width // 16 + px // width // 16) % 2 else 48
                for key, bg in (
                    ("081018", (8, 16, 24)),
                    ("F0F0F0", (240, 240, 240)),
                    ("checkerboard", (checker,) * 3),
                ):
                    expected[key] += sum(
                        abs(a[p + c] * aa + bg[c] * (255 - aa) - b[p + c] * ba - bg[c] * (255 - ba))
                        for c in range(3)
                    )
            assert ff.frame_metrics(bytes(a), bytes(b), width, height) == expected


def test_crop_numpy_all_frames_outward_no_media_files() -> None:
    from io import BytesIO
    from typing import cast
    from unittest.mock import Mock

    width, height = 32, 20
    frames = [bytearray(width * height * 4) for _ in range(3)]
    for frame, x, y in ((0, 10, 8), (1, 20, 14), (2, 2, 2)):
        frames[frame][(y * width + x) * 4 + 3] = 1
    raw = Mock()
    raw.open.return_value = BytesIO(b"".join(frames))
    crop = ff.freeze_crop(cast(Path, raw), width=width, height=height, frames=3, margin=1)
    assert (crop.x, crop.y, crop.width, crop.height) == (0, 0, 22, 16)


@pytest.mark.parametrize("height", [16, 17, 280, 281])
def test_anchor_matches_production_pixel_edge_convention(height: int) -> None:
    crop = ff.Crop(0, 2, 16, 12, 16, height)
    assert crop.record()["horizon_original_y"] == height // 2 + 0.5
    assert crop.record()["horizon_output_y"] == height // 2 + 0.5 - 2
    assert crop.record()["reflection_split_row"] == height // 2
    from ewp_waveform.ffmpeg.ribbon import ribbon_graph

    graph = ribbon_graph(
        width=16,
        height=height,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=16,
        finish=(0.45, True, 1.0, 0.96, 0.55),
    )
    row = height // 2
    assert f"between(Y,{row},{row})" in graph
    assert f"min(Y+1,{row + 1}.0)-max(Y,{row}.0)" in graph


def text_session(tmp_path: Path) -> list[dict[str, Any]]:
    cells = [
        {
            "id": name,
            "pair": "PRORES-Q4",
            "workload": "SPEECH4",
            "scope": "codec",
            "variant": variant,
            "skip": None,
        }
        for name, variant in (("a", "CPU-BASE"), ("b", "PRORES-Q4"))
    ]
    app.save_new(tmp_path / "session.json", {"cells": cells})
    app.Ledger(tmp_path).append(
        "PREPARED", "session", session_sha256=app.sha(tmp_path / "session.json")
    )
    return cells


def finish_text(tmp_path: Path, ident: str, *, kind: str = "cell") -> Path:
    commands = tmp_path / (ident + ".commands.jsonl")
    commands.write_text('{"argv":["mock"],"phase":"mock"}\n')
    path = tmp_path / (ident + ".result.json")
    app.save_new(
        path,
        {
            "artifacts": [],
            "commands_path": str(commands),
            "commands_sha256": app.sha(commands),
            "validation": {"passed": True},
        },
    )
    ledger = app.Ledger(tmp_path)
    ledger.append("STARTED", ident, kind=kind)
    ledger.append(
        "FINISHED",
        ident,
        status="TECHNICAL_PASS",
        result_path=str(path),
        result_sha256=app.sha(path),
        result=app.load(path),
    )
    return commands


def test_report_pair_rejection_global_uncertain_and_authentication(tmp_path: Path) -> None:
    cells = text_session(tmp_path)
    finish_text(tmp_path, "a")
    finish_text(tmp_path, "b")
    ledger = app.Ledger(tmp_path)
    ledger.append("PAIR_REJECTED", "a", members=[c["id"] for c in cells], error="drift")
    ledger.append("STARTED", "speech4-fixture", kind="prepare")
    result = app.report(tmp_path)
    assert result["status"] == "HOLD"
    assert all(c["status"] == "HOLD_PAIR_REJECTED" for c in result["cells"])
    assert result["pairs"][0]["status"] == "REJECTED"
    assert any(
        a["id"] == "speech4-fixture" and a["status"] == "HOLD_UNCERTAIN" for a in result["attempts"]
    )
    assert app.main(["report", "--run", str(tmp_path)]) == 2
    (tmp_path / "session.json").write_text('{"cells":[]}')
    with pytest.raises(ValueError, match="frozen session"):
        app.report(tmp_path)


@pytest.mark.parametrize("kind", ["prepare", "cpu-probe", "gpu-probe", "cell", "views"])
def test_all_attempt_command_hashes_authenticated(tmp_path: Path, kind: str) -> None:
    commands = finish_text(tmp_path, "attempt", kind=kind)
    assert app.readback(app.Ledger(tmp_path), "attempt")
    commands.write_text("changed")
    with pytest.raises(ValueError, match="commands changed"):
        app.readback(app.Ledger(tmp_path), "attempt")
    assert app.report(tmp_path)["attempts"][0]["status"] == "HOLD_READBACK_CHANGED"


def test_preset_performance_drift_before_first_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ewp_waveform.application import service
    from ewp_waveform.config.load import load_performance, load_preset

    preset, perf = load_preset("iuris-ribbon-refined"), load_performance("balanced")
    workload = {
        "start": 25,
        "duration": 4,
        "effective_configuration": app.frozen_configuration(preset, perf),
    }
    preset = preset.model_copy(deep=True)
    preset.waveform.amplitude = 0.41
    monkeypatch.setattr(service, "plan_jobs", lambda *a, **kw: (None, preset, perf, [], []))
    with pytest.raises(ValueError, match="drift; replan"):
        app.prepare_fixture(
            {"workload": workload, "media": str(tmp_path / "fixture")},
            {"audio": "unused.wav", "manifest": {"visual_overrides": app.VISUAL}},
        )
    preset.waveform.amplitude = 0.82
    perf.processing["new_unrelated_factor"] = True
    with pytest.raises(ValueError, match="drift; replan"):
        app.assert_frozen(workload, preset, perf)


@pytest.mark.parametrize("crossing", ["time", "growth", "evidence-reserve", "media-reserve"])
@pytest.mark.parametrize("returncode", [0, 1])
def test_already_exited_worker_final_resource_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crossing: str, returncode: int
) -> None:
    from types import SimpleNamespace

    media = tmp_path / "media"
    media.mkdir()
    result = tmp_path / "completed.json"
    app.save_new(result, {"validation": {"passed": True}})
    clock = iter([0.0, 5.0 if crossing == "time" else 0.5])
    monkeypatch.setattr(time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(app, "available_memory_bytes", lambda: 2 * app.GIB)
    launched = False

    class Process:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal launched
            self.returncode = returncode
            launched = True

        def poll(self) -> int:
            return self.returncode

    def disk(path: Path) -> Any:
        low = launched and (
            (crossing == "evidence-reserve" and path == tmp_path)
            or (crossing == "media-reserve" and path == media)
        )
        return SimpleNamespace(free=10 * app.GIB if low else 100 * app.GIB)

    monkeypatch.setattr(subprocess, "Popen", Process)
    monkeypatch.setattr(shutil, "disk_usage", disk)
    monkeypatch.setattr(
        app, "tree_bytes", lambda root: 200 if launched and crossing == "growth" else 0
    )
    result_data = app.bounded_worker(
        tmp_path,
        media,
        {"id": "fast", "result": str(result)},
        app.Limits(seconds=1, growth_bytes=100),
        starting_bytes=0,
    )
    assert (
        result_data["error"]
        == {
            "time": "TIME_LIMIT",
            "growth": "GROWTH_LIMIT",
            "evidence-reserve": "DISK_RESERVE",
            "media-reserve": "DISK_RESERVE",
        }[crossing]
    )
    finish = app.Ledger(tmp_path).read()[-1]
    assert finish["status"] == "FAILED"
    assert finish["limits"]["growth_bytes"] == 100
    assert len(finish["final_resources"]["free_bytes"]) == 2


def test_ffmpeg_failure_preserves_exact_argv_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["explicit-ffmpeg", "-vf", "gblur_vulkan", "test.mkv"]

    def failed(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 17, b"out", b"distinctive unsupported device")

    monkeypatch.setattr(subprocess, "run", failed)
    log = tmp_path / "commands.jsonl"
    with pytest.raises(subprocess.CalledProcessError) as captured:
        ff.run_captured(argv, log, phase="probe")
    assert captured.value.stderr == b"distinctive unsupported device"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert records[-1]["argv"] == argv and records[-1]["returncode"] == 17
    assert records[-1]["stderr"] == "distinctive unsupported device"


@pytest.mark.parametrize("suffix", [".mov", ".mkv"])
def test_viewing_application_reuses_mov_labels_proxy_and_separates_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    master = tmp_path / ("master" + suffix)
    master.write_text("mock media adapter token, not media")
    commands: list[list[str]] = []

    def captured(argv: list[str], log: Path, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(argv)
        Path(argv[-1]).write_text("mock adapter result token, not media")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(ff, "run_captured", captured)
    monkeypatch.setattr(ff, "inspect_master", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(ff, "inspect_view", lambda *args, **kwargs: {"passed": True})
    crop = ff.Crop(0, 12, 16, 8, 16, 32)
    result = app.prepare_views(
        {
            "tested_result": {"artifacts": [app.artifact(master)], "crop_transform": crop.record()},
            "workload_config": {"width": 16, "height": 32, "fps": "60/1", "frames": 4},
            "media": str(tmp_path / "view"),
            "commands": str(tmp_path / "views.commands.jsonl"),
        },
        {
            "tools": {"ffmpeg": {"path": "mock"}, "ffprobe": {"path": "mock-probe"}},
            "manifest": {"viewing_background": "#081018"},
        },
    )
    roles = {a["role"] for a in result["artifacts"]}
    assert roles == {
        "MASTER",
        "COMPOSITED_MP4",
        "COMPARISON_MOV" if suffix == ".mov" else "COMPARISON_MOV_PROXY",
    }
    assert len(commands) == (1 if suffix == ".mov" else 2)
    assert result["proxy_seconds"] == 0 if suffix == ".mov" else result["proxy_seconds"] >= 0
    assert result["view_seconds"] >= 0 and result["verification_and_hash_seconds"] >= 0
    graph = commands[-1][commands[-1].index("-filter_complex") + 1]
    assert "0x081018" in graph and "alpha=straight" in graph and "y=12" in graph
    assert result["throughput_fresh"] is False
    assert app.sha(master) == result["artifacts"][0]["sha256"]


def test_view_attempts_do_not_consume_original_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    media = tmp_path / "media"
    media.mkdir()
    ledger = app.Ledger(tmp_path)
    for i in range(36):
        ledger.append("STARTED", str(i), kind="cell")
        ledger.append("FINISHED", str(i), status="TECHNICAL_PASS", elapsed_seconds=0)
    path = tmp_path / "view-result.json"
    app.save_new(path, {"validation": {"passed": True}})
    monkeypatch.setattr(app, "available_memory_bytes", lambda: 2 * app.GIB)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * app.GIB))

    class Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", Process)
    assert app.bounded_worker(
        tmp_path,
        media,
        {"kind": "views", "id": "a-views", "result": str(path)},
        app.Limits(),
        starting_bytes=0,
    )["validation"]["passed"]
    assert app.report(tmp_path)["render_fixture_attempts"] == 36
    assert app.report(tmp_path)["view_attempts"] == 1
    with pytest.raises(ValueError, match="envelope exhausted"):
        app.bounded_worker(
            tmp_path, media, {"kind": "cell", "id": "37"}, app.Limits(), starting_bytes=0
        )
    for i in range(23):
        ledger.append("STARTED", "v" + str(i), kind="views")
        ledger.append("FINISHED", "v" + str(i), status="TECHNICAL_PASS", elapsed_seconds=0)
    with pytest.raises(ValueError, match="envelope exhausted"):
        app.bounded_worker(
            tmp_path, media, {"kind": "views", "id": "25th-view"}, app.Limits(), starting_bytes=0
        )


def test_explicit_unsupported_probe_skip_not_budget_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "request.json"
    commands = tmp_path / "commands.jsonl"
    commands.write_text("mock diagnostic command evidence\n")
    result = tmp_path / "result.json"
    app.save_new(request, {"kind": "gpu-probe", "result": str(result), "commands": str(commands)})

    def unsupported(path: Path) -> None:
        raise subprocess.CalledProcessError(
            9, ["mock", "-vf", "gblur_vulkan"], b"", b"unsupported device format"
        )

    monkeypatch.setattr(app, "_execute_worker", unsupported)
    app.worker(request)
    skip = app.load(result)
    assert skip["capability_skip"] and skip["returncode"] == 9
    assert skip["stderr"] == "unsupported device format"
    assert skip["commands_sha256"] == app.sha(commands)
