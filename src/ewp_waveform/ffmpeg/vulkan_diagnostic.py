"""Read-only, bounded Vulkan loader diagnostics (Linux and native Windows).

No SDK, vulkaninfo, GPU allocation, stack repair, or optional Python binding is
required. The public collector runs the C ABI calls in a disposable subprocess:
a broken ICD must not kill the qualification runner. Format support is evidence,
not a substitute for FFmpeg execution on the explicitly selected device.
"""

from __future__ import annotations

import ctypes as c
import ctypes.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

FORMATS = {
    "VK_FORMAT_R8_UNORM": 9,  # gray; one image per 8-bit plane
    "VK_FORMAT_R8_UINT": 13,
    "VK_FORMAT_R8G8B8A8_UNORM": 37,  # FFmpeg 9 maps both rgba and bgra to this
    "VK_FORMAT_R8G8B8A8_UINT": 41,
    "VK_FORMAT_B8G8R8A8_UNORM": 44,  # alternative driver format, not FFmpeg 9 BGRA mapping
    "VK_FORMAT_R16_UNORM": 70,  # yuva444p10le: four independent 16-bit images
    "VK_FORMAT_R16_UINT": 74,
}
FEATURE_FLAGS = {
    "SAMPLED_IMAGE": 0x1,
    "STORAGE_IMAGE": 0x2,
    "STORAGE_IMAGE_ATOMIC": 0x4,
    "SAMPLED_IMAGE_FILTER_LINEAR": 0x1000,
    "TRANSFER_SRC": 0x4000,
    "TRANSFER_DST": 0x8000,
    "STORAGE_READ_WITHOUT_FORMAT": 0x80000000,
    "STORAGE_WRITE_WITHOUT_FORMAT": 0x100000000,
}


class ApplicationInfo(c.Structure):
    _fields_ = [
        ("sType", c.c_uint32),
        ("pNext", c.c_void_p),
        ("pApplicationName", c.c_char_p),
        ("applicationVersion", c.c_uint32),
        ("pEngineName", c.c_char_p),
        ("engineVersion", c.c_uint32),
        ("apiVersion", c.c_uint32),
    ]


class InstanceCreateInfo(c.Structure):
    _fields_ = [
        ("sType", c.c_uint32),
        ("pNext", c.c_void_p),
        ("flags", c.c_uint32),
        ("pApplicationInfo", c.POINTER(ApplicationInfo)),
        ("enabledLayerCount", c.c_uint32),
        ("ppEnabledLayerNames", c.c_void_p),
        ("enabledExtensionCount", c.c_uint32),
        ("ppEnabledExtensionNames", c.c_void_p),
    ]


class Extension(c.Structure):
    _fields_ = [("name", c.c_char * 256), ("version", c.c_uint32)]


class Properties(c.Structure):
    # Only the fixed ABI prefix is interpreted; oversized, aligned storage safely
    # receives the remaining VkPhysicalDeviceLimits/SparseProperties structure.
    _fields_ = [
        ("apiVersion", c.c_uint32),
        ("driverVersion", c.c_uint32),
        ("vendorID", c.c_uint32),
        ("deviceID", c.c_uint32),
        ("deviceType", c.c_uint32),
        ("deviceName", c.c_char * 256),
        ("pipelineCacheUUID", c.c_ubyte * 16),
        ("remaining", c.c_uint64 * 512),
    ]


class DriverProperties(c.Structure):
    _fields_ = [
        ("sType", c.c_uint32),
        ("pNext", c.c_void_p),
        ("driverID", c.c_uint32),
        ("driverName", c.c_char * 256),
        ("driverInfo", c.c_char * 256),
        ("conformanceVersion", c.c_ubyte * 4),
    ]


class Properties2(c.Structure):
    _fields_ = [("sType", c.c_uint32), ("pNext", c.c_void_p), ("properties", Properties)]


class FormatProperties(c.Structure):
    _fields_ = [("linear", c.c_uint32), ("optimal", c.c_uint32), ("buffer", c.c_uint32)]


class FormatProperties2(c.Structure):
    _fields_ = [("sType", c.c_uint32), ("pNext", c.c_void_p), ("properties", FormatProperties)]


class FormatProperties3(c.Structure):
    _fields_ = [
        ("sType", c.c_uint32),
        ("pNext", c.c_void_p),
        ("linear", c.c_uint64),
        ("optimal", c.c_uint64),
        ("buffer", c.c_uint64),
    ]


class ImageProperties(c.Structure):
    _fields_ = [
        ("maxExtent", c.c_uint32 * 3),
        ("maxMipLevels", c.c_uint32),
        ("maxArrayLayers", c.c_uint32),
        ("sampleCounts", c.c_uint32),
        ("maxResourceSize", c.c_uint64),
    ]


def api_version(value: int) -> str:
    return f"{(value >> 22) & 127}.{(value >> 12) & 1023}.{value & 4095}"


def _text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _flags(value: int) -> dict[str, Any]:
    return {"value": value, "names": [n for n, mask in FEATURE_FLAGS.items() if value & mask]}


