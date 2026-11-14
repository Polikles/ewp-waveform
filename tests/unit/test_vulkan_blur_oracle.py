"""Independent finite-kernel and boundary reproductions, not RTX execution evidence."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pytest

from ewp_waveform.ffmpeg.backend_qualification import fixture
from ewp_waveform.ffmpeg.vulkan_blur_oracle import BLUR_TOLERANCE, assess_blur, blur_oracle


def scalar_reference(data: bytes, width: int, height: int) -> bytes:
    """Direct symmetric tap sum with clipped coordinates, not NumPy convolution."""
    taps = [
        sum(
            weight * math.exp(-((offset + delta) ** 2) / 512)
            for weight, delta in ((1, -0.5), (4, 0), (1, 0.5))
        )
        / 6
        for offset in range(49)
    ]
    scale = taps[0] + 2 * sum(taps[1:])
    taps = [tap / scale for tap in taps]
    current = list(data)
    for horizontal in (True, False):
        result = []
        for frame in range(2):
            for y in range(height):
                for x in range(width):
                    total = current[(frame * height + y) * width + x] * taps[0]
                    for offset in range(1, 49):
                        for sign in (-1, 1):
                            sx = min(width - 1, max(0, x + offset * sign)) if horizontal else x
                            sy = y if horizontal else min(height - 1, max(0, y + offset * sign))
                            total += current[(frame * height + sy) * width + sx] * taps[offset]
                    result.append(round(total))
        current = result
    return bytes(current)


@pytest.mark.parametrize("width,height", [(7, 5), (64, 32)])
def test_oracle_matches_independent_scalar_edge_taps(width: int, height: int) -> None:
    # Nonzero edges distinguish an explicit clamp contract from zero extension.
    data = bytes(
        (x * 7 + y * 13 + n * 31) % 256
        for n in range(2)
        for y in range(height)
        for x in range(width)
    )
    assert blur_oracle(data, width, height) == scalar_reference(data, width, height)


def boundary_simulation(
    data: bytes, width: int, height: int, mode: Literal["constant", "wrap"]
) -> bytes:
    """Invented OOB coordinate behavior to reproduce a hypothesis, never a GPU result."""
    positions = np.arange(-48, 49, dtype="f8")
    kernel = np.zeros_like(positions)
    for weight, delta in ((1, -0.5), (4, 0), (1, 0.5)):
        kernel += weight * np.exp(-((positions + delta) ** 2) / 512)
    kernel /= kernel.sum()
    values = np.frombuffer(data, "u1").reshape(2, height, width).astype("f8")
    for axis in (2, 1):
        padding = [(0, 0)] * 3
        padding[axis] = (48, 48)
        values = np.rint(
            np.apply_along_axis(
                lambda row: np.convolve(row, kernel, mode="valid"),
                axis,
                np.pad(values, padding, mode=mode),
            )
        )
    return values.astype("u1").tobytes()


@pytest.mark.parametrize("width,height", [(64, 32), (1400, 280)])
def test_centered_fixture_zero_and_clamp_are_identical(width: int, height: int) -> None:
    data = fixture("gray", width, height)
    assert boundary_simulation(data, width, height, "constant") == blur_oracle(data, width, height)


def test_simulated_wrap_reproduces_tiny_failure_without_breaking_large_case() -> None:
    results = {}
    for width, height in ((64, 32), (1400, 280)):
        data = fixture("gray", width, height)
        observed = boundary_simulation(data, width, height, "wrap")
        results[width] = assess_blur(data, observed, width, height)
    assert results[64]["status"] == "NUMERICAL_MISMATCH"
    assert results[64]["numerical_oracle"]["maximum_8bit_code_error"] == 6
    assert results[64]["numerical_oracle"]["mean_absolute_8bit_code_error"] == pytest.approx(
        2.757080078125
    )
    assert results[1400]["status"] == "PASS"
    # With radius48 no 64x32 output has a fully in-bounds source footprint.
    assert results[64]["numerical_oracle"]["regions"]["interior"]["samples"] == 0
    assert results[64]["numerical_oracle"]["regions"]["interior"]["maximum_8bit_code_error"] is None


def test_mean_threshold_is_not_relaxed_or_averaged_between_frames() -> None:
    data = bytes(200)
    at_limit = (bytes([2]) * 30 + bytes(70)) * 2
    result = assess_blur(data, at_limit, 10, 10)
    assert result["status"] == "PASS"
    assert result["numerical_oracle"]["mean_absolute_8bit_code_error"] == 0.6
    hidden_by_average = bytes([2]) * 60 + bytes(140)
    result = assess_blur(data, hidden_by_average, 10, 10)
    assert result["status"] == "NUMERICAL_MISMATCH"
    assert result["numerical_oracle"]["mean_absolute_8bit_code_error"] == 0.6
    assert result["numerical_oracle"]["frames"][0]["mean_absolute_8bit_code_error"] == 1.2
    assert BLUR_TOLERANCE["maximum_8bit_code_error"] == 2.0
    assert BLUR_TOLERANCE["mean_absolute_8bit_code_error"] == 0.6


def test_maximum_threshold_noop_and_truncation_fail_closed() -> None:
    data = bytes(200)
    for value, explanation in (
        (bytes([3]) + bytes(199), "finite Gaussian"),
        (data, "unchanged"),
        (data[:-1], "Truncated"),
    ):
        result = assess_blur(data, value, 10, 10)
        assert result["status"] == "NUMERICAL_MISMATCH"
        assert explanation in result["explanation"]
    evidence: dict[str, Any] = assess_blur(data, bytes([3]) + bytes(199), 10, 10)[
        "numerical_oracle"
    ]
    assert evidence["first_differences"] == [
        {"frame": 0, "x": 0, "y": 0, "expected": 0, "observed": 3}
    ]
    assert evidence["expected_bytes"] == 200
    assert evidence["observed_bytes"] == 200
