"""Opt-in FIR ribbon finishing, independent NumPy oracle and lazy Torch worker.

This is a NEW algorithm, not an implementation-equivalence claim for FFmpeg's
recursive gblur. Horizontal area AA -> separable normalized Gaussian FIR (4 sigma,
replicated boundary) -> body/halo union -> overscan crop -> lower reflection ->
independent horizon coverage -> straight RGB, with zero RGB at quantized alpha 0.
No default renderer imports this module. No explicit torch.compile or automatic installation.
"""

from __future__ import annotations

import importlib
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

type U8 = NDArray[np.uint8]
type F32 = NDArray[np.float32]
ALGORITHM = "ribbon-fir-gaussian-v1-not-ffmpeg-recursive-gblur"


def validate_backend_device(backend: str, device: str) -> None:
    """Never let a CUDA label select CPU, even before optional Torch imports."""
    if backend in ("cuda", "transfer-cuda") and re.fullmatch(r"cuda:[0-9]+", device) is None:
        raise ValueError("CUDA backends require an explicit cuda:N device, never CPU fallback")


@dataclass(frozen=True)
class FinishSpec:
    width: int = 1400
    height: int = 280
    overscan: int = 50
    supersample: int = 1  # Production supersamples X only, never Y.
    sigma: float = 16.0
    reflection: float = 0.45
    horizon: bool = True
    thickness: float = 1.0
    extent: float = 0.96
    opacity: float = 0.55
    color: tuple[int, int, int] = (199, 230, 236)

    def __post_init__(self) -> None:
        if (
            any(
                type(v) is not int
                for v in (self.width, self.height, self.overscan, self.supersample)
            )
            or min(self.width, self.height, self.supersample) < 1
            or self.overscan < 0
            or not all(
                math.isfinite(v)
                for v in (self.sigma, self.reflection, self.thickness, self.extent, self.opacity)
            )
            or not 0 <= self.sigma <= 64
            or self.thickness < 0
            or any(not 0 <= v <= 1 for v in (self.reflection, self.extent, self.opacity))
            or len(self.color) != 3
            or any(type(v) is not int or not 0 <= v <= 255 for v in self.color)
        ):
            raise ValueError("invalid FIR finishing geometry/parameters")

    @property
    def input_shape(self) -> tuple[int, int]:
        return self.height + 2 * self.overscan, (self.width + 2 * self.overscan) * self.supersample


def gaussian_kernel(sigma: float) -> F32:
    if sigma == 0:
        return np.ones(1, dtype=np.float32)
    radius = math.ceil(4 * sigma)
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    return np.asarray(kernel / kernel.sum(), dtype=np.float32)


def horizon_coverage(spec: FinishSpec) -> F32:
    x = np.arange(spec.width, dtype=np.float64)
    y = np.arange(spec.height, dtype=np.float64)
    left = spec.width * (1 - spec.extent) / 2
    right = spec.width * (1 + spec.extent) / 2
    cy = spec.height // 2 + 0.5
    top, bottom = cy - spec.thickness / 2, cy + spec.thickness / 2
    xx = np.clip(np.minimum(x + 1, right) - np.maximum(x, left), 0, 1)
    yy = np.clip(np.minimum(y + 1, bottom) - np.maximum(y, top), 0, 1)
    return np.asarray(yy[:, None] * xx[None, :] * spec.opacity * spec.horizon, dtype=np.float32)


def input_mask(frame: bytes | U8, spec: FinishSpec, pix_fmt: str = "gray") -> U8:
    if pix_fmt not in ("gray", "rgba"):
        raise ValueError("only original gray or RGBA raster inputs are supported")
    values = np.frombuffer(frame, dtype=np.uint8) if isinstance(frame, bytes) else frame
    if values.dtype != np.uint8:
        raise ValueError("original raster must be uint8")
    shape = spec.input_shape if pix_fmt == "gray" else (*spec.input_shape, 4)
    if values.size != math.prod(shape):
        raise ValueError(f"original raster size mismatch, expected {shape}")
    values = values.reshape(shape)
    return np.ascontiguousarray(values if pix_fmt == "gray" else values[..., 3])


