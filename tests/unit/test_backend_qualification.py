"""Deterministic orchestration/oracle tests; fake records are not GPU evidence."""

from __future__ import annotations

import ctypes.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ewp_waveform.ffmpeg import backend_qualification as bq
from ewp_waveform.ffmpeg import vulkan_diagnostic as vd


@pytest.mark.parametrize(
    "line",
    [
        "Using device: NVIDIA GeForce RTX 3090",
        "[Vulkan @ 0x123] Device 0 selected: NVIDIA GeForce RTX 3090",
    ],
)
def test_selected_device_actual_log_spellings(line: str) -> None:
    assert "RTX 3090" in bq.selected_device(line, r"RTX\s*3090")


@pytest.mark.parametrize(
    "text",
    [
        "GPU listing:\n0: NVIDIA GeForce RTX 3090",
        "Device 0 selected: llvmpipe (software RTX 3090)",
        "Using device: NVIDIA RTX 4090",
        "Device 0 selected: NVIDIA RTX 3090\nUsing device: lavapipe CPU",
    ],
)
def test_selected_device_rejects_listings_wrong_and_software(text: str) -> None:
    with pytest.raises(ValueError):
        bq.selected_device(text, r"RTX\s*3090")


def test_fixtures_include_hidden_rgb_and_10bit_alpha() -> None:
    rgba = np.frombuffer(bq.fixture("rgba", 64, 32), "u1").reshape(2, 32, 64, 4)
    bgra = np.frombuffer(bq.fixture("bgra", 64, 32), "u1").reshape(2, 32, 64, 4)
    assert np.array_equal(rgba[:, :, :, [2, 1, 0, 3]], bgra)
    assert rgba[:, :, :8, 3].max() == 0
    assert rgba[:, :, :8, :3].max() > 0
    assert rgba[:, :, -8:, 3].min() == 255
    assert not np.array_equal(rgba[0], rgba[1])
    planar = np.frombuffer(bq.fixture("yuva444p10le", 64, 32), "<u2").reshape(2, 4, 32, 64)
    assert planar.max() <= 1023
    assert planar[:, 3, :, :8].max() == 0
    assert planar[:, 3, :, -8:].min() == 1023


def test_exact_oracle_checks_transparent_hidden_rgb_and_all_bytes() -> None:
    data = bq.fixture("rgba", 64, 32)
    mutated = bytearray(data)
    assert data[3] == 0
    mutated[0] ^= 1
    case: dict[str, Any] = {"status": "PASS"}
    bq._exact(case, data, bytes(mutated))
    assert case["status"] == "NUMERICAL_MISMATCH"
    assert case["byte_oracle"]["includes_hidden_rgb"]


def test_blur_oracle_constant_preservation_and_real_smoothing() -> None:
    assert bq.blur_oracle(bytes([91]) * (64 * 32 * 2), 64, 32) == bytes([91]) * (64 * 32 * 2)
    data = bq.fixture("gray", 64, 32)
    value = bq.blur_oracle(data, 64, 32)
    assert len(value) == len(data) and value != data
    assert 0 < max(value) < 255
    assert np.frombuffer(value, "u1").reshape(2, 32, 64)[0, 16, 32] > 0


