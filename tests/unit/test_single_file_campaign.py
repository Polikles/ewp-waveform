"""Focused target scheduling, preserving independence from optional LUT/CUDA failures."""

from __future__ import annotations

from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.single_file_campaign import campaign


def test_single_file_target_pairs_and_optional_cuda_are_narrow() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append((name, request))
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "validation": {"passed": True},
            "output": name + ".mov",
            "original_raster_sha256": "r",
            "finished_rgba_sha256": "f",
        }

    skipped: list[str] = []
    campaign(
        {
            "cuda": True,
            "cuda_environment": {"fixture": True},
            "cuda_python": "fixture-python",
            "repeats": 2,
        },
        [{"id": "speech", "kind": "short", "start": 25, "duration": 4, "frames": 240}],
        step,
        lambda name, reason: skipped.append(name),
    )
    assert not skipped
    assert len(calls) == 23  # 1 LUT gate +12 CPU renders +2 CUDA gates +8 CUDA renders.
    assert [n for n, _ in calls[:1]] == ["single-file-lut-qualification"]
    for label in (
        "single-file-short-lut",
        "single-file-jobs32",
        "single-file-lut32",
        "cuda-combined-short",
        "cuda-combined-service32",
    ):
        pair = [r for n, r in calls if n.startswith(label + "-r")]
        assert [r["pair"]["side"] for r in pair] == list("ABBA")
        assert all(r["operation"] == "service" for r in pair)
        assert all(r["workload"]["duration"] == (4 if "short" in label else 32) for r in pair)
    jobs = [r["jobs"] for n, r in calls if n.startswith("single-file-jobs32-r")]
    assert jobs == [2, 1, 1, 2]
    assert not any(
        r.get("operation") in ("qualify", "direct", "codec", "compact") for _, r in calls
    )


@pytest.mark.parametrize("failure", ["lut-gate", "lut-short"])
def test_lut_failure_does_not_suppress_independent_jobs_policy_or_cuda(failure: str) -> None:
    calls: list[str] = []
    skipped: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        failed = (failure == "lut-gate" and name == "single-file-lut-qualification") or (
            failure == "lut-short" and name == "single-file-short-lut-r01-B"
        )
        return {
            "status": "FAILED" if failed else "SUCCEEDED",
            "passed": not failed,
            "gpu_qualified": True,
            "output": "fixture.mov",
            "validation": {"passed": True},
            "original_raster_sha256": "r",
            "finished_rgba_sha256": "f",
        }

    campaign(
        {
            "cuda": True,
            "cuda_environment": {"fixture": True},
            "cuda_python": "fixture",
            "repeats": 2,
        },
        [{"id": "speech"}],
        step,
        lambda name, reason: skipped.append(name),
    )
    assert len([n for n in calls if n.startswith("single-file-jobs32-r")]) == 4
    assert len([n for n in calls if n.startswith("cuda-combined-service32-r")]) == 4
    assert "single-file-lut32" in skipped
    assert not any(n.startswith("single-file-lut32-r") for n in calls)


def test_single_file_smoke_never_authorizes_medium() -> None:
    calls: list[str] = []
    skipped: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "output": "fixture.mov",
            "validation": {"passed": True},
        }

    campaign({"repeats": 2}, [{"id": "smoke"}], step, lambda name, reason: skipped.append(name))
    assert len(calls) == 5
    assert skipped == ["single-file-jobs32", "single-file-lut32"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--optimize"],
        ["--cuda", "--cuda-combined"],
        ["--preflight-only"],
        ["--full"],
        ["--setup-only"],
        ["--resume", "/not-opened"],
    ],
)
def test_single_file_cli_incompatible_scopes_refuse_before_setup(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app.main(["--cpu-smoke", "--optimize-single-file", *flags])
    assert exc.value.code == 2


def test_execute_single_file_never_enters_historical_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def invoke(config: Any, name: str, request: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        if name == "audio-plan":
            return {"workloads": [{"id": "smoke"}]}
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "validation": {"passed": True},
            "output": "fixture.mov",
        }

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "skip", lambda *args: {"status": "SKIPPED"})
    monkeypatch.setattr(app, "make_result_views", lambda results, step: results)
    app.execute(
        {"optimize_single_file": True, "selected": {"tools": {}}, "smoke": True, "repeats": 2}, {}
    )
    assert len(calls) == 6
    assert all(n == "audio-plan" or n.startswith("single-file-") for n in calls)
