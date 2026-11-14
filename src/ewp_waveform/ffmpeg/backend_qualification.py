"""Opt-in, independent bounded Vulkan execution qualification.

This module does not alter production adapters, choose a fallback, repair a
runtime, or infer support from a component listing. Every backend has its own
result even if another backend fails. Evidence is JSON/text; tiny temporary
codec files are deleted after software validation. Maximum geometry is 1400x280,
with two frames per case and a 45-second deadline per external command.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ewp_waveform.ffmpeg import vulkan_diagnostic
from ewp_waveform.ffmpeg.experiment_suite import codec_options, raw_input, raw_output
from ewp_waveform.ffmpeg.experiment_suite_probes import advertised
from ewp_waveform.ffmpeg.experiment_suite_validation import check_grid, decode_argv
from ewp_waveform.ffmpeg.vulkan_blur_oracle import (
    BLUR_RADIUS,
    assess_blur,
)
from ewp_waveform.ffmpeg.vulkan_blur_oracle import (
    BLUR_TOLERANCE as BLUR_TOLERANCE,
)
from ewp_waveform.ffmpeg.vulkan_blur_oracle import (
    blur_oracle as blur_oracle,
)

GEOMETRIES = ((64, 32), (1400, 280))
FORMATS = ("gray", "rgba", "bgra", "yuva444p10le")


def selected_device(stderr: str, expected: str) -> str:
    """Accept both actual FFmpeg log spellings, never inventory/device-list lines."""
    names = re.findall(r"(?:Using device:|Device\s+\d+\s+selected:)\s*([^\r\n]+)", stderr)
    if not names:
        raise ValueError("verbose FFmpeg selected-device evidence missing")
    if any(
        not re.search(expected, name, re.I)
        or re.search(r"llvmpipe|lavapipe|swiftshader|software|\bCPU\b", name, re.I)
        for name in names
    ):
        raise ValueError("wrong/software Vulkan device: " + "; ".join(names))
    return str(names[-1])


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _excerpts(stderr: str) -> list[str]:
    lines = stderr.splitlines()
    selected = [
        line
        for line in lines
        if re.search(
            r"selected:|Using device:|error|failed|unsupported|not supported|not implemented|"
            r"not found|no such|Unable|auto_scale|format|dzn|dozen|-38|Function",
            line,
            re.I,
        )
    ]
    return selected[-20:] or lines[-8:]


class _Commands:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: list[dict[str, Any]] = []

    def run(
        self, name: str, argv: list[str], data: bytes | None = None, *, text: bool = False
    ) -> tuple[dict[str, Any], bytes]:
        stem = f"{len(self.records):03d}-{name}"
        stderr_path = self.root / (stem + ".stderr")
        record: dict[str, Any] = {
            "name": name,
            "argv": argv,
            "timeout_seconds": 45,
            "returncode": None,
            "stderr_path": str(stderr_path),
            "stdin_bytes": len(data) if data is not None else 0,
            "stdin_sha256": _sha(data) if data is not None else None,
        }
        output = b""
        try:
            with stderr_path.open("wb") as err:
                proc = subprocess.run(
                    argv, input=data, stdout=subprocess.PIPE, stderr=err, timeout=45, check=False
                )
            output = proc.stdout
            record.update(
                returncode=proc.returncode,
                status="PASS" if proc.returncode == 0 else "EXECUTION_ERROR",
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or b""
            record.update(status="EXECUTION_ERROR", exception=repr(exc), stdout_complete=False)
        except OSError as exc:
            record.update(status="EXECUTION_ERROR", exception=repr(exc), stdout_complete=False)
        stderr = stderr_path.read_text(errors="replace") if stderr_path.exists() else ""
        record.update(
            stderr=stderr,
            excerpts=_excerpts(stderr),
            stdout_bytes=len(output),
            stdout_sha256=_sha(output),
        )
        if text:
            path = self.root / (stem + ".stdout.txt")
            path.write_bytes(output)
            record.update(stdout_path=str(path), stdout=output.decode(errors="replace"))
        self.records.append(record)
        with (self.root / "commands.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
        return record, output


def fixture(fmt: str, width: int, height: int) -> bytes:
    """Two varying frames with transparent hidden RGB and planar 10-bit alpha extremes."""
    import numpy as np

    n, y, x = np.indices((2, height, width), dtype=np.int32)
    alpha = np.where(
        x < width // 8, 0, np.where(x >= width * 7 // 8, 255, (x * 13 + y * 7 + n * 31) % 256)
    )
    if fmt == "gray":
        return (
            np.where((abs(x - width // 2 - n) < 5) & (abs(y - height // 2) < 4), 255, 0)
            .astype("u1")
            .tobytes()
        )
    channels = [
        (x * 3 + y + n * 19) % 256,
        (x + y * 5 + 7) % 256,
        (x * 7 + y * 3 + 199) % 256,
        alpha,
    ]
    if fmt == "rgba":
        return np.stack(channels, axis=-1).astype("u1").tobytes()
    if fmt == "bgra":
        return np.stack([channels[i] for i in (2, 1, 0, 3)], axis=-1).astype("u1").tobytes()
    if fmt == "yuva444p10le":
        # Direct planar fixture avoids a software color-conversion dependency.
        planes = [
            (x * 3 + y + n * 23) % 1024,
            (x + y * 7 + 512) % 1024,
            (x * 5 + y * 3 + 511) % 1024,
            (alpha * 1023 + 127) // 255,
        ]
        return np.stack(planes, axis=1).astype("<u2").tobytes()
    raise ValueError("unknown fixture format")


def _blur_boundary_control(
    commands: _Commands,
    ffmpeg: str,
    data: bytes,
    width: int,
    height: int,
    device: str,
    expected: str,
    graph: str,
) -> dict[str, Any]:
    """Diagnostic-only same-device halo control; the unpadded failure stays failed.

    At 64x32 with radius48 every output footprint crosses an image boundary.
    Explicitly edge-pad the input, then compare only the original center. All
    taps influencing that center are in bounds; no oracle or tolerance changes.
    This is not the timed workload and cannot admit the unpadded implementation.
    """
    import numpy as np

    halo = BLUR_RADIUS
    padded_width, padded_height = width + 2 * halo, height + 2 * halo
    values = np.frombuffer(data, "u1").reshape(2, height, width)
    padded = np.pad(values, ((0, 0), (halo, halo), (halo, halo)), mode="edge").tobytes()
    argv = raw_output(
        raw_input(ffmpeg, "gray", padded_width, padded_height, gpu=True, device=device),
        graph,
        "gray",
    )
    argv[1:1] = ["-filter_threads", "1", "-threads", "1"]
    record, observed = commands.run(
        f"blur-boundary-control-{padded_width}x{padded_height}", argv, padded
    )
    control = _command_result(record, expected)
    control.update(
        diagnostic_only=True,
        can_promote_original_case=False,
        halo_pixels=halo,
        upload_geometry=[padded_width, padded_height],
        comparison_geometry=[width, height],
        interpretation="Only cropped-center taps are guaranteed in bounds. A passing control "
        "localizes boundary sensitivity, not a proven driver defect or workload qualification.",
    )
    if control["status"] == "PASS":
        if len(observed) != len(padded):
            control.update(status="NUMERICAL_MISMATCH", explanation="Truncated boundary control")
        else:
            center = np.frombuffer(observed, "u1").reshape(2, padded_height, padded_width)[
                :, halo : halo + height, halo : halo + width
            ]
            control.update(assess_blur(data, center.tobytes(), width, height))
    return control


def _aggregate(cases: dict[str, Any]) -> dict[str, Any]:
    """Any requested case failure blocks this backend, never unrelated backends."""
    statuses = [value["status"] for value in cases.values()]
    priority = (
        "EXECUTION_ERROR",
        "DEVICE_MISMATCH",
        "NUMERICAL_MISMATCH",
        "CAPABILITY_UNAVAILABLE",
        "PASS",
    )
    invalid = [name for name, case in cases.items() if case["status"] not in priority]
    status = (
        "EXECUTION_ERROR"
        if invalid
        else next((s for s in priority if s in statuses), "EXECUTION_ERROR")
    )
    return {
        "status": status,
        "cases": cases,
        "all_cases_passed": bool(cases) and all(s == "PASS" for s in statuses),
        "passed_cases": [name for name, case in cases.items() if case["status"] == "PASS"],
        "nonpassing_cases": [name for name, case in cases.items() if case["status"] != "PASS"],
        "invalid_status_cases": invalid,
        "aggregation_scope": "All requested cases; a failure blocks this backend only. "
        "A passing geometry or diagnostic control cannot erase another geometry's failure.",
        "evidence": [
            f"{name}: {case.get('explanation', case['status'])}" for name, case in cases.items()
        ],
    }


def _unavailable(kind: str, explanation: str) -> dict[str, Any]:
    return {"status": "CAPABILITY_UNAVAILABLE", "capability_kind": kind, "explanation": explanation}


def _command_result(record: dict[str, Any], expected: str | None = None) -> dict[str, Any]:
    result = {
        "status": record["status"],
        "command": record,
        "explanation": "Command completed"
        if record["status"] == "PASS"
        else "External command failed; numeric errors including -38 are not capability proof",
    }
    if record["status"] == "PASS" and expected is not None:
        try:
            result["selected_device"] = selected_device(record["stderr"], expected)
        except ValueError as exc:
            result.update(status="DEVICE_MISMATCH", explanation=str(exc))
    return result


def _exact(
    result: dict[str, Any],
    data: bytes,
    observed: bytes,
    *,
    has_alpha: bool = True,
    hidden_rgb: bool = True,
) -> None:
    result["byte_oracle"] = {
        "expected_bytes": len(data),
        "observed_bytes": len(observed),
        "expected_sha256": _sha(data),
        "observed_sha256": _sha(observed),
        "all_bytes_equal": data == observed,
        "includes_alpha": has_alpha,
        "includes_hidden_rgb": hidden_rgb,
    }
    if data != observed:
        result.update(status="NUMERICAL_MISMATCH", explanation="Every-byte oracle failed")


def _codec(
    commands: _Commands,
    ffmpeg: str,
    ffprobe: str,
    directory: Path,
    codec: str,
    gpu: bool,
    width: int,
    height: int,
    device: str,
    expected: str,
) -> dict[str, Any]:
    fmt = "yuva444p10le" if codec == "prores" else "bgra"
    data = fixture(fmt, width, height)
    name = f"{'gpu' if gpu else 'cpu'}-{codec}-{width}x{height}"
    path = directory / (name + (".mov" if codec == "prores" else ".mkv"))
    argv = raw_input(ffmpeg, fmt, width, height, gpu=gpu, device=device)
    argv += [
        "-filter_threads",
        "1",
        "-vf",
        "format=" + fmt + (",hwupload" if gpu else ""),
        "-frames:v",
        "2",
        "-threads:v",
        "1",
        "-fps_mode",
        "cfr",
        "-r",
        "60/1",
        *codec_options(codec, gpu),
        str(path),
    ]
    record, _ = commands.run(name + "-encode", argv, data)
    result = _command_result(record, expected if gpu else None)
    if result["status"] != "PASS":
        return result
    record, metadata = commands.run(
        name + "-probe",
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-show_frames",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    result["probe_command"] = record
    if record["status"] != "PASS":
        return {**result, "status": "EXECUTION_ERROR", "explanation": "ffprobe failed"}
    try:
        result["timing"] = check_grid(
            json.loads(metadata), width=width, height=height, frames=2, codec=codec
        )
    except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        return {
            **result,
            "status": "NUMERICAL_MISMATCH",
            "explanation": "Codec/alpha-layout/timing oracle: " + str(exc),
        }
    argv = decode_argv(ffmpeg, path, fmt)
    argv[1:1] = ["-threads", "1", "-filter_threads", "1"]
    record, decoded = commands.run(name + "-decode", argv)
    result["decode_command"] = record
    if record["status"] != "PASS":
        return {**result, "status": "EXECUTION_ERROR", "explanation": "Software decode failed"}
    if codec == "ffv1":
        _exact(result, data, decoded)
        result["lossless_rgba_including_hidden_rgb"] = data == decoded
    else:
        import numpy as np

        if len(decoded) != len(data):
            return {
                **result,
                "status": "NUMERICAL_MISMATCH",
                "explanation": "Truncated planar ProRes decode",
            }
        pixels = width * height
        alpha = np.frombuffer(decoded, dtype="<u2").reshape(2, 4, pixels)[:, 3]
        oracle = np.frombuffer(data, dtype="<u2").reshape(2, 4, pixels)[:, 3]
        error = int(np.abs(alpha.astype("i4") - oracle.astype("i4")).max())
        result["alpha_oracle"] = {
            "maximum_10bit_code_error": error,
            "allowed_input_quantization_steps": 1,
            "minimum": int(alpha.min()),
            "maximum": int(alpha.max()),
            "encoder_alpha_bits": 16,
            "all_samples_checked": True,
            "expected_sha256": _sha(oracle.tobytes()),
            "observed_sha256": _sha(alpha.tobytes()),
            "assessment": "EXACT" if error == 0 else "QUANTIZED_VISUAL_ACCEPTANCE_PENDING",
        }
        if error > 1 or alpha.min() != 0 or alpha.max() < 1022:
            result.update(status="NUMERICAL_MISMATCH", explanation="ProRes alpha oracle failed")
    return result


def _qualify(ffmpeg: str, ffprobe: str, root: Path, device: str, expected: str) -> dict[str, Any]:
    commands = _Commands(root)
    inventory: dict[str, Any] = {}
    for name, flag in (
        ("version", "-version"),
        ("buildconf", "-buildconf"),
        ("encoders", "-encoders"),
        ("filters", "-filters"),
        ("hwaccels", "-hwaccels"),
    ):
        record, _ = commands.run("inventory-" + name, [ffmpeg, "-hide_banner", flag], text=True)
        inventory[name] = record
    probe_version, _ = commands.run("inventory-ffprobe-version", [ffprobe, "-version"], text=True)
    inventory["ffprobe_version"] = probe_version

    def version_identity(record: dict[str, Any]) -> tuple[str, str] | None:
        version = re.search(r"^ff(?:mpeg|probe) version (\S+)", record.get("stdout", ""), re.M)
        config = re.search(r"^configuration: (.+)$", record.get("stdout", ""), re.M)
        return (
            (version[1], config[1]) if version and config and record["status"] == "PASS" else None
        )

    ffmpeg_identity, ffprobe_identity = (
        version_identity(inventory["version"]),
        version_identity(probe_version),
    )
    same_build = {
        "status": "PASS"
        if ffmpeg_identity is not None and ffmpeg_identity == ffprobe_identity
        else "EXECUTION_ERROR",
        "ffmpeg_version_and_configuration": ffmpeg_identity,
        "ffprobe_version_and_configuration": ffprobe_identity,
        "explanation": "Observed version/configuration equality; pinned acquisition additionally "
        "verifies both executables and all DLL hashes from the same archive",
    }
    diagnostic = vulkan_diagnostic.collect(root / "device")
    devices = diagnostic.get("loader", {}).get("devices", [])
    diagnostic["expected_device_matches"] = [
        d["index"]
        for d in devices
        if re.search(expected, d["name"], re.I) and not d.get("software_device")
    ]
    result: dict[str, Any] = {
        "schema_version": 1,
        "requested_device": device,
        "expected_device_regex": expected,
        "bounds": {
            "geometries": [list(g) for g in GEOMETRIES],
            "frames_per_case": 2,
            "fps": "60/1",
            "per_command_timeout_seconds": 45,
            "diagnostic_only_on_failed_64x32_blur": {
                "halo_pixels": BLUR_RADIUS,
                "geometry": [160, 128],
            },
        },
        "inventory": inventory,
        "same_build_control": same_build,
        "device_diagnostic": diagnostic,
        "cpu_controls": {},
        "tool_paths": {"ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "tool_sha256": {},
        "qualification_scope": "bounded backend correctness, not performance, full render, "
        "native-NLE acceptance or production visual equivalence",
    }
    for tool, executable in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        resolved = shutil.which(executable)
        if resolved:
            with Path(resolved).open("rb") as source:
                result["tool_sha256"][tool] = hashlib.file_digest(source, "sha256").hexdigest()

    def missing(filters: tuple[str, ...] = (), encoder: str | None = None) -> dict[str, Any] | None:
        categories = ("filters", "hwaccels", "encoders") if encoder else ("filters", "hwaccels")
        for category in categories:
            if inventory[category]["status"] != "PASS":
                return {
                    "status": "EXECUTION_ERROR",
                    "explanation": "Inventory command failed; component absence is unknown",
                    "command": inventory[category],
                }
        if "vulkan" not in inventory["hwaccels"]["stdout"].split():
            return _unavailable("API", "Selected FFmpeg build does not advertise Vulkan")
        for f in filters:
            if not advertised(inventory["filters"]["stdout"], f):
                return _unavailable("FILTER", f"Selected FFmpeg build lacks filter {f}")
        if encoder and not advertised(inventory["encoders"]["stdout"], encoder):
            return _unavailable("ENCODER", f"Selected FFmpeg build lacks encoder {encoder}")
        return None

    backend_cases: dict[str, dict[str, Any]] = {
        name: {} for name in ("transfer", "blur", "prores", "ffv1")
    }
    # The root is explicitly supplied and therefore never uses the OS temp directory.
    with tempfile.TemporaryDirectory(prefix="codec-media-", dir=root) as directory:
        for width, height in GEOMETRIES:
            geometry = f"{width}x{height}"
            for fmt in FORMATS:
                key = geometry + "/" + fmt
                absent = missing(("hwupload", "hwdownload"))
                if absent:
                    backend_cases["transfer"][key] = absent
                    continue
                data = fixture(fmt, width, height)
                argv = raw_output(
                    raw_input(ffmpeg, fmt, width, height, gpu=True, device=device),
                    f"format={fmt},hwupload,hwdownload,format={fmt}",
                    fmt,
                )
                argv[1:1] = ["-filter_threads", "1", "-threads", "1"]
                record, observed = commands.run("transfer-" + key.replace("/", "-"), argv, data)
                case = _command_result(record, expected)
                if case["status"] == "PASS":
                    _exact(
                        case,
                        data,
                        observed,
                        has_alpha=fmt != "gray",
                        hidden_rgb=fmt in ("rgba", "bgra"),
                    )
                backend_cases["transfer"][key] = case
            absent = missing(("hwupload", "hwdownload", "gblur_vulkan"))
            if absent:
                backend_cases["blur"][geometry] = absent
            else:
                data = fixture("gray", width, height)
                graph = (
                    "format=gray,hwupload,gblur_vulkan=sigma=16:sigmaV=16:size=97:sizeV=97:"
                    "planes=1,hwdownload,format=gray"
                )
                argv = raw_output(
                    raw_input(ffmpeg, "gray", width, height, gpu=True, device=device), graph, "gray"
                )
                argv[1:1] = ["-filter_threads", "1", "-threads", "1"]
                record, observed = commands.run("blur-" + geometry, argv, data)
                case = _command_result(record, expected)
                if case["status"] == "PASS":
                    case.update(assess_blur(data, observed, width, height))
                    # A tiny-image halo control can localize OOB tap sensitivity,
                    # but MUST NOT erase or promote the original failed case.
                    if case["status"] == "NUMERICAL_MISMATCH" and (width, height) == (64, 32):
                        case["boundary_control"] = _blur_boundary_control(
                            commands, ffmpeg, data, width, height, device, expected, graph
                        )
                backend_cases["blur"][geometry] = case
            for codec, cpu_encoder, gpu_encoder in (
                ("prores", "prores_ks", "prores_ks_vulkan"),
                ("ffv1", "ffv1", "ffv1_vulkan"),
            ):
                control_key = codec + "/" + geometry
                if inventory["encoders"]["status"] != "PASS":
                    result["cpu_controls"][control_key] = {
                        "status": "EXECUTION_ERROR",
                        "explanation": "CPU encoder inventory failed",
                    }
                elif not advertised(inventory["encoders"]["stdout"], cpu_encoder):
                    result["cpu_controls"][control_key] = _unavailable("ENCODER", cpu_encoder)
                else:
                    result["cpu_controls"][control_key] = _codec(
                        commands,
                        ffmpeg,
                        ffprobe,
                        Path(directory),
                        codec,
                        False,
                        width,
                        height,
                        device,
                        expected,
                    )
                absent = missing(("hwupload",), gpu_encoder)
                backend_cases[codec][geometry] = absent or _codec(
                    commands,
                    ffmpeg,
                    ffprobe,
                    Path(directory),
                    codec,
                    True,
                    width,
                    height,
                    device,
                    expected,
                )
    # Device absence needs two independent observations: an explicit FFmpeg
    # name-selection refusal and a successful loader enumeration without a
    # matching non-software device. A numeric code (-19, -38, etc.) is not proof.
    for cases in backend_cases.values():
        for case in cases.values():
            record = case.get("command", {})
            if (
                case["status"] == "EXECUTION_ERROR"
                and diagnostic.get("loader", {}).get("status") == "PASS"
                and not diagnostic["expected_device_matches"]
                and re.search(
                    r"Unable to find device|No physical devices found",
                    record.get("stderr", ""),
                    re.I,
                )
            ):
                case.update(
                    status="CAPABILITY_UNAVAILABLE",
                    capability_kind="DEVICE",
                    explanation="FFmpeg explicitly refused the requested device and the actual "
                    "Vulkan loader enumeration found no matching hardware device; command and "
                    "diagnostic evidence retained, no software fallback",
                )
    result.update({backend: _aggregate(cases) for backend, cases in backend_cases.items()})
    result["commands"] = commands.records
    result["cpu_controls_status"] = _aggregate(result["cpu_controls"])["status"]
    result["all_backends_passed"] = (
        all(result[b]["status"] == "PASS" for b in backend_cases)
        and result["cpu_controls_status"] == "PASS"
        and same_build["status"] == "PASS"
    )
    return result


def qualify(
    ffmpeg: str, ffprobe: str, root: Path, device: str = "RTX 3090", expected: str = r"RTX\s*3090"
) -> dict[str, Any]:
    """Execute all independent bounded cases; root must be a fresh owned directory.

    Malformed arguments and occupied evidence roots are caller errors. External
    failures are per-case results, not exceptions or unsupported claims. Explicit
    executable resolution is frozen before any invocation.
    """
    if not re.fullmatch(r"[A-Za-z0-9 ._-]+", device):
        raise ValueError("device must be a name substring or numeric index")
    re.compile(expected)
    if not expected:
        raise ValueError("expected device regex must not be empty")
    # Freeze PATH lookup once; a missing executable remains an execution error.
    ffmpeg, ffprobe = shutil.which(ffmpeg) or ffmpeg, shutil.which(ffprobe) or ffprobe
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("qualification evidence root must be empty")
    result = _qualify(ffmpeg, ffprobe, root, device, expected)
    (root / "qualification.json").write_text(json.dumps(result, indent=2, default=str))
    return result
