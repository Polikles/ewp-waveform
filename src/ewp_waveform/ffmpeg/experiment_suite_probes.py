"""Real bounded target probes. Inventory absence may skip; command bugs never do."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ewp_waveform.ffmpeg.experiment_suite import (
    codec_options,
    raw_input,
    raw_output,
    selected_device,
)
from ewp_waveform.ffmpeg.experiment_suite_validation import check_grid, decode_argv
from ewp_waveform.ffmpeg.experiments import record_command


def invoke(
    argv: list[str], log: Path, name: str, data: bytes | None = None, expected: str | None = None
) -> bytes:
    record_command(log, argv, phase=name + "-STARTED")
    result = subprocess.run(argv, input=data, capture_output=True, timeout=60, check=False)
    (log.parent / (name + ".stderr")).write_bytes(result.stderr)
    record_command(
        log,
        [str(result.returncode), hashlib.sha256(result.stdout).hexdigest()],
        phase=name + "-FINISHED",
    )
    if result.returncode:
        raise RuntimeError(f"{name}: failed command; diagnostics retained, not unsupported")
    if expected is not None:
        selected_device(result.stderr.decode(errors="replace"), expected)
    return result.stdout


def advertised(text: str, component: str) -> bool:
    return any(component in line.split()[:2] for line in text.splitlines())


def inventory(ffmpeg: str, root: Path) -> dict[str, Any]:
    log = root / "commands.jsonl"
    texts = {}
    for name, flag in (
        ("version", "-version"),
        ("buildconf", "-buildconf"),
        ("encoders", "-encoders"),
        ("filters", "-filters"),
        ("hwaccels", "-hwaccels"),
    ):
        value = invoke([ffmpeg, "-hide_banner", flag], log, "inventory-" + name)
        texts[name] = value.decode(errors="replace")
        (root / (name + ".txt")).write_text(texts[name])
    return texts


def probe_geometry(
    ffmpeg: str,
    ffprobe: str,
    root: Path,
    device: str,
    expected: str,
    width: int,
    height: int,
    capabilities: dict[str, bool],
) -> dict[str, Any]:
    root.mkdir()
    log = root / "commands.jsonl"
    pixels = width * height
    rgba = bytes(
        v
        for n in range(2)
        for y in range(height)
        for x in range(width)
        for v in (
            199,
            230,
            236,
            0 if x < width // 8 else 255 if x > width * 7 // 8 else (x + 7 * y + n * 11) % 256,
        )
    )
    gray = bytes(
        255
        if width // 2 - 4 + n <= x < width // 2 + 5 + n and height // 2 - 4 <= y < height // 2 + 4
        else 0
        for n in range(2)
        for y in range(height)
        for x in range(width)
    )
    planar = invoke(
        raw_output(raw_input(ffmpeg, "rgba", width, height), "format=yuva444p10le", "yuva444p10le"),
        log,
        "to-planar",
        rgba,
    )
    if len(planar) != pixels * 8 * 2:
        raise ValueError("invalid planar reference")
    bgra = bytes(
        v for i in range(0, len(rgba), 4) for v in (rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3])
    )
    results: dict[str, Any] = {}
    for fmt, data in (("gray", gray), ("rgba", rgba), ("bgra", bgra), ("yuva444p10le", planar)):
        observed = invoke(
            raw_output(
                raw_input(ffmpeg, fmt, width, height, gpu=True, device=device),
                f"format={fmt},hwupload,hwdownload,format={fmt}",
                fmt,
            ),
            log,
            "transfer-" + fmt,
            data,
            expected,
        )
        if data != observed:
            raise ValueError("non-exact matching-format transfer: " + fmt)
        results["transfer-" + fmt] = {"status": "PASS", "sha256": hashlib.sha256(data).hexdigest()}
    if capabilities["blur"]:
        graph = (
            "format=gray,hwupload,"
            "gblur_vulkan=sigma=16:sigmaV=16:size=97:sizeV=97:planes=1,"
            "hwdownload,format=gray"
        )
        value = invoke(
            raw_output(
                raw_input(ffmpeg, "gray", width, height, gpu=True, device=device), graph, "gray"
            ),
            log,
            "blur-gray",
            gray,
            expected,
        )
        if len(value) != len(gray) or value == gray or not 0 < max(value) < 255:
            raise ValueError("mono blur did not actually execute")
        results["blur"] = {"status": "PASS", "sha256": hashlib.sha256(value).hexdigest()}
    else:
        results["blur"] = {"status": "CAPABILITY_UNAVAILABLE", "evidence": "filter absent"}
    for codec in ("prores", "ffv1"):
        if not capabilities[codec]:
            results[codec] = {"status": "CAPABILITY_UNAVAILABLE", "evidence": "encoder absent"}
            continue
        data, fmt = (planar, "yuva444p10le") if codec == "prores" else (bgra, "bgra")
        decoded_alpha: list[str] = []
        for gpu in (False, True):
            name = ("gpu-" if gpu else "cpu-") + codec
            path = root / (name + (".mov" if codec == "prores" else ".mkv"))
            argv = raw_input(ffmpeg, fmt, width, height, gpu=gpu, device=device)
            argv += [
                "-vf",
                "format=" + fmt + (",hwupload" if gpu else ""),
                "-frames:v",
                "2",
                "-fps_mode",
                "cfr",
                "-r",
                "60/1",
                *codec_options(codec, gpu),
                str(path),
            ]
            invoke(argv, log, name, data, expected if gpu else None)
            meta = json.loads(
                invoke(
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
                    log,
                    name + "-probe",
                )
            )
            check_grid(meta, width=width, height=height, frames=2, codec=codec)
            raw = invoke(
                decode_argv(ffmpeg, path, fmt if codec == "prores" else "rgba"),
                log,
                name + "-decode",
            )
            if codec == "prores":

                def alpha(value: bytes) -> bytes:
                    return b"".join(
                        value[i + pixels * 6 : i + pixels * 8]
                        for i in range(0, len(value), pixels * 8)
                    )

                if len(raw) != len(planar):
                    raise ValueError(name + ": truncated planar alpha decode")
                import numpy as np

                aa = np.frombuffer(alpha(raw), dtype="<u2").astype(np.int32)
                oracle = np.frombuffer(alpha(planar), dtype="<u2").astype(np.int32)
                error = int(abs(aa - oracle).max())
                if int(aa.min()) != 0 or int(aa.max()) < 1022 or error > 1:
                    raise ValueError(name + ": alpha loss violates 10-bit input precision contract")
                results[name + "-alpha"] = {
                    "exact": error == 0,
                    "maximum_10bit_code_error": error,
                    "allowed_input_quantization_steps": 1,
                    "encoder_alpha_bits": 16,
                    "assessment": "EXACT" if error == 0 else "QUANTIZED_VISUAL_STUDIO_PENDING",
                }
                decoded_alpha.append(hashlib.sha256(alpha(raw)).hexdigest())
            elif raw != rgba:
                raise ValueError(name + ": exact RGBA oracle failed (hidden RGB included)")
        results[codec] = {
            "status": "PASS",
            "cpu_gpu_alpha_sha256": decoded_alpha,
            "cpu_gpu_alpha_equal": decoded_alpha[0] == decoded_alpha[1] if decoded_alpha else True,
            "lossless_rgba": codec == "ffv1",
            "studio": "PENDING",
        }
    if (width, height) == (1400, 280):
        from ewp_waveform.ffmpeg.ribbon import ribbon_graph

        iw, ih = (width + 100) * 2, height + 100
        mask = bytes(
            255 if iw // 3 + n <= x < iw * 2 // 3 + n and ih // 3 < y < ih * 2 // 3 else 0
            for n in range(2)
            for y in range(ih)
            for x in range(iw)
        )
        finishes = []
        for candidate in (None, "TRANSFER"):
            gpu = candidate is not None
            graph = ribbon_graph(
                width=width,
                height=height,
                overscan=50,
                supersample=2,
                pix_fmt="gray",
                color="#C7E6EC",
                glow=16.0,
                finish=(0.45, True, 1.0, 0.96, 0.55),
                suite_candidate=candidate,
            )
            argv = [
                *raw_input(ffmpeg, "gray", iw, ih, gpu=gpu, device=device),
                "-filter_complex",
                graph,
                "-map",
                "[vout]",
                "-frames:v",
                "2",
                "-c:v",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "-f",
                "rawvideo",
                "pipe:1",
            ]
            finishes.append(
                invoke(argv, log, "finish-" + str(candidate), mask, expected if gpu else None)
            )
        if finishes[0] != finishes[1] or len(finishes[0]) != width * height * 4 * 2:
            raise ValueError("production topology preencode transfer/CPU finishing mismatch")
        results["production-finish-transfer"] = {
            "status": "PASS",
            "exact_rgba": True,
            "sha256": hashlib.sha256(finishes[0]).hexdigest(),
        }
    return results


def runtime_preflight(
    ffmpeg: str, ffprobe: str, root: Path, device: str, expected: str, gpu: bool
) -> dict[str, Any]:
    texts = inventory(ffmpeg, root)
    log = root / "commands.jsonl"
    # These are metadata observations, not Vulkan admission.
    import platform

    is_target = "microsoft" in platform.release().lower()
    observations = [("uname", ["uname", "-a"])]
    if gpu and is_target:
        observations += [
            ("nvidia-smi", ["nvidia-smi", "-q"]),
            ("vulkaninfo", ["vulkaninfo", "--summary"]),
        ]
    for tool, args in observations:
        import shutil

        if shutil.which(tool):
            proc = subprocess.run(args, capture_output=True, timeout=30, check=False)
            (root / (tool + ".txt")).write_bytes(proc.stdout + proc.stderr)
    cpu = {}
    for codec in ("prores_ks", "ffv1"):
        cpu[codec] = advertised(texts["encoders"], codec)
    caps = {
        "blur": advertised(texts["filters"], "gblur_vulkan"),
        "prores": advertised(texts["encoders"], "prores_ks_vulkan"),
        "ffv1": advertised(texts["encoders"], "ffv1_vulkan"),
    }
    result: dict[str, Any] = {
        "advertised_cpu": cpu,
        "advertised_gpu": caps,
        "gpu_status": "NOT_REQUESTED",
        "capabilities": {},
    }
    # Always exercise a tiny software encode/decode, not help-only CPU admission.
    rgba = (
        bytes(
            v
            for y in range(32)
            for x in range(64)
            for v in (199, 230, 236, 0 if x < 8 else (255 if x > 55 else x * 4))
        )
        * 2
    )
    path = root / "cpu-smoke.mkv"
    argv = [
        *raw_input(ffmpeg, "rgba", 64, 32),
        "-vf",
        "format=bgra",
        "-frames:v",
        "2",
        *codec_options("ffv1", False),
        str(path),
    ]
    invoke(argv, log, "cpu-smoke", rgba)
    if invoke(decode_argv(ffmpeg, path), log, "cpu-smoke-decode") != rgba:
        raise ValueError("software FFV1 smoke mismatch")
    result["cpu_status"] = "PASS"
    if not gpu:
        return result
    import platform

    if "microsoft" not in platform.release().lower():
        result.update(gpu_status="NOT_TARGET", evidence="WSL GPU probes not run on this host")
        return result
    if not re.search(r"^vulkan\s*$", texts["hwaccels"], re.M):
        result.update(gpu_status="API_UNAVAILABLE", evidence="selected build lacks Vulkan hwaccel")
        return result
    if not all(advertised(texts["filters"], f) for f in ("hwupload", "hwdownload")):
        result.update(gpu_status="CAPABILITY_UNAVAILABLE", evidence="upload/download filter absent")
        return result
    # Failures below remain FAILED, never inferred unsupported or silently CPU-fallback.
    geometries = {}
    for w, h in ((64, 32), (1400, 280)):
        geometries[f"{w}x{h}"] = probe_geometry(
            ffmpeg, ffprobe, root / f"probe-{w}x{h}", device, expected, w, h, caps
        )
    result.update(gpu_status="PASS", capabilities=geometries)
    return result