class FakeCommands:
    """Invented unit-test process records; production uses subprocess.run."""

    transfer_error = False
    bad_blur = False
    missing_prores = False
    failure_text = "auto_scale failed: Function not implemented (-38)"
    wrong_timing = False
    mutate_decode = False
    dimensions: tuple[int, int] = (64, 32)

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: list[dict[str, Any]] = []

    def run(
        self, name: str, argv: list[str], data: bytes | None = None, *, text: bool = False
    ) -> tuple[dict[str, Any], bytes]:
        output = b""
        code = 0
        stderr = "Device 0 selected: NVIDIA GeForce RTX 3090"
        if name.startswith("inventory-"):
            if name == "inventory-filters":
                output = b"... hwupload\n... hwdownload\n... gblur_vulkan\n"
            elif name == "inventory-encoders":
                output = b"V... ffv1\nV... ffv1_vulkan\nV... prores_ks\n"
                if not self.missing_prores:
                    output += b"V... prores_ks_vulkan\n"
            elif name == "inventory-hwaccels":
                output = b"vulkan\n"
            elif name in ("inventory-version", "inventory-ffprobe-version"):
                tool = "ffprobe" if "ffprobe" in name else "ffmpeg"
                output = f"{tool} version TEST\nconfiguration: --enable-vulkan\n".encode()
        elif name.startswith("transfer-"):
            if self.transfer_error:
                code, stderr = 218, self.failure_text
            else:
                output = data or b""
        elif name.startswith("blur-"):
            width, height = map(int, name.split("-")[-1].split("x"))
            output = (data or b"") if self.bad_blur else bq.blur_oracle(data or b"", width, height)
            assert output is not None
        elif name.endswith("-probe"):
            codec = "prores" if "prores" in name else "ffv1"
            width, height = self.dimensions
            output = json.dumps(
                {
                    "streams": [
                        {
                            "time_base": "1/15360",
                            "avg_frame_rate": "60/1",
                            "width": width,
                            "height": height,
                            "codec_name": codec,
                            "profile": "4444",
                            "pix_fmt": "yuva444p12le" if codec == "prores" else "bgra",
                        }
                    ],
                    "frames": [
                        {"best_effort_timestamp": 0},
                        {"best_effort_timestamp": 777 if self.wrong_timing else 256},
                    ],
                }
            ).encode()
        elif name.endswith("-decode"):
            fmt = "yuva444p10le" if "prores" in name else "bgra"
            output = bq.fixture(fmt, *self.dimensions)
            if self.mutate_decode:
                output = bytes([output[0] ^ 1]) + output[1:]
        record = {
            "name": name,
            "argv": argv,
            "status": "PASS" if code == 0 else "EXECUTION_ERROR",
            "returncode": code,
            "stderr": stderr,
            "excerpts": [stderr],
            "stdout": output.decode(errors="replace") if text else "",
        }
        self.records.append(record)
        return record, output


def setup_fake(monkeypatch: pytest.MonkeyPatch, *, devices: bool = True) -> None:
    monkeypatch.setattr(bq, "GEOMETRIES", ((64, 32),))
    monkeypatch.setattr(bq, "_Commands", FakeCommands)
    monkeypatch.setattr(FakeCommands, "transfer_error", False)
    monkeypatch.setattr(FakeCommands, "bad_blur", False)
    monkeypatch.setattr(FakeCommands, "missing_prores", False)
    monkeypatch.setattr(FakeCommands, "wrong_timing", False)
    monkeypatch.setattr(FakeCommands, "mutate_decode", False)
    monkeypatch.setattr(
        vd,
        "collect",
        lambda root: {
            "loader": {
                "status": "PASS",
                "devices": [{"index": 0, "name": "NVIDIA RTX 3090"}]
                if devices
                else [{"index": 0, "name": "llvmpipe", "software_device": True}],
            }
        },
    )


def test_all_backends_execute_and_validate_independently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["all_backends_passed"]
    assert all(result[k]["status"] == "PASS" for k in ("transfer", "blur", "prores", "ffv1"))
    assert result["cpu_controls_status"] == "PASS"
    assert result["ffv1"]["cases"]["64x32"]["byte_oracle"]["all_bytes_equal"]
    assert result["prores"]["cases"]["64x32"]["alpha_oracle"]["maximum_10bit_code_error"] == 0
    assert (tmp_path / "qualification.json").is_file()
    assert not list(tmp_path.glob("codec-media-*"))


def test_minus38_is_execution_error_not_absence_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch)
    monkeypatch.setattr(FakeCommands, "transfer_error", True)
    monkeypatch.setattr(FakeCommands, "missing_prores", True)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["transfer"]["status"] == "EXECUTION_ERROR"
    assert result["blur"]["status"] == result["ffv1"]["status"] == "PASS"
    assert result["prores"]["status"] == "CAPABILITY_UNAVAILABLE"
    assert result["prores"]["cases"]["64x32"]["capability_kind"] == "ENCODER"
    assert result["cpu_controls_status"] == "PASS"
    assert not result["all_backends_passed"]
    case = result["transfer"]["cases"]["64x32/gray"]
    assert case["command"]["returncode"] == 218
    assert "-38" in case["command"]["stderr"]
    assert "not capability proof" in case["explanation"]


def test_device_absence_requires_actual_loader_and_explicit_name_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch, devices=False)
    monkeypatch.setattr(FakeCommands, "transfer_error", True)
    monkeypatch.setattr(FakeCommands, "failure_text", 'Unable to find device "RTX 3090"!')
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["transfer"]["cases"]["64x32/gray"]["capability_kind"] == "DEVICE"
    assert result["transfer"]["status"] == "CAPABILITY_UNAVAILABLE"


def test_bad_blur_rejected_without_aborting_codec_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch)
    monkeypatch.setattr(FakeCommands, "bad_blur", True)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["blur"]["status"] == "NUMERICAL_MISMATCH"
    assert result["transfer"]["status"] == result["ffv1"]["status"] == "PASS"


