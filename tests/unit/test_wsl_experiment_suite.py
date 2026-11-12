"""No media execution: command topology, validation, identity, lifecycle and admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ewp_waveform.application import experiment_suite as app
from ewp_waveform.application import experiment_suite_state as state
from ewp_waveform.application.experiment_suite_models import GPU, Manifest
from ewp_waveform.application.experiments import save_new
from ewp_waveform.ffmpeg import experiment_suite as ff
from ewp_waveform.ffmpeg.experiment_suite_probes import advertised, invoke
from ewp_waveform.ffmpeg.experiment_suite_validation import check_grid, view_argv
from ewp_waveform.ffmpeg.ribbon import ribbon_graph

ROOT = Path(__file__).resolve().parents[2]


def sample() -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((ROOT / "examples/experiments/wsl-suite.json").read_text())
    )


def argv() -> list[str]:
    return [
        "/selected/ffmpeg",
        "-loglevel",
        "error",
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
        "out.mov",
    ]


def graph(candidate: str | None = None) -> str:
    return ribbon_graph(
        width=1400,
        height=280,
        overscan=50,
        supersample=2,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=16.0,
        finish=(0.45, True, 1, 0.96, 0.55),
        suite_candidate=candidate,
    )


def test_schema_and_complete_example() -> None:
    value = Manifest.model_validate(sample())
    assert {c.scenario for c in value.cells} == set(GPU) | {
        "FULL",
        "PRODUCTION32",
        "A",
        "B",
        "E0",
        "F0",
    }
    for name in ("transfer", "blur", "prores", "ffv1", "build"):
        ids = [c.scenario for c in value.cells if c.pair and c.pair.startswith(name)]
        assert ids[:2] == ids[2:][::-1]  # Predeclared sequential ABBA counterbalance.
    assert value.workload("full").duration is None
    assert value.workload("production32").frames == 1920


@pytest.mark.parametrize("bad", [True, 0, -1, float("inf"), float("nan"), "32"])
def test_finite_resource_limits(bad: Any) -> None:
    m = sample()
    m["limits"]["growth_bytes"] = bad
    with pytest.raises(ValueError):
        Manifest.model_validate(m)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "traversal",
        "unknown",
        "badpair",
        "fullclip",
        "toolong",
        "frames",
        "beyond",
        "extra",
    ],
)
def test_matrix_rejections(mutation: str) -> None:
    m = sample()
    if mutation == "duplicate":
        m["cells"].append(m["cells"][0])
    elif mutation == "traversal":
        m["cells"][0]["id"] = "../escape"
    elif mutation == "unknown":
        m["cells"][0]["scenario"] = "FALLBACK"
    elif mutation == "badpair":
        m["cells"][2]["role"] = "candidate"
    elif mutation == "fullclip":
        m["workloads"][0]["duration"] = 4.0
    elif mutation == "toolong":
        m["workloads"][2]["duration"] = 5.0
    elif mutation == "frames":
        m["workloads"][2]["frames"] = 239
    elif mutation == "beyond":
        m["workloads"][2]["start"] = 395.0
    else:
        m["automatic_retry"] = True
    with pytest.raises(ValueError):
        Manifest.model_validate(m)


def test_tiny_explicit_allowance_no_inherited_two_gib_floor() -> None:
    m = sample()
    m["cells"] = [c for c in m["cells"] if c["scenario"] == "B"][:1]
    m["cells"][0].update(pair=None, role=None)
    m["limits"]["growth_bytes"] = 32 * 1024**2
    for e in m["limits"]["estimates"].values():
        e["growth_bytes"] = 4 * 1024**2
    assert Manifest.model_validate(m).limits.growth_bytes == 32 * 1024**2


def test_default_graph_exact_and_structured_halo() -> None:
    baseline = graph()
    assert baseline == graph("PRORES-GPU") == graph("PRORES-MATCHED")
    assert "[halo]gblur=sigma=16.0:steps=3[blur]" in baseline
    assert (
        graph("TRANSFER").replace(ff.halo_filter(16.0, "TRANSFER"), ff.halo_filter(16.0))
        == baseline
    )
    assert graph("BLUR").replace(ff.halo_filter(16.0, "BLUR"), ff.halo_filter(16.0)) == baseline
    vk = ff.halo_filter(16, "BLUR")
    assert "format=gray,hwupload" in vk and "size=97:sizeV=97:planes=1" in vk
    assert "steps" not in vk and "hwdownload,format=gray" in vk
    with pytest.raises(ValueError):
        ff.halo_filter(8, "BLUR")


@pytest.mark.parametrize("candidate", ff.ADAPTERS)
def test_actual_service_command_transform(candidate: str, tmp_path: Path) -> None:
    spec = ff.SuiteEncoding(candidate, tmp_path / "commands.jsonl")
    source = argv()
    result = ff.service_argv(source, spec)
    assert source == argv()
    assert result[result.index("-i") + 1] == "-"
    graph_value = result[result.index("-filter_complex") + 1]
    if candidate == "PRORES-GPU":
        assert graph_value.endswith("format=yuva444p10le,hwupload[vout]")
        assert result[-result[::-1].index("-pix_fmt")] == "vulkan"
        assert result[result.index("-c:v") + 1] == "prores_ks_vulkan"
        assert "-alpha_bits" in result and "-async_depth" in result
    elif candidate == "PRORES-MATCHED":
        assert graph_value.endswith("format=yuva444p10le[vout]")
        assert "-alpha_bits" in result and "-init_hw_device" not in result
    else:
        assert graph_value == source[source.index("-filter_complex") + 1]
    if spec.gpu:
        assert result.index("-init_hw_device") < result.index("-i")
        assert result[result.index("-loglevel") + 1] == "verbose"


@pytest.mark.parametrize("name", ["FFV1-GPU", "ENC-FFV1", "bogus"])
def test_service_refuses_ffv1_or_unknown(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ff.SuiteEncoding(name, tmp_path / "commands")


def test_ffv1_same_shared_compressed_input_and_frozen_options(tmp_path: Path) -> None:
    common = tmp_path / "shared.mkv"
    cpu, gpu = [
        ff.codec_argv(
            "/p/ffmpeg", common, tmp_path / f"{g}.mkv", gpu=g, device="RTX 3090", frames=240
        )
        for g in (False, True)
    ]
    for value in (cpu, gpu):
        assert value[value.index("-i") + 1] == str(common)
        for key, setting in (
            ("-level", "3"),
            ("-g", "1"),
            ("-coder", "1"),
            ("-context", "0"),
            ("-slices", "4"),
        ):
            assert value[value.index(key) + 1] == setting
    assert "format=bgra,hwupload" in gpu and "vulkan" in gpu
    assert "format=bgra" in cpu and "-init_hw_device" not in cpu


@pytest.mark.parametrize(
    "diagnostic",
    ["", "Using device: llvmpipe RTX 3090", "Using device: RTX 4090", "Available device: RTX 3090"],
)
def test_intended_selected_device_required(diagnostic: str) -> None:
    with pytest.raises(ValueError):
        ff.selected_device(diagnostic, r"RTX\s*3090")
    assert ff.selected_device("Using device: NVIDIA GeForce RTX 3090\n", r"RTX\s*3090")


def test_inventory_not_substring_or_help_claim() -> None:
    assert advertised(" V....D prores_ks_vulkan description", "prores_ks_vulkan")
    assert not advertised(
        " V....D prores_ks description mentions prores_ks_vulkan", "prores_ks_vulkan"
    )


def metadata() -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_name": "prores",
                "profile": "4444",
                "pix_fmt": "yuva444p12le",
                "width": 1400,
                "height": 280,
                "avg_frame_rate": "60/1",
                "time_base": "1/15360",
            }
        ],
        "frames": [{"best_effort_timestamp": str(i * 256)} for i in range(3)],
    }


def test_exact_rational_pts() -> None:
    assert check_grid(metadata(), width=1400, height=280, frames=3)["max_pts_error_seconds"] == "0"
    for key, value in (
        ("codec_name", "h264"),
        ("profile", "HQ"),
        ("pix_fmt", "yuv444p10le"),
        ("width", 1398),
    ):
        m = metadata()
        m["streams"][0][key] = value
        with pytest.raises(ValueError):
            check_grid(m, width=1400, height=280, frames=3)
    for pts in ([0, 256, 256], [256, 512, 768], [0, 512, 256]):
        m = metadata()
        m["frames"] = [{"best_effort_timestamp": str(v)} for v in pts]
        with pytest.raises(ValueError):
            check_grid(m, width=1400, height=280, frames=3)


def test_matroska_nearest_millisecond_grid() -> None:
    m = metadata()
    m["streams"][0].update(codec_name="ffv1", pix_fmt="bgra", time_base="1/1000")
    m["frames"] = [{"best_effort_timestamp": str(i)} for i in [0, 17, 33]]
    assert check_grid(m, width=1400, height=280, frames=3, codec="ffv1")


def test_straight_views_and_finite_checker(tmp_path: Path) -> None:
    for bg in ("#081018", "#F0F0F0", "checker"):
        value = view_argv(
            "ffmpeg",
            tmp_path / "native.mov",
            tmp_path / "view.mp4",
            width=1400,
            height=280,
            frames=240,
            background=bg,
        )
        graph_value = value[value.index("-filter_complex") + 1]
        assert "alpha=straight" in graph_value and "format=yuv420p" in graph_value
        assert value[value.index("-frames:v") + 1] == "240"


def test_command_failure_not_unsupported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ewp_waveform.ffmpeg.experiment_suite_probes.subprocess.run",
        Mock(return_value=Mock(returncode=1, stdout=b"", stderr=b"Option not found")),
    )
    with pytest.raises(RuntimeError, match="not unsupported"):
        invoke(["ffmpeg", "--bad-option"], tmp_path / "commands", "bad")
    assert (tmp_path / "bad.stderr").read_bytes() == b"Option not found"


def test_ledger_partial_failure_mutation_and_no_replay(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    save_new(request, {"operation": "unit"})
    ledger = state.Ledger(tmp_path)
    ledger.append("STARTED", "unit", request=state.artifact(request))
    with pytest.raises(RuntimeError, match="uncertain"):
        state.Ledger(tmp_path)
    output = tmp_path / "output.txt"
    output.write_text("retained failure bytes")
    result = tmp_path / "result.json"
    save_new(
        result,
        {"status": "FAILED", "worker_wall_seconds": 1.0, "artifacts": [state.artifact(output)]},
    )
    ledger.append("FINISHED", "unit", result=state.artifact(result))
    assert state.Ledger(tmp_path).results()["unit"]["status"] == "FAILED"
    output.write_text("changed")
    with pytest.raises(ValueError, match="artifact mutation"):
        state.Ledger(tmp_path)


def test_hash_chain_corruption(tmp_path: Path) -> None:
    request = tmp_path / "r.json"
    save_new(request, {})
    ledger = state.Ledger(tmp_path)
    ledger.append("STARTED", "x", request=state.artifact(request))
    ledger.path.write_text(ledger.path.read_text().replace('"id": "x"', '"id": "y"'))
    with pytest.raises(ValueError, match="hash chain"):
        state.Ledger(tmp_path)


def snapshot() -> dict[str, Any]:
    return {
        "available_memory_bytes": 10**9,
        "cgroups": {"memory.max": "max"},
        "roots": {"/unit": {"device": 1, "free_bytes": 10**9, "tree_bytes": 10}},
    }


def test_resource_admission_exact_small_and_crossings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = {"manifest": sample(), "growth_baseline": {"/unit": 0}}
    s["manifest"]["limits"].update(
        growth_bytes=1024,
        reserve_bytes=100,
        memory_floor_bytes=100,
        seconds=100.0,
        attempt_seconds=10.0,
    )
    estimate = {"growth_bytes": 100, "memory_bytes": 100, "seconds": 1.0}
    monkeypatch.setattr(state, "resources", lambda _: snapshot())
    assert state.check_envelope(s, estimate)["observed_growth_bytes"] == 10
    for kind in ("growth", "reserve", "memory", "time"):
        snap = snapshot()
        if kind == "growth":
            snap["roots"]["/unit"]["tree_bytes"] = 1000
        elif kind == "reserve":
            snap["roots"]["/unit"]["free_bytes"] = 150
        elif kind == "memory":
            snap["cgroups"] = {"memory.max": "150", "memory.current": "100"}
        monkeypatch.setattr(state, "resources", lambda _, value=snap: value)
        with pytest.raises(RuntimeError):
            state.check_envelope(s, estimate, elapsed=11 if kind == "time" else 0)


def test_skip_is_advertised_absence_not_studio(tmp_path: Path) -> None:
    session = {"tools": {"old": None}}
    pre: dict[str, Any] = {
        "runtime": {
            "gpu_status": "PASS",
            "capabilities": {"1400x280": {"ffv1": {"status": "PASS", "studio": "PENDING"}}},
        }
    }
    assert app.capability_skip(session, pre, {"scenario": "F1"}) is None
    assert app.capability_skip(session, pre, {"scenario": "A"}) == "OLD_BUILD_NOT_PROVIDED"
    pre["runtime"]["capabilities"]["1400x280"]["ffv1"]["status"] = "FAILED"
    with pytest.raises(ValueError):
        app.capability_skip(session, pre, {"scenario": "F1"})


def test_stock_full_32_route_no_hook(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from ewp_waveform.application import experiment_suite_render as rendering

    expected = {"preset": {"frozen": True}}
    monkeypatch.setattr(rendering, "effective", lambda *args: expected)
    output = tmp_path / "out.mov"
    output.write_bytes(b"synthetic-file-for-unit-not-media")
    calls = []

    def render(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return [
            {
                "job": {"status": "SUCCEEDED"},
                "analysis": {"encode_workers": 2},
                "validation": {"passed": True},
                "resolved_visual_config": {
                    "effective_preset": expected["preset"],
                    "fixed_axis_recipe": {},
                },
                "outputs": [{"path": str(output)}],
            }
        ]

    monkeypatch.setattr("ewp_waveform.application.service.render", render)
    s = {
        "audio": {"path": "input.wav"},
        "manifest": {"visual_overrides": {}},
        "vm_reference": {
            "effective_visual_config": {
                "effective_preset": expected["preset"],
                "fixed_axis_recipe": {},
            }
        },
    }
    for scenario, start, duration in (("FULL", None, None), ("PRODUCTION32", 25.0, 32.0)):
        root = tmp_path / scenario
        root.mkdir()
        result = rendering.service_cell(
            s,
            {"scenario": scenario},
            {
                "kind": "full" if start is None else "production32",
                "start": start,
                "duration": duration,
            },
            root,
            root,
            expected,
        )
        assert result["route"] == "STOCK_SERVICE"
        assert "experiment" not in calls[-1]
        assert calls[-1]["start"] == start and calls[-1]["duration"] == duration


def test_effective_preset_matches_portable_reference_without_media(tmp_path: Path) -> None:
    from ewp_waveform.application.experiment_suite_render import performance_file
    from ewp_waveform.application.experiments import VISUAL, frozen_configuration
    from ewp_waveform.config.load import load_performance, load_preset
    from ewp_waveform.config.ribbon import apply_public_appearance

    preset = apply_public_appearance(
        load_preset("iuris-ribbon-refined"), **cast(dict[str, Any], VISUAL)
    )
    expected = json.loads((ROOT / "examples/experiments/vm-reference.json").read_text())
    frozen = frozen_configuration(preset, load_performance("balanced"))
    assert frozen["preset"] == expected["effective_visual_config"]["effective_preset"]
    assert frozen["appearance"] == expected["effective_visual_config"]["fixed_axis_recipe"]
    actual = frozen_configuration(preset, load_performance(str(performance_file(tmp_path))))
    assert actual == frozen


def test_export_null_throughput_and_no_new_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    m = Manifest.model_validate(sample()).model_dump(mode="json")
    m["cells"] = [{"id": "cpu", "scenario": "B", "workload": "speech", "pair": None, "role": None}]
    session = {"manifest": m, "source": {}, "tools": {}, "build": None, "device": "RTX3090"}
    monkeypatch.setattr(app, "session_at", lambda _: session)
    monkeypatch.setattr(app, "check_envelope", lambda *a, **k: {})
    request = tmp_path / "request.json"
    save_new(request, {})
    result = tmp_path / "terminal.json"
    save_new(
        result,
        {
            "status": "SUCCEEDED",
            "actual_action": "PROCESS",
            "throughput_fresh": False,
            "worker_wall_seconds": 12.0,
            "wall_seconds": 12.0,
            "validation": {"passed": True},
            "artifacts": [],
        },
    )
    ledger = state.Ledger(tmp_path)
    ledger.append("STARTED", "cpu", request=state.artifact(request))
    ledger.append("FINISHED", "cpu", result=state.artifact(result))
    before = ledger.path.read_bytes()
    exported = app.export_results(tmp_path)
    value = json.loads(Path(exported["json"]).read_text())
    assert value["cells"][0]["wall_seconds"] is None
    assert value["cells"][0]["fps"] is None
    assert value["fresh_measurements_added_by_export"] == 0
    assert ledger.path.read_bytes() == before


def test_attempt_supervisor_timeout_retains_failure_no_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess
    import sys

    real_popen = subprocess.Popen
    launched = []

    def slow(*args: Any, **kwargs: Any) -> Any:
        proc = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        launched.append(proc)
        return proc

    run, media = tmp_path / "run", tmp_path / "media"
    run.mkdir()
    media.mkdir()
    save_new(run / "session.json", {})
    session: dict[str, Any] = {
        "manifest": sample(),
        "media_root": str(media),
        "tools": {"new": {}},
        "growth_baseline": {"/unit": 0},
    }
    session["manifest"]["limits"]["attempt_seconds"] = 0.01
    monkeypatch.setattr("ewp_waveform.application.experiment_suite_state.subprocess.Popen", slow)
    monkeypatch.setattr(state, "resources", lambda _: snapshot())
    # Deterministic resource snapshot applies only to this synthetic timer unit,
    # never to integration/production resource admission.
    session["manifest"]["limits"].update(memory_floor_bytes=1, reserve_bytes=1, growth_bytes=10**9)
    for e in session["manifest"]["limits"]["estimates"].values():
        e.update(memory_bytes=1, growth_bytes=1)
    result = state.execute(run, session, "timeout", {"operation": "unit"}, "short")
    assert result["status"] == "FAILED" and "time" in result["error"]
    assert launched[0].poll() is not None
    again = state.execute(run, session, "timeout", {"operation": "unit"}, "short")
    assert again == result and len(launched) == 1


@pytest.mark.parametrize("background", ["#081018", "#F0F0F0", "checker"])
def test_native_mkv_view_preserves_every_canonical_frame(
    tmp_path: Path, background: str
) -> None:
    command = view_argv(
        "/selected/ffmpeg", tmp_path / "native.mkv", tmp_path / "view.mp4",
        width=1400, height=280, frames=6, background=background,
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:v]settb=1/60,setpts=N" in graph
    assert "alpha=straight" in graph and "shortest=1" in graph
    assert command[command.index("-frames:v") + 1] == "6"
    assert "fps=" not in graph and "select=" not in graph
