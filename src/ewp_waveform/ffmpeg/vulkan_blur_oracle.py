"""Independent fixed finite-Gaussian reference and bounded numerical diagnostics.

The reference specifies clamp edges; it does not infer that a selected Vulkan
shader implements clamping. In the pinned FFmpeg source, gblur's imageLoad tap
coordinates are not clamped. Out-of-bounds behavior is not an alternative oracle.
Source inspected: FFmpeg 7adfbe40dcde598f93a6963d2f7b22cd75202ccc,
libavfilter/vf_gblur_vulkan.c and libavfilter/vulkan/gblur.comp.glsl.
"""

from __future__ import annotations

import hashlib
from typing import Any

BLUR_RADIUS = 48
BLUR_TOLERANCE = {
    "maximum_8bit_code_error": 2.0,
    "mean_absolute_8bit_code_error": 0.6,
    "interpretation": "Descriptive finite-kernel float-convolution screen, fixed before execution; "
    "not production appearance equivalence or a performance acceptance threshold.",
}


def blur_oracle(data: bytes, width: int, height: int) -> bytes:
    """Two-frame sigma16,size97 Simpson taps; clamp; quantize both R8_UNORM passes.

    This is a reference contract, not software gblur's recursive approximation
    and not a model of unspecified out-of-bounds storage-image reads. The centered
    qualification fixture has zero edges, so zero extension gives identical bytes.
    """
    import numpy as np

    if width <= 0 or height <= 0 or len(data) != 2 * width * height:
        raise ValueError("blur reference requires two complete positive-geometry gray frames")
    values = np.frombuffer(data, dtype="u1").reshape(2, height, width).astype("f8")
    offsets = np.arange(-BLUR_RADIUS, BLUR_RADIUS + 1, dtype="f8")

    def gaussian(position: Any) -> Any:
        return np.exp(-(position * position) / (2 * 16.0**2))

    kernel = (gaussian(offsets - 0.5) + 4 * gaussian(offsets) + gaussian(offsets + 0.5)) / 6
    kernel /= kernel.sum()
    for axis in (2, 1):
        pad = [(0, 0)] * 3
        pad[axis] = (BLUR_RADIUS, BLUR_RADIUS)
        padded = np.pad(values, pad, mode="edge")
        values = np.apply_along_axis(
            lambda row: np.convolve(row, kernel, mode="valid"), axis, padded
        )
        values = np.clip(np.rint(values), 0, 255)
    return values.astype("u1").tobytes()


def assess_blur(data: bytes, observed: bytes, width: int, height: int) -> dict[str, Any]:
    """Keep complete-case metrics, per-frame gates and spatial evidence; never retune."""
    import numpy as np

    oracle = blur_oracle(data, width, height)
    evidence: dict[str, Any] = {
        "algorithm": "float64 finite separable Gaussian; sigma16, size97, normalized "
        "Simpson-integrated taps; clamp reference; nearest 8-bit at BOTH passes",
        "boundary_contract": "Reference clamp is explicit, not inferred from shader imageLoad; "
        "centered fixture also equals zero-extension. OOB reads are not a valid reference.",
        "kernel_radius": BLUR_RADIUS,
        "tolerance": dict(BLUR_TOLERANCE),
        "gate_scope": "Each frame must satisfy both unchanged tolerances; no cross-frame averaging",
        "expected_bytes": len(oracle),
        "observed_bytes": len(observed),
        "expected_sha256": hashlib.sha256(oracle).hexdigest(),
        "observed_sha256": hashlib.sha256(observed).hexdigest(),
    }
    result = {
        "status": "PASS",
        "explanation": "Finite Gaussian oracle passed",
        "numerical_oracle": evidence,
    }
    if len(observed) != len(oracle):
        result.update(status="NUMERICAL_MISMATCH", explanation="Truncated or oversized blur output")
        return result
    expected = np.frombuffer(oracle, "u1").reshape(2, height, width)
    actual = np.frombuffer(observed, "u1").reshape(2, height, width)
    error = np.abs(actual.astype("i4") - expected.astype("i4"))

    def metrics(values: Any) -> dict[str, Any]:
        return {
            "samples": int(values.size),
            "maximum_8bit_code_error": int(values.max()) if values.size else None,
            "mean_absolute_8bit_code_error": float(values.mean()) if values.size else None,
            "differing_samples": int(np.count_nonzero(values)),
        }

    evidence.update(metrics(error))
    evidence["frames"] = [metrics(frame) for frame in error]
    interior = error[
        :,
        BLUR_RADIUS : max(BLUR_RADIUS, height - BLUR_RADIUS),
        BLUR_RADIUS : max(BLUR_RADIUS, width - BLUR_RADIUS),
    ]
    boundary_mask = np.ones((height, width), dtype=bool)
    boundary_mask[
        BLUR_RADIUS : max(BLUR_RADIUS, height - BLUR_RADIUS),
        BLUR_RADIUS : max(BLUR_RADIUS, width - BLUR_RADIUS),
    ] = False
    evidence["regions"] = {
        "interior": metrics(interior),
        "boundary": metrics(error[:, boundary_mask]),
    }
    evidence["first_differences"] = [
        {
            "frame": int(index // (width * height)),
            "y": int(index // width % height),
            "x": int(index % width),
            "expected": int(expected.ravel()[index]),
            "observed": int(actual.ravel()[index]),
        }
        for index in np.flatnonzero(error)[:16]
    ]
    if any(
        frame["maximum_8bit_code_error"] > BLUR_TOLERANCE["maximum_8bit_code_error"]
        or frame["mean_absolute_8bit_code_error"] > BLUR_TOLERANCE["mean_absolute_8bit_code_error"]
        for frame in evidence["frames"]
    ):
        result.update(
            status="NUMERICAL_MISMATCH", explanation="Blur differs from finite Gaussian oracle"
        )
    if observed == data:
        result.update(status="NUMERICAL_MISMATCH", explanation="Blur output unchanged from input")
    return result
