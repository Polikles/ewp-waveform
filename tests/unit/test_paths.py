from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ewp_waveform import paths


@pytest.mark.parametrize("platform", ["posix", "nt"])
@pytest.mark.parametrize(
    "value,linux_path",
    [
        (r"D:\podkast\s0e00.wav", "/mnt/d/podkast/s0e00.wav"),
        ("D:/podkast/s0e00.wav", "/mnt/d/podkast/s0e00.wav"),
        (r"E:\other episode\another mono.wav", "/mnt/e/other episode/another mono.wav"),
        (r"\\server\share\another mono.wav", "//server/share/another mono.wav"),
        (r"relative folder\another mono.wav", "relative folder/another mono.wav"),
    ],
)
def test_platform_path_policy_simulation(
    monkeypatch: pytest.MonkeyPatch, platform: str, value: str, linux_path: str
) -> None:
    # Simulate only this module's platform branch, not os.name/pathlib globally.
    # Path remains the real host class; this is not Windows filesystem execution.
    monkeypatch.setattr(paths, "os", SimpleNamespace(name=platform))
    expected = value if platform == "nt" else linux_path
    assert paths.normalize_user_path(value) == Path(expected)


def test_native_platform_drive_policy() -> None:
    value = r"D:\podkast\s0e00.wav"
    expected = value if os.name == "nt" else "/mnt/d/podkast/s0e00.wav"
    assert paths.normalize_user_path(value) == Path(expected)


def test_posix_path_is_unchanged() -> None:
    assert paths.normalize_user_path("/mnt/d/podkast/s0e00.wav") == Path("/mnt/d/podkast/s0e00.wav")


@pytest.mark.parametrize("quote", ['"', "'"])
def test_quoted_windows_path(quote: str) -> None:
    value = r"C:\Users\me\another mono.wav"
    expected = value if os.name == "nt" else "/mnt/c/Users/me/another mono.wav"
    assert paths.normalize_user_path(f"{quote}{value}{quote}") == Path(expected)
