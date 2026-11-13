"""FIR correctness, not visual equivalence to FFmpeg recursive gblur."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ewp_waveform.application.torch_experiment import main, render_experiment
from ewp_waveform.ffmpeg.torch_finish import (
    FinishSpec,
    TorchFinisher,
    gaussian_kernel,
    horizon_coverage,
    input_mask,
    numpy_alpha,
    numpy_finish,
    qualify,
)


def test_import_does_not_import_torch() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import ewp_waveform.application.torch_experiment; "
            "assert 'torch' not in sys.modules",
        ],
        check=True,
    )


@pytest.mark.parametrize("width,height", [(64, 32), (1400, 280)])
def test_zero_horizon_and_hidden_rgb(width: int, height: int) -> None:
    spec = FinishSpec(width=width, height=height, overscan=0)
    mask = np.zeros(spec.input_shape, dtype=np.uint8)
    result = numpy_finish(mask, spec)
    assert result.shape == (height, width, 4)
    assert np.array_equal(result[..., 3], np.floor(horizon_coverage(spec) * 255 + 0.5))
    assert np.all(result[result[..., 3] == 0, :3] == 0)
    assert np.all(result[result[..., 3] > 0, :3] == spec.color)
    assert np.all(numpy_finish(mask, replace(spec, horizon=False)) == 0)


def test_fractional_horizon_pixel_coverage() -> None:
    spec = FinishSpec(width=64, height=32, overscan=0, thickness=0.5, extent=0.96)
    line = horizon_coverage(spec)
    assert line[16, 1] == pytest.approx(0.72 * 0.5 * 0.55)
    assert line[16, 2] == pytest.approx(0.5 * 0.55)
    assert np.count_nonzero(line[15]) == 0
    assert np.count_nonzero(line[17]) == 0
    assert line[16, 0] == 0


def test_area_aa_is_horizontal_only_and_lower_reflection_after_union() -> None:
    spec = FinishSpec(
        width=8, height=6, overscan=2, supersample=2, sigma=0, horizon=False, reflection=0.45
    )
    mask = np.zeros(spec.input_shape, dtype=np.uint8)
    mask[:, ::2] = 255
    alpha = numpy_alpha(mask, spec)
    assert alpha.shape == (6, 8)
    assert np.allclose(alpha[:4], 0.5)
    assert np.allclose(alpha[4:], 0.5 * 0.45)
    assert mask[:, 1::2].sum() == 0  # Input never mutated.


def test_fir_matches_independent_scalar_convolution_and_crop() -> None:
    spec = FinishSpec(width=8, height=6, overscan=2, sigma=0.75, horizon=False, reflection=1)
    mask = np.zeros(spec.input_shape, dtype=np.uint8)
    mask[2, 3] = 255
    kernel = gaussian_kernel(spec.sigma).astype(np.float64)
    r = len(kernel) // 2
    values = mask.astype(np.float64) / 255
    halo = np.zeros_like(values)
    for y in range(values.shape[0]):
        for x in range(values.shape[1]):
            for iy, ky in enumerate(kernel):
                for ix, kx in enumerate(kernel):
                    yy = min(max(y + iy - r, 0), values.shape[0] - 1)
                    xx = min(max(x + ix - r, 0), values.shape[1] - 1)
                    halo[y, x] += values[yy, xx] * ky * kx
    expected = (values + halo * (1 - values))[2:8, 2:10]
    assert np.allclose(numpy_alpha(mask, spec), expected, atol=2e-7)


def test_sigma16_impulse_symmetry_and_alpha_union() -> None:
    spec = FinishSpec(width=65, height=33, overscan=48, sigma=16, reflection=1, horizon=False)
    mask = np.zeros(spec.input_shape, dtype=np.uint8)
    mask[64, 80] = 255
    alpha = numpy_alpha(mask, spec)
    assert alpha[16, 32] == 1
    assert 0 < alpha[16, 31] < 1
    assert np.allclose(alpha, alpha[::-1, ::-1], atol=1e-7)


def test_original_rgba_hidden_rgb_is_ignored() -> None:
    spec = FinishSpec(width=8, height=6, overscan=0, sigma=0, horizon=False)
    rgba = np.full((*spec.input_shape, 4), 91, dtype=np.uint8)
    rgba[..., 3] = 0
    rgba[2, 3, 3] = 37
    assert np.array_equal(numpy_finish(rgba, spec, "rgba"), numpy_finish(rgba[..., 3], spec))
    output = numpy_finish(rgba, spec, "rgba")
    assert tuple(output[2, 3]) == (*spec.color, 37)
    assert np.all(output[output[..., 3] == 0] == 0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 0},
        {"height": -1},
        {"overscan": -1},
        {"supersample": 0},
        {"sigma": float("nan")},
        {"sigma": -1},
        {"reflection": 1.1},
        {"opacity": -0.1},
        {"extent": 2},
        {"color": (1, 2, 256)},
    ],
)
def test_rejects_invalid_spec(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        FinishSpec(**kwargs)  # type: ignore[arg-type]


def test_input_validation() -> None:
    spec = FinishSpec(width=8, height=6, overscan=0)
    with pytest.raises(ValueError, match="size mismatch"):
        input_mask(b"a", spec)
    with pytest.raises(ValueError, match="uint8"):
        input_mask(np.zeros(spec.input_shape, dtype=np.float32), spec)
    with pytest.raises(ValueError, match="gray or RGBA"):
        input_mask(b"", spec, "rgb")


def test_numpy_qualification_both_geometries() -> None:
    result = qualify("numpy")
    assert result["passed"] and not result["gpu_qualified"]
    cases = [row for row in result["cases"] if "case" in row]
    assert len(cases) == 10
    assert {tuple(row["geometry"]) for row in cases} == {(64, 32), (1400, 280)}
    assert all(row["rgb_including_hidden_equal"] for row in cases)


def test_invalid_bounds_rejected_without_output(tmp_path: Path) -> None:
    output = tmp_path / "never" / "asset.mov"
    with pytest.raises(ValueError, match="duration"):
        render_experiment(source=tmp_path / "absent.wav", start=0, duration=33, output=output)
    assert not output.parent.exists()


def test_cli_failure_report_and_no_false_gpu_success(tmp_path: Path) -> None:
    import json

    report = tmp_path / "failed.json"
    assert main(["render", "--backend", "cuda", "--report", str(report)]) == 2
    result = json.loads(report.read_text())
    assert result["status"] == "FAILED_OR_UNAVAILABLE" and not result["gpu_qualified"]


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="optional torch absent")
def test_real_torch_cpu_equivalence() -> None:
    assert qualify("torch-cpu")["passed"]


@pytest.mark.skipif(
    os.environ.get("EWP_TEST_TORCH_CUDA") != "1",
    reason="real CUDA qualification explicitly opt-in; no availability-only pass",
)
def test_real_cuda_equivalence_and_transfer() -> None:
    assert qualify("cuda")["gpu_qualified"]
    transfer = qualify("transfer-cuda")
    assert transfer["transfer_qualified"] and not transfer["gpu_qualified"]


def test_device_selector_is_explicit() -> None:
    with pytest.raises(ValueError, match="explicit"):
        TorchFinisher(FinishSpec(), "cuda")


def test_numpy_phase_measurement_does_not_change_pixels() -> None:
    spec = FinishSpec(width=8, height=6, overscan=0, sigma=1)
    mask = np.full(spec.input_shape, 37, dtype=np.uint8)
    phases: dict[str, float] = {}
    assert np.array_equal(numpy_finish(mask, spec, phases=phases), numpy_finish(mask, spec))
    assert set(phases) == {
        "host_input_conversion_wall_seconds",
        "host_input_conversion_process_cpu_seconds",
        "alpha_compute_wall_seconds",
        "alpha_compute_process_cpu_seconds",
        "host_output_conversion_wall_seconds",
        "host_output_conversion_process_cpu_seconds",
    }
    assert all(value >= 0 for value in phases.values())


def test_qualification_rejects_nonfinite_alpha(monkeypatch: pytest.MonkeyPatch) -> None:
    from ewp_waveform.ffmpeg import torch_finish

    def nonfinite(mask: torch_finish.U8, spec: FinishSpec) -> torch_finish.F32:
        return np.full((spec.height, spec.width), np.nan, dtype=np.float32)

    monkeypatch.setattr(torch_finish, "numpy_alpha", nonfinite)
    with pytest.raises(ValueError, match="nonfinite"):
        qualify("numpy")