def _bind(lib: Any, name: str, restype: Any, args: list[Any]) -> Any:
    function = getattr(lib, name)
    function.restype = restype
    function.argtypes = args
    return function


def _enumerate(function: Any, prefix: list[Any], item: Any) -> list[Any]:
    for _ in range(3):
        count = c.c_uint32()
        result = function(*prefix, c.byref(count), None)
        if result not in (0, 5):
            raise RuntimeError(f"enumeration VkResult={result}")
        if count.value > 4096:
            raise RuntimeError("implausible Vulkan enumeration count")
        values = (item * count.value)()
        result = function(*prefix, c.byref(count), values)
        if result == 0:
            return list(values[: count.value])
        if result != 5:
            raise RuntimeError(f"enumeration VkResult={result}")
    raise RuntimeError("Vulkan enumeration remained VK_INCOMPLETE")


def inspect_loader() -> dict[str, Any]:
    """Child-process entry point; use collect() from application code."""
    library = "vulkan-1.dll" if os.name == "nt" else ctypes.util.find_library("vulkan")
    if not library:
        return {"status": "CAPABILITY_UNAVAILABLE", "evidence": "Vulkan loader not found"}
    try:
        # VKAPI_CALL is stdcall on Win32 (Win64 has a unified calling convention).
        windows_loader: Any = c
        lib = windows_loader.WinDLL(library) if os.name == "nt" else c.CDLL(library)
    except OSError as exc:
        return {"status": "CAPABILITY_UNAVAILABLE", "loader": library, "evidence": str(exc)}
    loader_version = c.c_uint32(1 << 22)
    if hasattr(lib, "vkEnumerateInstanceVersion"):
        result = _bind(lib, "vkEnumerateInstanceVersion", c.c_int32, [c.c_void_p])(
            c.byref(loader_version)
        )
        if result:
            return {"status": "EXECUTION_ERROR", "VkResult": result, "loader": library}
    app = ApplicationInfo(
        sType=0,
        pApplicationName=b"ewp-readonly-diagnostic",
        apiVersion=min(loader_version.value, (1 << 22) | (3 << 12)),
    )
    create = InstanceCreateInfo(sType=1, pApplicationInfo=c.pointer(app))
    instance = c.c_void_p()
    result = _bind(lib, "vkCreateInstance", c.c_int32, [c.c_void_p, c.c_void_p, c.c_void_p])(
        c.byref(create), None, c.byref(instance)
    )
    report: dict[str, Any] = {
        "loader": library,
        "loader_api_version": api_version(loader_version.value),
        "requested_instance_api_version": api_version(app.apiVersion),
        "vkCreateInstance_result": result,
        "devices": [],
    }
    if result:
        return {**report, "status": "EXECUTION_ERROR"}
    try:
        physical = _bind(
            lib, "vkEnumeratePhysicalDevices", c.c_int32, [c.c_void_p, c.c_void_p, c.c_void_p]
        )
        extensions = _bind(
            lib,
            "vkEnumerateDeviceExtensionProperties",
            c.c_int32,
            [c.c_void_p, c.c_char_p, c.c_void_p, c.c_void_p],
        )
        properties = _bind(lib, "vkGetPhysicalDeviceProperties", None, [c.c_void_p, c.c_void_p])
        formats = _bind(
            lib, "vkGetPhysicalDeviceFormatProperties", None, [c.c_void_p, c.c_int32, c.c_void_p]
        )
        images = _bind(
            lib,
            "vkGetPhysicalDeviceImageFormatProperties",
            c.c_int32,
            [c.c_void_p, c.c_int32, c.c_int32, c.c_int32, c.c_uint32, c.c_uint32, c.c_void_p],
        )
        for handle in _enumerate(physical, [instance], c.c_void_p):
            p = Properties()
            properties(handle, c.byref(p))
            exts = {
                _text(e.name): e.version for e in _enumerate(extensions, [handle, None], Extension)
            }
            device: dict[str, Any] = {
                "index": len(report["devices"]),
                "name": _text(p.deviceName),
                "api_version": api_version(p.apiVersion),
                "api_version_raw": p.apiVersion,
                "driver_version_raw": p.driverVersion,
                "vendor_id": p.vendorID,
                "device_id": p.deviceID,
                "device_type": p.deviceType,
                "software_device": p.deviceType == 4,
                "extensions": dict(sorted(exts.items())),
                "formats": {},
            }
            if hasattr(lib, "vkGetPhysicalDeviceProperties2") and (
                p.apiVersion >= ((1 << 22) | (2 << 12)) or "VK_KHR_driver_properties" in exts
            ):
                driver = DriverProperties(sType=1000196000)
                pp = Properties2(sType=1000059001, pNext=c.addressof(driver))
                _bind(lib, "vkGetPhysicalDeviceProperties2", None, [c.c_void_p, c.c_void_p])(
                    handle, c.byref(pp)
                )
                device["driver"] = {
                    "id": driver.driverID,
                    "name": _text(driver.driverName),
                    "info": _text(driver.driverInfo),
                    "conformance": list(driver.conformanceVersion),
                }
            feature_values = (c.c_uint32 * 55)()
            _bind(lib, "vkGetPhysicalDeviceFeatures", None, [c.c_void_p, c.c_void_p])(
                handle, c.byref(feature_values)
            )
            device["core_features"] = {
                key: bool(feature_values[index])
                for key, index in {
                    "shaderStorageImageExtendedFormats": 29,
                    "shaderStorageImageReadWithoutFormat": 31,
                    "shaderStorageImageWriteWithoutFormat": 32,
                    "shaderFloat64": 39,
                    "shaderInt64": 40,
                    "shaderInt16": 41,
                }.items()
            }
            device["core_features_raw"] = list(feature_values)
            for name, number in FORMATS.items():
                fp = FormatProperties()
                formats(handle, number, c.byref(fp))
                fmt: dict[str, Any] = {
                    "vk_format": number,
                    "linear_tiling": _flags(fp.linear),
                    "optimal_tiling": _flags(fp.optimal),
                    "buffer": _flags(fp.buffer),
                    "image_queries": {},
                }
                if hasattr(lib, "vkGetPhysicalDeviceFormatProperties2") and (
                    p.apiVersion >= ((1 << 22) | (3 << 12))
                    or "VK_KHR_format_feature_flags2" in exts
                ):
                    fp3 = FormatProperties3(sType=1000360000)
                    fp2 = FormatProperties2(sType=1000059002, pNext=c.addressof(fp3))
                    _bind(
                        lib,
                        "vkGetPhysicalDeviceFormatProperties2",
                        None,
                        [c.c_void_p, c.c_int32, c.c_void_p],
                    )(handle, number, c.byref(fp2))
                    fmt["format_properties_3"] = {
                        "linear_tiling": _flags(fp3.linear),
                        "optimal_tiling": _flags(fp3.optimal),
                        "buffer": _flags(fp3.buffer),
                    }
                # Actual usage-combination queries, not just individual feature bits.
                for tiling, tiling_id in (("optimal", 0), ("linear", 1)):
                    for usage, usage_flags in (("transfer", 3), ("transfer_sampled_storage", 15)):
                        ip = ImageProperties()
                        code = images(handle, number, 1, tiling_id, usage_flags, 0, c.byref(ip))
                        fmt["image_queries"][f"{tiling}_{usage}"] = {
                            "VkResult": code,
                            "usage_flags": usage_flags,
                            "max_extent": list(ip.maxExtent) if code == 0 else None,
                            "max_resource_size": ip.maxResourceSize if code == 0 else None,
                        }
                device["formats"][name] = fmt
            report["devices"].append(device)
        report["status"] = "PASS" if report["devices"] else "CAPABILITY_UNAVAILABLE"
        return report
    finally:
        _bind(lib, "vkDestroyInstance", None, [c.c_void_p, c.c_void_p])(instance, None)