def _convolve_axis(values: F32, kernel: F32, axis: int) -> F32:
    radius = len(kernel) // 2
    if not radius:
        return values.copy()
    pads = [(0, 0)] * values.ndim
    pads[axis] = (radius, radius)
    padded = np.pad(values, pads, mode="edge")
    result = np.zeros_like(values)
    for i, weight in enumerate(kernel):
        indices = [slice(None)] * values.ndim
        indices[axis] = slice(i, i + values.shape[axis])
        result += padded[tuple(indices)] * weight
    return result


def numpy_alpha(mask: U8, spec: FinishSpec) -> F32:
    """Independent executable float32 CPU oracle; output alpha is in [0, 1]."""
    mask = input_mask(mask, spec)
    h, _ = spec.input_shape
    body = np.asarray(
        mask.astype(np.float32).reshape(h, -1, spec.supersample).mean(axis=2) / np.float32(255),
        dtype=np.float32,
    )
    kernel = gaussian_kernel(spec.sigma)
    halo = _convolve_axis(_convolve_axis(body, kernel, 1), kernel, 0)
    union = body + halo * (1 - body) if spec.sigma else body
    p = spec.overscan
    alpha = union[p : p + spec.height, p : p + spec.width].copy()
    alpha[spec.height // 2 + 1 :] *= spec.reflection
    line = horizon_coverage(spec)
    return np.clip(line + alpha * (1 - line), 0, 1)


def rgba_from_alpha(alpha: F32, spec: FinishSpec) -> U8:
    quantized = np.floor(np.clip(alpha, 0, 1) * 255 + 0.5).astype(np.uint8)
    output = np.zeros((*quantized.shape, 4), dtype=np.uint8)
    output[..., 3] = quantized
    output[..., :3] = np.where(quantized[..., None] > 0, spec.color, 0).astype(np.uint8)
    return output


OUTPUT_MODES = ("host-reference", "host-reuse", "device-rgba", "device-alpha8")
TIMING_MODES = ("diagnostic", "ordinary")
MAX_BATCH_SIZE = 16


def validate_execution_options(output_mode: str, batch_size: int, timing_mode: str) -> None:
    """Validate experimental controls before optional imports or filesystem writes."""
    if output_mode not in OUTPUT_MODES or timing_mode not in TIMING_MODES:
        raise ValueError("unknown FIR output_mode or timing_mode")
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be an integer in [1, {MAX_BATCH_SIZE}]")


class HostRGBAAssembler:
    """Exact float32 half-up quantization with reusable scratch and a straight-RGBA LUT.

    Results are borrowed until the next assemble/from_quantized call. The LUT sets
    hidden RGB to zero; visible RGB is the unpremultiplied spec.color even at alpha 1.
    Buffer capacity is fixed; partial batches use only their live prefix.
    """

    def __init__(self, spec: FinishSpec, batch_size: int = 1) -> None:
        validate_execution_options("host-reuse", batch_size, "ordinary")
        shape = (batch_size, spec.height, spec.width)
        self.scratch = np.empty(shape, dtype=np.float32)
        self.quantized = np.empty(shape, dtype=np.uint8)
        # np.take otherwise casts uint8 indices to a newly allocated intp plane
        # on every call. Retain that index plane as well as quantization scratch.
        self.indices = np.empty(shape, dtype=np.intp)
        self.output = np.empty((*shape, 4), dtype=np.uint8)
        self.table = np.empty((256, 4), dtype=np.uint8)
        self.table[:, :3] = spec.color
        self.table[:, 3] = np.arange(256, dtype=np.uint8)
        self.table[0] = 0

    def _count(self, values: F32 | U8) -> int:
        if (
            values.ndim != 3
            or values.shape[1:] != self.scratch.shape[1:]
            or not 1 <= len(values) <= len(self.scratch)
        ):
            raise ValueError("alpha batch shape exceeds fixed assembly capacity")
        return len(values)

    def assemble(self, alpha: F32) -> U8:
        n = self._count(alpha)
        if alpha.dtype != np.float32:
            raise ValueError("reusable assembly requires float32 alpha")
        scratch, quantized = self.scratch[:n], self.quantized[:n]
        np.clip(alpha, 0, 1, out=scratch)
        np.multiply(scratch, np.float32(255), out=scratch)
        np.add(scratch, np.float32(0.5), out=scratch)
        np.floor(scratch, out=scratch)
        np.copyto(quantized, scratch, casting="unsafe")
        return self.from_quantized(quantized)

    def from_quantized(self, quantized: U8) -> U8:
        n = self._count(quantized)
        if quantized.dtype != np.uint8:
            raise ValueError("quantized alpha must be uint8")
        # mode=clip avoids np.take's mandatory output buffering for mode=raise.
        np.copyto(self.indices[:n], quantized)
        np.take(self.table, self.indices[:n], axis=0, out=self.output[:n], mode="clip")
        return self.output[:n]


def numpy_finish(
    frame: bytes | U8,
    spec: FinishSpec,
    pix_fmt: str = "gray",
    *,
    phases: dict[str, float] | None = None,
) -> U8:
    started, cpu = time.perf_counter(), time.process_time()
    mask = input_mask(frame, spec, pix_fmt)
    if phases is not None:
        phases["host_input_conversion_wall_seconds"] = time.perf_counter() - started
        phases["host_input_conversion_process_cpu_seconds"] = time.process_time() - cpu
    started, cpu = time.perf_counter(), time.process_time()
    alpha = numpy_alpha(mask, spec)
    if phases is not None:
        phases["alpha_compute_wall_seconds"] = time.perf_counter() - started
        phases["alpha_compute_process_cpu_seconds"] = time.process_time() - cpu
    started, cpu = time.perf_counter(), time.process_time()
    output = rgba_from_alpha(alpha, spec)
    if phases is not None:
        phases["host_output_conversion_wall_seconds"] = time.perf_counter() - started
        phases["host_output_conversion_process_cpu_seconds"] = time.process_time() - cpu
    return output


class TorchFinisher:
    """Opt-in bounded eager batches; no compile, warmup or global Torch settings.

    host-reference preserves the allocating float-alpha host control. host-reuse
    selects exact reusable host assembly. device-rgba quantizes/assembles on the
    selected device, downloading RGBA8 (still 4 bytes/pixel); device-alpha8 downloads
    just quantized alpha (1 byte/pixel), then uses the reusable host LUT.

    Diagnostic timing serializes phases with CUDA events. Ordinary timing records
    only completed call wall/CPU spans, with no events or per-phase explicit sync.
    Transfers remain blocking; this is not a synchronization-free CUDA pipeline.
    No asynchronous overlap/pinned-memory claim. Batch outputs from reusable modes
    are borrowed until the next finish call; consume/copy before reusing this worker.
    """

    def __init__(
        self,
        spec: FinishSpec,
        device: str = "cuda:0",
        *,
        output_mode: str = "host-reference",
        batch_size: int = 1,
        timing_mode: str = "diagnostic",
    ) -> None:
        validate_execution_options(output_mode, batch_size, timing_mode)
        if device != "cpu" and not (device.startswith("cuda:") and device[5:].isdigit()):
            raise ValueError("explicit cpu or cuda:N device required")
        # Conservative admission screen, not a guarantee of CUDA library workspace.
        # Production 1400x280 fits; oversized geometry/capacity refuses before imports.
        if batch_size * (math.prod(spec.input_shape) + spec.width * spec.height) * 64 > 256 << 20:
            raise ValueError("batch geometry exceeds 256 MiB conservative working-set screen")
        self.spec = spec
        self.device = device
        self.cuda = device.startswith("cuda:")
        self.output_mode = output_mode
        self.batch_size = batch_size
        self.timing_mode = timing_mode
        self.timings: list[dict[str, Any]] = []
        started = time.perf_counter()
        self.torch: Any = importlib.import_module("torch")
        self.import_seconds = time.perf_counter() - started
        torch = self.torch
        started = time.perf_counter()
        # A real allocation and synchronize, never is_available() as qualification.
        torch.empty(1, device=device)
        self._sync()
        self.context_seconds = time.perf_counter() - started
        started = time.perf_counter()
        self.kernel = torch.from_numpy(gaussian_kernel(spec.sigma)).to(device)
        self.line = torch.from_numpy(horizon_coverage(spec)).to(device)
        self.reflection = torch.ones((spec.height, 1), device=device, dtype=torch.float32)
        self.reflection[spec.height // 2 + 1 :] = spec.reflection
        self.host_input = np.empty((batch_size, *spec.input_shape), dtype=np.uint8)
        self.assembler = (
            HostRGBAAssembler(spec, batch_size)
            if output_mode in ("host-reuse", "device-alpha8")
            else None
        )
        # Allocate the small device LUT only for the assembly candidate.
        self.table: Any = None
        if output_mode == "device-rgba":
            table = np.empty((256, 4), dtype=np.uint8)
            table[:, :3] = spec.color
            table[:, 3] = np.arange(256, dtype=np.uint8)
            table[0] = 0
            self.table = torch.from_numpy(table).to(device)
        self._sync()
        self.setup_seconds = time.perf_counter() - started

    def _sync(self) -> None:
        if self.cuda:
            self.torch.cuda.synchronize(self.device)

    def _phase(self, name: str, operation: Callable[[], Any], row: dict[str, Any]) -> Any:
        if self.timing_mode == "ordinary":
            return operation()
        self._sync()
        a = b = None
        if self.cuda and not name.startswith("host_"):
            with self.torch.cuda.device(self.device):
                a = self.torch.cuda.Event(enable_timing=True)
                b = self.torch.cuda.Event(enable_timing=True)
                a.record(self.torch.cuda.current_stream(self.device))
        started, cpu = time.perf_counter(), time.process_time()
        value = operation()
        if b is not None:
            b.record(self.torch.cuda.current_stream(self.device))
        self._sync()
        row[name + "_wall_seconds"] = time.perf_counter() - started
        row[name + "_process_cpu_seconds"] = time.process_time() - cpu
        row[name + "_cuda_event_seconds"] = a.elapsed_time(b) / 1000 if a is not None else None
        return value

    def _alpha(self, values: Any) -> Any:
        torch, spec = self.torch, self.spec
        h, _ = spec.input_shape
        body = values.reshape(len(values), h, -1, spec.supersample).mean(dim=3) / 255
        if spec.sigma:
            functional = torch.nn.functional
            r = self.kernel.numel() // 2
            image = body[:, None]
            horizontal = functional.conv2d(
                functional.pad(image, (r, r, 0, 0), mode="replicate"),
                self.kernel.reshape(1, 1, 1, -1),
            )
            halo = functional.conv2d(
                functional.pad(horizontal, (0, 0, r, r), mode="replicate"),
                self.kernel.reshape(1, 1, -1, 1),
            )[:, 0]
            body = body + halo * (1 - body)
        p = spec.overscan
        alpha = body[:, p : p + spec.height, p : p + spec.width] * self.reflection
        return (self.line + alpha * (1 - self.line)).clamp(0, 1)

    def _quantize(self, alpha: Any) -> Any:
        # Same separate float32 operations/half-up rule as the independent oracle.
        return self.torch.floor(alpha.clamp(0, 1) * 255 + 0.5).to(self.torch.uint8)

    def _run_batch(
        self, frames: Sequence[bytes | U8], pix_fmt: str, *, alpha_only: bool = False
    ) -> F32 | U8:
        n = len(frames)
        if not 1 <= n <= self.batch_size:
            raise ValueError("nonempty batch must not exceed configured batch_size")
        mode = "float-alpha-only" if alpha_only else self.output_mode
        download_bpp = 1 if mode == "device-alpha8" else 4
        row: dict[str, Any] = {
            "ordinal": len(self.timings),
            "kind": "finish-alpha" if alpha_only else "finish",
            "batch_frames": n,
            "batch_capacity": self.batch_size,
            "output_mode": mode,
            "timing_mode": self.timing_mode,
            "upload_bytes": n * math.prod(self.spec.input_shape),
            "download_bytes": n * self.spec.height * self.spec.width * download_bpp,
            "upload_dtype": "uint8",
            "download_dtype": {
                "device-rgba": "uint8-rgba",
                "device-alpha8": "uint8-alpha",
            }.get(mode, "float32-alpha"),
            "transfer_scope": "tensor payload; CPU worker makes no host/device transfers",
        }
        row["host_to_device_bytes"] = row["upload_bytes"] if self.cuda else 0
        row["device_to_host_bytes"] = row["download_bytes"] if self.cuda else 0
        started, cpu = time.perf_counter(), time.process_time()

        def prepare() -> Any:
            for i, frame in enumerate(frames):
                np.copyto(self.host_input[i], input_mask(frame, self.spec, pix_fmt))
            return self.torch.from_numpy(self.host_input[:n])

        host = self._phase("host_input_conversion", prepare, row)
        with self.torch.inference_mode():
            uploaded = self._phase("upload", lambda: host.to(self.device), row)
            values = self._phase("device_conversion", lambda: uploaded.float(), row)
            alpha = self._phase("compute", lambda: self._alpha(values), row)
            if alpha.dtype != self.torch.float32 or tuple(alpha.shape) != (
                n,
                self.spec.height,
                self.spec.width,
            ):
                raise ValueError("compute must return float32 BxHxW alpha")
            if self.cuda and not (uploaded.is_cuda and values.is_cuda and alpha.is_cuda):
                raise ValueError("CUDA finishing unexpectedly produced host tensors; no fallback")
            payload = alpha
            if mode in ("device-rgba", "device-alpha8"):
                payload = self._phase("device_quantization", lambda: self._quantize(alpha), row)
                if mode == "device-rgba":
                    quantized = payload
                    payload = self._phase(
                        "device_assembly", lambda: self.table[quantized.long()], row
                    )
            if self.cuda and not payload.is_cuda:
                raise ValueError("CUDA output unexpectedly remained on host; no fallback")
            expected_dtype = (
                self.torch.uint8 if mode in ("device-rgba", "device-alpha8") else self.torch.float32
            )
            if payload.dtype != expected_dtype or (
                payload.numel() * payload.element_size() != row["download_bytes"]
            ):
                raise ValueError("output tensor dtype/size differs from declared transfer payload")
            result = self._phase("download", lambda: payload.cpu().numpy(), row)
        if mode in ("host-reference", "host-reuse", "device-alpha8"):

            def assemble() -> U8:
                if mode == "host-reference":
                    return rgba_from_alpha(result, self.spec)
                assert self.assembler is not None
                if mode == "host-reuse":
                    return self.assembler.assemble(result)
                return self.assembler.from_quantized(result)

            result = self._phase("host_output_conversion", assemble, row)
        if self.timing_mode == "ordinary":
            # Exactly one explicit completion boundary per ordinary call. Blocking
            # .cpu() above already makes its download visible before host assembly.
            self._sync()
        row["call_wall_seconds"] = time.perf_counter() - started
        row["call_process_cpu_seconds"] = time.process_time() - cpu
        self.timings.append(row)
        return result  # type: ignore[no-any-return]

    def finish_alpha(self, mask: U8) -> F32:
        """Independent float-alpha diagnostic, irrespective of selected output path."""
        return np.asarray(self._run_batch([mask], "gray", alpha_only=True)[0], dtype=np.float32)

    def finish_batch(self, frames: Sequence[bytes | U8], pix_fmt: str = "gray") -> U8:
        """Return ordered BxHxWx4; reusable modes borrow storage until next finish."""
        return np.asarray(self._run_batch(frames, pix_fmt), dtype=np.uint8)

    def finish(self, frame: bytes | U8, pix_fmt: str = "gray") -> U8:
        return np.asarray(self.finish_batch([frame], pix_fmt)[0], dtype=np.uint8)

    def transfer(self, frame: bytes | U8, pix_fmt: str = "gray") -> U8:
        """Identical uint8 mask roundtrip, with NO device finishing computation."""
        if (self.output_mode, self.batch_size, self.timing_mode) != (
            "host-reference",
            1,
            "diagnostic",
        ):
            raise ValueError("transfer-only control retains batch-one diagnostic defaults")
        row: dict[str, Any] = {
            "ordinal": len(self.timings),
            "kind": "transfer-only",
            "upload_bytes": math.prod(self.spec.input_shape),
            "download_bytes": math.prod(self.spec.input_shape),
            "upload_dtype": "uint8",
            "download_dtype": "uint8-mask",
            "control_scope": "exact mask roundtrip; not matched float-alpha download volume",
        }
        started, cpu = time.perf_counter(), time.process_time()
        mask = input_mask(frame, self.spec, pix_fmt)
        host = self.torch.from_numpy(mask.copy())
        row["host_input_conversion_wall_seconds"] = time.perf_counter() - started
        row["host_input_conversion_process_cpu_seconds"] = time.process_time() - cpu
        uploaded = self._phase("upload", lambda: host.to(self.device), row)
        if self.cuda and not uploaded.is_cuda:
            raise ValueError("CUDA transfer unexpectedly remained on host; no fallback")
        result = self._phase("download", lambda: uploaded.cpu().numpy(), row)
        if not np.array_equal(result, mask):
            raise ValueError("transfer roundtrip changed original mask bytes")
        self.timings.append(row)
        return np.asarray(result, dtype=np.uint8)

    def evidence(self) -> dict[str, Any]:
        torch = self.torch
        return {
            "torch_version": torch.__version__,
            "torch_cuda_build": torch.version.cuda,
            "device": self.device,
            "device_name": torch.cuda.get_device_name(self.device) if self.cuda else "CPU",
            "compute_capability": torch.cuda.get_device_capability(self.device)
            if self.cuda
            else None,
            "torch_arch_list": torch.cuda.get_arch_list() if self.cuda else [],
            "import_seconds": self.import_seconds,
            "context_seconds": self.context_seconds,
            "setup_seconds": self.setup_seconds,
            "compilation": (
                "NO_TORCH_COMPILE_REQUESTED; implicit CUDA/library initialization or driver JIT "
                "may occur on first calls and remains included in qualification/cold process costs"
            ),
            "warmup": "NONE; first call retained as ordinal 0",
            "output_mode": self.output_mode,
            "batch_size": self.batch_size,
            "timing_mode": self.timing_mode,
            "output_ownership": (
                "borrowed until next finish call"
                if self.output_mode in ("host-reuse", "device-alpha8")
                else "owned output"
            ),
            "phase_scope": (
                "diagnostic synchronized serialized phases; wall and CUDA events non-additive"
                if self.timing_mode == "diagnostic"
                else "ordinary completed call wall/CPU only; one explicit completion sync; "
                "blocking transfers; no CUDA events"
            ),
            "call_timer": (
                "after batch metadata/validation, before host input preparation through "
                "completed download and optional host assembly; ends before timing-row append; "
                "excludes tobytes/encoder feed"
            ),
            "calls": self.timings,
        }


def correctness_cases(spec: FinishSpec) -> dict[str, U8]:
    h, w = spec.input_shape
    zero = np.zeros((h, w), dtype=np.uint8)
    impulse = zero.copy()
    impulse[h // 2, w // 2] = 255
    edge = zero.copy()
    edge[0, 0] = 255
    fractional = np.full((h, w), 37, dtype=np.uint8)
    reflection = zero.copy()
    reflection[h // 2 - 4 : h // 2 + 5, w // 3 : 2 * w // 3] = 255
    return {
        "zero-horizon-hidden-rgb": zero,
        "impulse": impulse,
        "edge-impulse": edge,
        "fractional-alpha": fractional,
        "reflection": reflection,
    }


def qualify(
    backend: str = "numpy",
    *,
    device: str = "cuda:0",
    output_mode: str = "host-reference",
    batch_size: int = 1,
    timing_mode: str = "diagnostic",
) -> dict[str, Any]:
    """Real upload/compute/download and independent oracle checks at both geometries.

    Raises on failure; a missing dependency/device is NOT a successful qualification.
    FIR float alpha tolerance 3e-5, uint8 alpha <=1, exact RGB including hidden RGB,
    and straight composites on black/white/magenta within 1 output byte.
    """
    if backend not in ("numpy", "torch-cpu", "cuda", "transfer-cuda"):
        raise ValueError("qualification backend must be numpy/torch-cpu/cuda/transfer-cuda")
    validate_backend_device(backend, device)
    validate_execution_options(output_mode, batch_size, timing_mode)
    if backend not in ("torch-cpu", "cuda") and (output_mode, batch_size, timing_mode) != (
        "host-reference",
        1,
        "diagnostic",
    ):
        raise ValueError("execution controls require torch-cpu or cuda finishing")
    rows: list[dict[str, Any]] = []
    gpu_workers: list[bool] = []
    for width, height in ((64, 32), (1400, 280)):
        spec = FinishSpec(width=width, height=height, overscan=50, supersample=2)
        worker = (
            None
            if backend == "numpy"
            else TorchFinisher(
                spec,
                "cpu" if backend == "torch-cpu" else device,
                output_mode=output_mode,
                batch_size=batch_size,
                timing_mode=timing_mode,
            )
        )
        if backend in ("cuda", "transfer-cuda"):
            if worker is None or not worker.cuda:
                raise ValueError("CUDA qualification requires an actual CUDA worker")
            gpu_workers.append(worker.cuda)
        cases = correctness_cases(spec)
        outputs: dict[str, U8] = {}
        if worker is not None and backend != "transfer-cuda":
            names = list(cases)
            for offset in range(0, len(names), batch_size):
                group = names[offset : offset + batch_size]
                batch = worker.finish_batch([cases[name] for name in group])
                for name, image in zip(group, batch, strict=True):
                    outputs[name] = image.copy()  # Reusable output expires on the next batch.
        for name, mask in cases.items():
            if backend == "transfer-cuda":
                assert worker is not None
                actual_mask = worker.transfer(mask)
                if not np.array_equal(actual_mask, mask):
                    raise ValueError(f"CUDA transfer changed mask bytes: {width}x{height} {name}")
                rows.append(
                    {
                        "geometry": [width, height],
                        "case": name,
                        "bytes_equal": True,
                        "scope": "UINT8_MASK_TRANSFER_ONLY_NO_FINISHING_COMPUTE",
                    }
                )
                continue
            expected = numpy_alpha(mask, spec)
            actual = numpy_alpha(mask, spec) if worker is None else worker.finish_alpha(mask)
            if actual.shape != expected.shape or not np.isfinite(actual).all():
                raise ValueError(f"{backend} nonfinite or malformed alpha: {name}")
            rgba = rgba_from_alpha(actual, spec) if worker is None else outputs[name]
            reference = rgba_from_alpha(expected, spec)
            if rgba.shape != reference.shape:
                raise ValueError(f"{backend} malformed batched RGBA: {name}")
            float_error = float(np.max(np.abs(actual - expected)))
            byte_error = int(
                np.max(np.abs(rgba[..., 3].astype(np.int16) - reference[..., 3].astype(np.int16)))
            )
            rgb_equal = bool(np.array_equal(rgba[..., :3], reference[..., :3]))
            composite_error = 0.0
            for background in ((0, 0, 0), (255, 255, 255), (255, 0, 255)):

                def composite(image: U8, bg: tuple[int, int, int] = background) -> Any:
                    a = image[..., 3:4].astype(np.float32) / 255
                    return image[..., :3] * a + np.asarray(bg) * (1 - a)

                composite_error = max(
                    composite_error, float(np.max(np.abs(composite(rgba) - composite(reference))))
                )
            if float_error > 3e-5 or byte_error > 1 or not rgb_equal or composite_error > 1.001:
                raise ValueError(f"{backend} correctness failed: {width}x{height} {name}")
            # Alpha extraction ignores arbitrary hidden RGB in the original raster.
            colored = np.full((*mask.shape, 4), 173, dtype=np.uint8)
            colored[..., 3] = mask
            if not np.array_equal(input_mask(colored, spec, "rgba"), mask):
                raise ValueError("RGBA original-alpha extraction failed")
            rows.append(
                {
                    "geometry": [width, height],
                    "case": name,
                    "max_float_alpha_error": float_error,
                    "max_alpha_byte_error": byte_error,
                    "rgb_including_hidden_equal": rgb_equal,
                    "max_composite_byte_error": composite_error,
                }
            )
        rows.append(
            {
                "geometry": [width, height],
                "worker": worker.evidence() if worker else None,
                "spec": asdict(spec),
            }
        )
    return {
        "passed": True,
        "backend": backend,
        "output_mode": output_mode,
        "batch_size": batch_size,
        "timing_mode": timing_mode,
        "algorithm": ALGORITHM,
        "gpu_qualified": backend == "cuda" and len(gpu_workers) == 2 and all(gpu_workers),
        "transfer_qualified": backend == "transfer-cuda"
        and len(gpu_workers) == 2
        and all(gpu_workers),
        "cases": rows,
        "claim": (
            "compute-free CUDA mask transfers only; finishing compute is independently qualified"
            if backend == "transfer-cuda"
            else "same FIR algorithm backend equivalence; not FFmpeg appearance acceptance"
        ),
    }
