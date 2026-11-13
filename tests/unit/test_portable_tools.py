"""No-network tests for frozen acquisition, integrity and extraction safety."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.ffmpeg import portable_tools as pt


def make_archive(entries: Mapping[str, bytes | zipfile.ZipInfo]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            if isinstance(data, zipfile.ZipInfo):
                archive.writestr(data, b"symlink-target")
            else:
                archive.writestr(name, data)
    return output.getvalue()


def fake_lock(archive: bytes) -> dict[str, Any]:
    return {
        "archive_root": "payload",
        "archive_name": "ffmpeg-test.zip",
        "url": "https://example.invalid/not-actually-requested.zip",
        "archive_bytes": len(archive),
        "sha256": hashlib.sha256(archive).hexdigest(),
        "max_archive_bytes": 100000,
        "max_expanded_bytes": 100000,
        "build_version": "TEST-NOT-RUNTIME-EVIDENCE",
        "bin_sha256": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in {"ffmpeg.exe": b"fake-mpeg", "ffprobe.exe": b"fake-probe"}.items()
        },
    }


def test_absent_acquisition_requires_opt_in_without_creating_root(tmp_path: Path) -> None:
    root = tmp_path / "not-created"
    with pytest.raises(PermissionError, match="explicit"):
        pt.acquire_windows(root)
    assert not root.exists()


def test_verified_install_and_reuse_are_read_back_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = make_archive(
        {"payload/bin/ffmpeg.exe": b"fake-mpeg", "payload/bin/ffprobe.exe": b"fake-probe"}
    )
    lock = fake_lock(payload)
    monkeypatch.setattr(pt, "read_lock", lambda: lock)
    calls = []

    def download(url: str, path: Path, maximum: int) -> int:
        calls.append(url)
        path.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(pt, "_download", download)
    result = pt.acquire_windows(tmp_path, allow_download=True)
    assert result["status"] == "PINNED_PAYLOAD_VERIFIED" and not result["reused"]
    assert result["runtime_qualification"] == "PENDING_NATIVE_WINDOWS_EXECUTION"
    assert Path(result["ffmpeg"]).parent == Path(result["ffprobe"]).parent
    assert Path(result["ffprobe"]).read_bytes() == b"fake-probe"
    assert pt.acquire_windows(tmp_path)["reused"]
    assert len(calls) == 1
    assert not list(tmp_path.glob(".ffmpeg-acquire-*"))
    # Changed payload cannot silently be reused.
    Path(result["ffprobe"]).write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        pt.acquire_windows(tmp_path)


def test_wrong_archive_hash_never_installs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = make_archive({"payload/bin/ffmpeg.exe": b"fake-mpeg"})
    lock = fake_lock(payload)
    lock["sha256"] = "0" * 64
    monkeypatch.setattr(pt, "read_lock", lambda: lock)

    def download(url: str, path: Path, maximum: int) -> int:
        path.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(pt, "_download", download)
    with pytest.raises(ValueError, match="size/SHA256 mismatch"):
        pt.acquire_windows(tmp_path, allow_download=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute/path",
        "payload/../escape",
        "payload/bin/..\\escape",
        "payload/bin/C:escape",
        "payload/bin/NUL.txt",
        "payload/bin/file.",
        "wrong-root/bin/ffmpeg.exe",
    ],
)
def test_safe_extract_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    payload = make_archive({name: b"bad"})
    archive = tmp_path / "input.zip"
    archive.write_bytes(payload)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(ValueError, match="unsafe archive entry"):
        pt._safe_extract(archive, destination, fake_lock(payload))
    assert list(destination.iterdir()) == []


def test_safe_extract_rejects_symlinks_and_case_collisions(tmp_path: Path) -> None:
    link = zipfile.ZipInfo("payload/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    for entries in ({"payload/link": link}, {"payload/file": b"x", "payload/FILE": b"y"}):
        payload = make_archive(entries)
        archive = tmp_path / "input.zip"
        archive.write_bytes(payload)
        with pytest.raises(ValueError):
            pt._safe_extract(archive, tmp_path / "out", fake_lock(payload))
    assert not (tmp_path / "out").exists()


def test_safe_extract_rejects_expanded_budget_before_writes(tmp_path: Path) -> None:
    payload = make_archive({"payload/bin/data": b"large"})
    archive = tmp_path / "input.zip"
    archive.write_bytes(payload)
    lock = fake_lock(payload)
    lock["max_expanded_bytes"] = 2
    with pytest.raises(ValueError, match="expanded budget"):
        pt._safe_extract(archive, tmp_path / "out", lock)
    assert not (tmp_path / "out").exists()


def test_lock_records_provenance_not_runtime_pass() -> None:
    lock = pt.read_lock()
    assert "/latest/" not in lock["url"]
    assert lock["release_tag"] == "autobuild-2026-10-31-12-59"
    assert lock["sha256"] == "1d9823c35c7a7e2f54d1438cf61030d6efabe3278de01c191309d1e828bb74df"
    assert lock["research"]["verified_download"]
    assert lock["research"]["runtime_qualification"] == "PENDING_NATIVE_WINDOWS"
    assert set(lock["required_encoder_names"]) <= set(
        lock["research"]["avcodec_binary_codec_strings"]
    )
    assert all(lock["research"]["avcodec_binary_codec_strings"].values())
    assert {"ffmpeg.exe", "ffprobe.exe"} <= set(lock["bin_sha256"])
    assert json.loads(pt.LOCK_PATH.read_text())["platform"] == "windows-x86_64"