def collect(root: Path) -> dict[str, Any]:
    """Preserve actual API/extension/format and OS evidence; never diagnose by name alone."""
    root.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(Path(__file__).resolve()), "--child"]
    stdout, stderr = root / "vulkan-loader.json", root / "vulkan-loader.stderr"
    result: dict[str, Any] = {
        "argv": argv,
        "platform": platform.platform(),
        "os_release": None,
        "environment": {
            k: os.environ[k]
            for k in (
                "VK_ICD_FILENAMES",
                "VK_DRIVER_FILES",
                "VK_LOADER_DEBUG",
                "MESA_D3D12_DEFAULT_ADAPTER_NAME",
            )
            if k in os.environ
        },
    }
    if Path("/etc/os-release").is_file():
        result["os_release"] = Path("/etc/os-release").read_text(errors="replace")
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            proc = subprocess.run(argv, stdout=out, stderr=err, timeout=30, check=False)
        result["returncode"] = proc.returncode
        result["loader"] = (
            json.loads(stdout.read_text())
            if proc.returncode == 0
            else {"status": "EXECUTION_ERROR", "evidence": "Vulkan diagnostic child failed"}
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result["loader"] = {"status": "EXECUTION_ERROR", "evidence": str(exc)}
    result["stderr_path"] = str(stderr)
    result["stderr"] = stderr.read_text(errors="replace") if stderr.exists() else ""
    devices = result["loader"].get("devices", [])
    dzn = any(
        "dzn" in json.dumps(d.get("driver", {})).lower()
        or "dozen" in json.dumps(d.get("driver", {})).lower()
        for d in devices
    )
    result["wsl_dzn_hypothesis"] = {
        "status": "UNCONFIRMED",
        "dzn_driver_observed": dzn,
        "explanation": "Driver identity, API, extensions and format queries are observations; "
        "neither WSL nor -38 proves a dzn root cause. Compare the selected device's actual "
        "format/usage support and failing FFmpeg stage; no stack changes attempted.",
    }
    (root / "diagnostic.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(inspect_loader()))
    except Exception as exc:
        print(json.dumps({"status": "EXECUTION_ERROR", "evidence": repr(exc)}))
