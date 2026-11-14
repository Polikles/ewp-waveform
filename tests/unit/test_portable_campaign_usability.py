"""Counterbalanced pairing, optional admission, compact evidence and view aliases."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application import portable_experiments_reporting as reporting
from ewp_waveform.application import portable_experiments_worker as worker


def configuration() -> dict[str, Any]:
    return {
        "selected": {"tools": {}},
        "installed": None,
        "smoke": False,
        "preflight_only": False,
        "production32": False,
        "full": False,
        "cuda": False,
        "cuda_environment": None,
        "repeats": 2,
    }


def test_repeat_defaults_and_invalid_or_resume_overrides() -> None:
    args = app.parser().parse_args([])
    assert args.repeats == 2 and args.reserve_gib == 10
    for tokens in (
        ["--cpu-smoke", "--repeats=1"],
        ["--cpu-smoke", "--repeats=3"],
        ["--resume=x", "--repeats=4"],
    ):
        with pytest.raises(SystemExit) as caught:
            app.main(tokens)
        assert caught.value.code == 2


def test_numpy_independent_and_only_shortlist_is_repeated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    workloads: list[dict[str, Any]] = [
        {"id": name, "kind": "short", "start": 0.0, "duration": 0.1, "frames": 6}
        for name in ("speech", "onset", "quiet", "tail")
    ]

    def fake(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request, kwargs))
        if name == "audio-plan":
            return {"status": "SUCCEEDED", "workloads": workloads}
        if request["operation"] == "qualify-finish":
            assert request["backend"] == "numpy"
            assert kwargs.get("python") is None
            return {"status": "SUCCEEDED", "passed": True}
        return {"status": "SUCCEEDED", "output": "native.mov"}

    monkeypatch.setattr(app, "invoke", fake)
    monkeypatch.setattr(app, "skip", lambda *a: {"status": "SKIPPED"})
    app.execute(configuration(), {})
    pair_calls = [(name, request) for name, request, _ in calls if request.get("pair")]
    assert [name for name, _ in pair_calls] == [
        "speech-fir-algorithm-r01-A",
        "speech-fir-algorithm-r01-B",
        "speech-fir-algorithm-r02-B",
        "speech-fir-algorithm-r02-A",
        "onset-fir-screen-r01-A",
        "onset-fir-screen-r01-B",
        "quiet-fir-screen-r01-A",
        "quiet-fir-screen-r01-B",
        "tail-fir-screen-r01-A",
        "tail-fir-screen-r01-B",
    ]
    assert [r["backend"] for _, r in pair_calls[:4]] == ["ffmpeg", "numpy", "numpy", "ffmpeg"]
    assert all(request["pair"]["repeat"] == 1 for _, request in pair_calls[4:])
    assert all(
        sum(name == w["id"] + "-cpu-selected" for name, _, _ in calls) == 1 for w in workloads
    )


def test_failed_cuda_qualification_isolated_from_cpu_torch_and_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {
        **configuration(),
        "cuda": True,
        "cuda_environment": {},
        "cuda_python": "torch-python",
    }
    config["cuda_environment"] = {"observed": True}
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def fake(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request, kwargs))
        if name == "audio-plan":
            return {"status": "SUCCEEDED", "workloads": [{"id": "speech"}]}
        if request["operation"] == "qualify-finish":
            return {
                "status": "FAILED" if request["backend"] == "cuda" else "SUCCEEDED",
                "passed": request["backend"] != "cuda",
            }
        return {"status": "SUCCEEDED", "output": "native.mov"}

    monkeypatch.setattr(app, "invoke", fake)
    monkeypatch.setattr(app, "skip", lambda *a: {"status": "SKIPPED"})
    app.execute(config, {})
    timed = [(name, r, k) for name, r, k in calls if r.get("pair")]
    assert not any(r.get("backend") == "cuda" for _, r, _ in timed)
    assert any(r.get("backend") == "numpy" and k.get("python") is None for _, r, k in timed)
    optional = [
        (name, r, k) for name, r, k in timed if "torch-cpu" in name or "transfer-cuda" in name
    ]
    assert optional and all(k["python"] == "torch-python" for _, _, k in optional)


def test_compute_free_transfer_gate_never_calls_finishing(monkeypatch: pytest.MonkeyPatch) -> None:
    from ewp_waveform.ffmpeg import torch_finish

    class Transfer:
        cuda = True  # Explicit admission-control stand-in, not hardware execution.

        def __init__(self, spec: Any, device: str, **kwargs: Any):
            self.calls = 0

        def transfer(self, mask: Any) -> Any:
            self.calls += 1
            return mask.copy()

        def finish_alpha(self, *a: Any) -> None:
            pytest.fail("transfer-only gate must never run compute")

        def evidence(self) -> dict[str, Any]:
            return {"device_name": "NVIDIA GeForce RTX 3090", "calls": self.calls}

    monkeypatch.setattr(torch_finish, "TorchFinisher", Transfer)
    value = worker.qualify_finish({"backend": "transfer-cuda", "expected_device": r"RTX\s*3090"})
    assert value["transfer_qualified"] and value["selected_device_match"]
    assert value["gpu_qualified"] is False
    with pytest.raises(ValueError, match="selected device mismatch"):
        worker.check_cuda_device(value, "RTX 4090")


def pair_result(side: str, ordinal: int, wall: float) -> dict[str, Any]:
    return {
        "pair": {
            "id": "fir",
            "repeat": ordinal,
            "side": side,
            "order": "AB" if ordinal == 1 else "BA",
            "comparison": "algorithm contrast",
        },
        "status": "SUCCEEDED",
        "actual_action": "PROCESS",
        "throughput_fresh": True,
        "wall_seconds": wall,
        "timer": "pipeline",
        "route": "CUSTOM",
        "workload": {"start": 0, "frames": 6},
        "execution_settings": {"python": "same"},
        "original_raster_sha256": "same",
        "spec": {"width": 1400},
        "effective_preset": {"noise": 0.35},
        "validation": {"passed": True, "frames": 6},
    }


def test_statistics_require_matched_validated_same_raster() -> None:
    results = {
        f"{r}{s}": pair_result(s, r, wall)
        for r, aw, bw in ((1, 2.0, 4.0), (2, 3.0, 5.0))
        for s, wall in (("A", aw), ("B", bw))
    }
    value = reporting.pair_statistics(results)[0]
    assert value["orders"] == ["AB", "BA"] and value["validated_paired_n"] == 2
    assert value["sides"]["A"] == {
        "n": 2,
        "median_seconds": 2.5,
        "min_seconds": 2.0,
        "max_seconds": 3.0,
    }
    assert value["speedup"] is None
    changed = copy.deepcopy(results)
    changed["1B"]["original_raster_sha256"] = "different"
    changed["2B"]["status"] = "FAILED"
    excluded = reporting.pair_statistics(changed)[0]
    assert excluded["validated_paired_n"] == 0 and len(excluded["excluded"]) == 2
    assert excluded["speedup"] is None


def test_main_report_is_compact_and_exact_commands_are_in_appendix(tmp_path: Path) -> None:
    command = {"argv": ["ffmpeg", "space name.mov"], "returncode": 1, "stderr": "x" * 300000}
    results = {"failed": {"status": "FAILED", "commands": [command]}}
    report = reporting.report(tmp_path, "FAILED", "retained failure", None, results)
    assert report.stat().st_size < 10000
    assert "## Results" in report.read_text()
    appendix = json.loads(report.with_name(report.stem + "-commands.json").read_text())
    assert appendix["failed"]["commands"] == [command]


def test_view_alias_does_not_create_duplicate_media(tmp_path: Path) -> None:
    mov = tmp_path / "master.mov"
    mov.write_bytes(b"retained real master stand-in; no encoder invoked")
    reuse = {
        "native": str(mov),
        "views": [{"path": str(mov), "role": "COMPARISON_MOV_SAME_MASTER"}],
    }
    value = worker.make_views(
        {"source": "native.mkv", "reuse_views": reuse, "media": str(tmp_path / "must-not-exist")}
    )
    assert value["views"] == reuse["views"] and value["native"] == "native.mkv"
    assert not (tmp_path / "must-not-exist").exists()
