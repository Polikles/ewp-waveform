"""Integration seams: explicit dependency locks and legacy command compatibility."""

from __future__ import annotations

import importlib.util
import platform
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments as portable
from ewp_waveform.application import portable_experiments_setup as setup
from ewp_waveform.application import portable_experiments_state as state
from ewp_waveform.ffmpeg import experiment_suite

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "portable_legacy_compat", ROOT / "scripts/run_wsl_experiments.py"
)
assert SPEC and SPEC.loader
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


def test_ordinary_legacy_command_uses_portable_application(monkeypatch: Any) -> None:
    seen = []

    def called(argv: list[str]) -> int:
        seen.append(argv)
        return 31

    monkeypatch.setattr(portable, "main", called)
    assert legacy.compatibility_main(["--preflight-only", "--audio", "/source.wav"]) == 31
    assert seen == [["--preflight-only", "--audio", "/source.wav"]]


def test_sealed_legacy_resume_keeps_original_integrity_checks(
    tmp_path: Path, monkeypatch: Any
) -> None:
    (tmp_path / "driver-seal.json").write_text("{}")
    seen = []

    def called(argv: list[str]) -> int:
        seen.append(argv)
        return 17

    monkeypatch.setattr(legacy, "main", called)
    assert legacy.compatibility_main(["--resume", str(tmp_path)]) == 17
    assert seen == [["--resume", str(tmp_path)]]


def test_service_device_guard_accepts_observed_ffmpeg_spelling() -> None:
    assert "RTX 3090" in experiment_suite.selected_device(
        "Device 0 selected: Microsoft Direct3D12 (NVIDIA GeForce RTX 3090)", r"RTX\s*3090"
    )
    with pytest.raises(ValueError):
        experiment_suite.selected_device("Device 0 selected: llvmpipe", r"RTX\s*3090")


def test_both_optional_platform_closures_are_versioned_and_hashed() -> None:
    for target in ("windows", "linux"):
        lock = ROOT / "requirements" / f"torch-cu128-{target}-x64-py312.txt"
        text = lock.read_text()
        assert "torch==2.9.1+cu128" in text
        assert "--hash=sha256:" in text
        assert "numpy==2.5.3" in text
        assert "pydantic==2.13.4" in text
        assert "typer==0.27.1" in text
    source = state.source_identity(ROOT)
    assert "requirements/torch-cu128-linux-x64-py312.txt" in source["files"]
    assert "requirements-torch-experiment.txt" in source["files"]


def test_cuda_lock_refuses_unsupported_architecture(monkeypatch: Any) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    with pytest.raises(ValueError, match="x86-64"):
        setup.cuda_lock(ROOT)
