"""Combined service admission/wiring; mocked scheduling is never target timing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as app
from ewp_waveform.application.cuda_combined_experiment import (
    COMBINED,
    CONTROL,
    TorchServiceExperiment,
    campaign,
)


def test_combined_focused_abba_short_then_service32() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    config = {
        "cuda_environment": {},
        "cuda_python": "fixture-python",
        "repeats": 2,
        "cuda_combined_service32": True,
    }
    config["cuda_environment"] = {"fixture": True}

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"optional": True, "python": "fixture-python"}
        calls.append((name, request))
        return {
            "status": "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "output": name + ".mov",
            "original_raster_sha256": "original",
            "finished_rgba_sha256": "finished",
            "validation": {"passed": True},
        }

    def skipped(name: str, reason: str) -> None:
        raise AssertionError((name, reason))

    campaign(config, [{"id": "speech", "start": 25, "duration": 4, "frames": 240}], step, skipped)
    assert len(calls) == 10
    assert [r["operation"] for _, r in calls[:2]] == ["qualify-finish"] * 2
    for offset, duration in ((2, 4), (6, 32)):
        pair = calls[offset : offset + 4]
        assert [r["pair"]["side"] for _, r in pair] == list("ABBA")
        for _, r in pair:
            assert r["operation"] == "service" and r["torch_finish"] and r["jobs"] == 1
            assert r["workload"]["duration"] == duration
            expected = CONTROL if r["pair"]["side"] == "A" else COMBINED
            assert {k: r[k] for k in expected} == expected
        assert "reference" not in pair[0][1]
        for _, r in pair[1:]:
            assert r["reference"] == pair[0][0] + ".mov"
            assert r["expected_raster_sha256"] == "original"
            assert r["expected_finished_rgba_sha256"] == "finished"


@pytest.mark.parametrize("failure", ["qualification", "short", "smoke", "preparation"])
def test_combined_never_admits_service32_without_complete_original_short(failure: str) -> None:
    calls: list[str] = []
    skipped: list[str] = []

    def step(name: str, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        failed = (failure == "qualification" and name.endswith("candidate")) or (
            failure == "short" and name.endswith("r01-B")
        )
        return {
            "status": "FAILED" if failed else "SUCCEEDED",
            "passed": True,
            "gpu_qualified": True,
            "output": "fixture.mov",
            "original_raster_sha256": "r",
            "finished_rgba_sha256": "f",
            "validation": {"passed": True},
        }

    campaign(
        {
            "cuda_environment": None if failure == "preparation" else {"fixture": True},
            "cuda_python": "fixture",
            "repeats": 2,
            "cuda_combined_service32": True,
        },
        [{"id": "smoke" if failure == "smoke" else "speech"}],
        step,
        lambda name, reason: skipped.append(name),
    )
    assert not any("service32-r" in name for name in calls)
    assert skipped


def test_execute_focused_campaign_never_launches_vulkan_or_old_matrix(
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
            "gpu_qualified": True,
            "output": "fixture",
            "original_raster_sha256": "r",
            "finished_rgba_sha256": "f",
            "validation": {"passed": True},
        }

    monkeypatch.setattr(app, "invoke", invoke)
    monkeypatch.setattr(app, "make_result_views", lambda results, step: results)
    app.execute(
        {
            "selected": {"tools": {}},
            "smoke": True,
            "cuda_combined": True,
            "cuda_environment": {"fixture": True},
            "cuda_python": "fixture",
            "repeats": 2,
        },
        {},
    )
    assert len(calls) == 7
    assert all(n == "audio-plan" or n.startswith("cuda-combined-") for n in calls)


@pytest.mark.parametrize(
    "flags",
    [
        ["--cuda-combined"],
        ["--cuda", "--cuda-combined-service32"],
        ["--cuda", "--cuda-combined", "--optimize"],
        ["--cuda", "--cuda-combined", "--preflight-only"],
        ["--cuda", "--cuda-combined", "--full"],
        ["--resume", "/not-opened", "--cuda", "--cuda-combined"],
    ],
)
def test_combined_cli_refusals_before_setup(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app.main(["--cpu-smoke", *flags])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "options",
    [
        {"backend": "ffmpeg"},
        {"device": "cpu"},
        {"batch_size": True},
        {"timing_mode": "unknown"},
        {"backend": "torch-cpu", "device": "cuda:0"},
    ],
)
def test_adapter_options_fail_before_torch_import(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TorchServiceExperiment(**options)


def test_adapter_service_bounds_and_identity() -> None:
    adapter = TorchServiceExperiment()
    preset = SimpleNamespace(name="iuris-ribbon-refined")
    job = SimpleNamespace(domain=SimpleNamespace(value="frequency"), fps=60)
    adapter.validate(job, preset, ["prores4444"], 32)  # type: ignore[arg-type]
    for duration in (None, 0, 33, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="duration <=32s"):
            adapter.validate(job, preset, ["prores4444"], duration)  # type: ignore[arg-type]
    identity = adapter.identity()
    assert {k: identity[k] for k in COMBINED} == COMBINED
    assert identity["analysis_cache"] == "disabled"
    control = TorchServiceExperiment(**CONTROL)
    assert control.identity() != identity


def test_service_refuses_pool_or_competing_adapter_without_media(tmp_path: Path) -> None:
    from ewp_waveform.application.portable_experiments_worker import service_render

    for options in (
        {"jobs": 2},
        {"jobs": 1, "finish_lut": True},
        {"jobs": 1, "variant": "PRORES-GPU"},
        {"torch_finish": 1},
    ):
        media = tmp_path / "absent"
        with pytest.raises(ValueError, match="FIR service requires"):
            service_render({"torch_finish": True, "media": str(media), **options})
        assert not media.exists()
