"""Bounded first optimization campaign; no device or performance claims from mocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.portable_experiments_optimize import campaign, direct_render
from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding, service_argv


def argv(path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-i",
        "-",
        "-filter_complex",
        "[0:v]format=rgba[vout]",
        "-map",
        "[vout]",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        str(path),
    ]


def test_encoder_filter_options_are_independent_and_after_input(tmp_path: Path) -> None:
    original = argv(tmp_path / "native.mkv")
    spec = SuiteEncoding("FFV1-DIRECT", tmp_path / "commands.jsonl", encoder_threads=2)
    encoded = service_argv(original, spec)
    assert encoded[encoded.index("-c:v") + 1] == "ffv1"
    assert encoded[encoded.index("-pix_fmt") + 1] == "gray"
    assert encoded.index("-threads:v") > encoded.index("-i")
    assert encoded[encoded.index("-threads:v") + 1] == "2"
    assert "-filter_complex_threads" not in encoded
    assert "prores_ks" not in encoded and "matroska" in encoded
    filtered = service_argv(
        argv(tmp_path / "native.mov"),
        SuiteEncoding("CPU-CONTROL", tmp_path / "filter.jsonl", filter_threads=1),
    )
    assert filtered[filtered.index("-filter_complex_threads") + 1] == "1"
    assert "-threads:v" not in filtered and "-threads" not in filtered
    assert original == argv(tmp_path / "native.mkv")


def test_async_is_bounded_and_preserves_default_one(tmp_path: Path) -> None:
    for depth in (None, 1, 4, 8):
        out = service_argv(
            argv(tmp_path / "native.mov"),
            SuiteEncoding("PRORES-GPU", tmp_path / "gpu.jsonl", async_depth=depth),
        )
        assert out[out.index("-async_depth") + 1] == str(depth or 1)
        assert out[out.index("-c:v") + 1] == "prores_ks_vulkan"
        assert out.index("-async_depth") > out.index("-i")
    for depth in (0, 9, True):
        with pytest.raises(ValueError, match="async_depth"):
            SuiteEncoding("PRORES-GPU", tmp_path / "commands.jsonl", async_depth=depth)
    with pytest.raises(ValueError, match="async_depth"):
        SuiteEncoding("CPU-CONTROL", tmp_path / "commands.jsonl", async_depth=2)
    with pytest.raises(ValueError, match=r"native \.mkv"):
        service_argv(argv(tmp_path / "bad.mov"), SuiteEncoding("FFV1-DIRECT", tmp_path / "x"))


def test_campaign_shortlist_counterbalance_and_singular_variables() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    w = {"id": "speech", "kind": "short", "start": 25.0, "duration": 4.0, "frames": 240}

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        return {"status": "SUCCEEDED", "output": "native.mov", "original_raster_sha256": "raster"}

    def skipped(name: str, reason: str) -> None:
        raise AssertionError((name, reason))

    campaign(
        {
            "repeats": 2,
            "optimization": {"encoder_threads": 2, "filter_threads": 1, "async_depth": 4},
        },
        [w, {**w, "id": "tail"}],
        step,
        skipped,
        {"backends": {"prores": {"status": "PASS"}, "blur": {"status": "FAILED"}}},
    )
    assert calls[0][0] == "opt-stock-service"
    for label in ("opt-direct-ffv1", "opt-ffv1-encoder", "opt-prores-filter", "opt-prores-async"):
        pair = [(n, r) for n, r in calls if n.startswith(label + "-r")]
        assert [r["pair"]["side"] for _, r in pair] == list("ABBA")
    encoder = [r for n, r in calls if n.startswith("opt-ffv1-encoder")]
    assert all(r.get("filter_threads") is None for r in encoder)
    filters = [r for n, r in calls if n.startswith("opt-prores-filter")]
    assert all(r.get("encoder_threads") is None for r in filters)
    assert all(r["codec"] == "prores" for r in filters)
    asyncs = [r for n, r in calls if n.startswith("opt-prores-async")]
    assert [r["async_depth"] for r in asyncs] == [1, 4, 4, 1]
    assert all(r["workload"] == w for _, r in calls)


def test_execute_optimization_does_not_rerun_historical_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        if name == "audio-plan":
            return {"workloads": [{"id": "smoke", "duration": 0.1, "frames": 6}]}
        return {"status": "SUCCEEDED", "output": "native.mkv", "original_raster_sha256": "r"}

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "skip", lambda *args: {"status": "SKIPPED"})
    config = {
        "selected": {"tools": {}},
        "smoke": True,
        "optimize": True,
        "preflight_only": False,
        "optimization": {"encoder_threads": 2, "filter_threads": 1, "async_depth": None},
        "repeats": 2,
    }
    app.execute(config, {})
    assert len([n for n in calls if n.startswith("opt-")]) == 13
    assert not any("qualify" in n or "production32" in n or "fir" in n for n in calls)


def test_optimize_refuses_full_and_unscoped_settings() -> None:
    assert not app.parser().parse_args(["--cpu-smoke"]).optimize
    for flags in (
        ["--optimize", "--full"],
        ["--optimize-filter-threads", "1"],
        ["--resume", "/some/run", "--optimize"],
    ):
        with pytest.raises(SystemExit) as error:
            app.main(["--cpu-smoke", *flags])
        assert error.value.code == 2


def test_direct_duration_refusal_precedes_media_creation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duration <=32s"):
        direct_render({"workload": {"duration": 33}, "media": str(tmp_path / "not-created")})
    assert not (tmp_path / "not-created").exists()


def test_codec_prefix_screen_is_independent_and_bounded() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    w = {"id": "speech", "duration": 4.0, "frames": 240}

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        return {"status": "SUCCEEDED", "output": "native.mov", "original_raster_sha256": "r"}

    skipped = []
    campaign(
        {
            "optimization": {
                "encoder_threads": None,
                "filter_threads": None,
                "ffv1_gpu": True,
                "async_depth": 4,
            }
        },
        [w],
        step,
        lambda n, r: skipped.append(n),
        {
            "backends": {
                "ffv1": {"status": "PASS"},
                "blur": {"status": "FAILED"},
                "prores": {"status": "FAILED"},
            }
        },
    )
    prefix = [r for n, r in calls if n.startswith("opt-ffv1-prefix")]
    assert [r["workload"]["frames"] for r in prefix] == [6, 6, 60, 60]
    assert [r["gpu"] for r in prefix] == [False, True, False, True]
    assert all(r["workload"]["duration"] == r["workload"]["frames"] / 60 for r in prefix)
    assert all(r["codec_prefix"] and r["reference_workload"] == w for r in prefix)
    assert skipped == ["opt-prores-async"]


def test_prefix_timeout_is_supervised_and_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ewp_waveform.application.portable_experiments_state import save

    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    config = {
        "run": str(run),
        "media": str(media),
        "python": "not-executed",
        "audio": {"path": "fixture.wav"},
        "original_path": "",
        "device": "fixture",
        "expected_device": "fixture",
        "visual_overrides": {},
        "limits": {"stage_timeout": 900},
    }
    timeouts = []

    def command(argv: Any, folder: Path, **kwargs: Any) -> dict[str, Any]:
        timeouts.append(kwargs["timeout"])
        save(folder.parent / "value.json", {"status": "FAILED", "error": "fixture timeout"})
        return {
            "returncode": 124,
            "error": "fixture timeout",
            "stderr": "timed out",
            "argv": argv,
            "wall_seconds": 60,
            "shutdown_verified": True,
        }

    monkeypatch.setattr(app, "run_command", command)
    monkeypatch.setattr(app, "check_budget", lambda *args: None)
    for frames in (6, 60):
        result = app.invoke(
            config, f"prefix{frames}", {"operation": "codec", "codec_prefix": True}, optional=True
        )
        assert result["failure_scope"] == "OPTIONAL_SCENARIO"
        assert result["independent_dispatch_allowed"]
    assert timeouts == [60.0, 60.0]