@pytest.mark.parametrize("mutation", ["wrong_timing", "mutate_decode"])
def test_ffv1_rejects_bad_grid_or_hidden_rgb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    setup_fake(monkeypatch)
    monkeypatch.setattr(FakeCommands, mutation, True)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["ffv1"]["status"] == "NUMERICAL_MISMATCH"
    assert not result["all_backends_passed"]


def test_command_evidence_preserves_actual_argv_return_code_and_stderr(tmp_path: Path) -> None:
    import sys

    commands = bq._Commands(tmp_path)
    argv = [sys.executable, "-c", "import sys; sys.stderr.write('literal -38\\n'); sys.exit(7)"]
    record, output = commands.run("failed", argv)
    assert output == b"" and record["returncode"] == 7
    assert record["argv"] == argv
    assert record["stderr"] == "literal -38\n"
    assert Path(record["stderr_path"]).read_text() == record["stderr"]
    assert json.loads((tmp_path / "commands.jsonl").read_text())["argv"] == argv


def test_timeout_is_result_and_preserves_partial_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> Any:
        kwargs["stderr"].write(b"literal timeout stderr")
        raise subprocess.TimeoutExpired(args[0], 45, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)
    record, output = bq._Commands(tmp_path).run("timeout", ["not-run"])
    assert record["status"] == "EXECUTION_ERROR"
    assert record["returncode"] is None
    assert output == b"partial"
    assert record["stderr"] == "literal timeout stderr"


def test_missing_executable_not_inventory_absence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(vd, "collect", lambda root: {"loader": {"devices": []}})
    result = bq.qualify(str(tmp_path / "missing-ffmpeg"), "missing-ffprobe", tmp_path / "evidence")
    assert all(
        result[b]["status"] == "EXECUTION_ERROR" for b in ("transfer", "blur", "ffv1", "prores")
    )
    assert result["cpu_controls_status"] == "EXECUTION_ERROR"


def test_bad_selector_and_occupied_root_are_readonly(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        bq.qualify("unused", "unused", tmp_path, device="x,debug=1")
    (tmp_path / "held.txt").write_text("held")
    with pytest.raises(ValueError):
        bq.qualify("unused", "unused", tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["held.txt"]


def test_encoder_inventory_failure_does_not_block_transfer_or_blur(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch)
    original = FakeCommands.run

    def run(
        self: FakeCommands,
        name: str,
        argv: list[str],
        data: bytes | None = None,
        *,
        text: bool = False,
    ) -> tuple[dict[str, Any], bytes]:
        record, value = original(self, name, argv, data, text=text)
        if name == "inventory-encoders":
            record.update(status="EXECUTION_ERROR", returncode=7, stdout="")
        return record, value

    monkeypatch.setattr(FakeCommands, "run", run)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["transfer"]["status"] == result["blur"]["status"] == "PASS"
    assert result["ffv1"]["status"] == result["prores"]["status"] == "EXECUTION_ERROR"


def test_missing_blur_filter_does_not_block_other_backends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_fake(monkeypatch)
    original = FakeCommands.run

    def run(
        self: FakeCommands,
        name: str,
        argv: list[str],
        data: bytes | None = None,
        *,
        text: bool = False,
    ) -> tuple[dict[str, Any], bytes]:
        record, value = original(self, name, argv, data, text=text)
        if name == "inventory-filters":
            record["stdout"] = "... hwupload\n... hwdownload\n"
        return record, value

    monkeypatch.setattr(FakeCommands, "run", run)
    result = bq.qualify("mock-ffmpeg", "mock-ffprobe", tmp_path)
    assert result["blur"]["status"] == "CAPABILITY_UNAVAILABLE"
    assert result["blur"]["cases"]["64x32"]["capability_kind"] == "FILTER"
    assert all(result[b]["status"] == "PASS" for b in ("transfer", "ffv1", "prores"))


def test_vulkan_constants_and_api_version() -> None:
    assert vd.api_version((1 << 22) | (3 << 12) | 280) == "1.3.280"
    assert vd.FORMATS["VK_FORMAT_R16_UNORM"] == 70
    assert vd._flags(0xC003)["names"] == [
        "SAMPLED_IMAGE",
        "STORAGE_IMAGE",
        "TRANSFER_SRC",
        "TRANSFER_DST",
    ]


@pytest.mark.skipif(os.name == "nt", reason="Linux loader-discovery branch")
def test_vulkan_diagnostic_missing_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    assert vd.inspect_loader()["status"] == "CAPABILITY_UNAVAILABLE"
