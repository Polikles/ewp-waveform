"""Explicit isolated acquisition of the frozen native-Windows FFmpeg build.

No network is contacted on import, no PATH or system installation is changed,
and downloading requires allow_download=True (CLI --acquire). The archive and
all installed executables/shared libraries are hash-verified. That is provenance,
NOT encoder inventory or GPU qualification: callers must run qualify() on the
returned exact ffmpeg/ffprobe pair on native Windows before admitting a backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

LOCK_PATH = Path(__file__).with_name("portable_ffmpeg_lock.json")


def read_lock() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, maximum: int) -> int:
    if not url.startswith("https://"):
        raise ValueError("only HTTPS downloads are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "ewp-portable-tool-acquisition/1"})
    count = 0
    deadline = time.monotonic() + 300
    with urllib.request.urlopen(request, timeout=60) as response, target.open("xb") as out:
        if not response.geturl().startswith("https://"):
            raise ValueError("download redirected outside HTTPS")
        while block := response.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError("pinned acquisition exceeded its 300-second transfer deadline")
            count += len(block)
            if count > maximum:
                raise ValueError("archive exceeds the locked download budget")
            out.write(block)
    return count


def _safe_extract(archive: Path, destination: Path, lock: dict[str, Any]) -> None:
    """Validate every entry before creating any archive-derived path."""
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > 4096:
            raise ValueError("archive contains too many entries")
        if sum(m.file_size for m in members) > lock["max_expanded_bytes"]:
            raise ValueError("archive exceeds the locked expanded budget")
        seen: set[str] = set()
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            reserved = {"CON", "PRN", "AUX", "NUL"} | {
                f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
            }
            windows_unsafe = any(
                part.endswith((".", " ")) or part.split(".")[0].upper() in reserved
                for part in path.parts
            )
            if (
                "\\" in name
                or ":" in name
                or windows_unsafe
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != lock["archive_root"]
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
            ):
                raise ValueError("unsafe archive entry: " + name)
            key = str(path).casefold()
            if key in seen:
                raise ValueError("duplicate/case-colliding archive entry: " + name)
            seen.add(key)
        actual_total = 0
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("archive extraction escapes destination")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            actual_member = 0
            with source.open(member) as src, target.open("xb") as out:
                while block := src.read(1024 * 1024):
                    actual_member += len(block)
                    actual_total += len(block)
                    if (
                        actual_member > member.file_size
                        or actual_total > lock["max_expanded_bytes"]
                    ):
                        raise ValueError("archive expanded beyond declared bounds")
                    out.write(block)
            if actual_member != member.file_size:
                raise ValueError("truncated archive entry")


def verify_install(directory: Path, lock: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read back exact executable/DLL payloads; reject changed or injected binaries."""
    lock = read_lock() if lock is None else lock
    if directory.is_symlink() or (directory / "bin").is_symlink():
        raise ValueError("pinned installation must not be a symbolic link")
    binary_dir = directory / "bin"
    expected = lock["bin_sha256"]
    actual_names = {p.name for p in binary_dir.iterdir() if p.suffix.lower() in (".dll", ".exe")}
    if actual_names != set(expected):
        raise ValueError("pinned installation binary set mismatch")
    hashes = {}
    for name, digest in expected.items():
        path = binary_dir / name
        if path.is_symlink() or not path.is_file() or _sha(path) != digest:
            raise ValueError("pinned installation checksum mismatch: " + name)
        hashes[name] = digest
    return {
        "status": "PINNED_PAYLOAD_VERIFIED",
        "ffmpeg": str((binary_dir / "ffmpeg.exe").resolve()),
        "ffprobe": str((binary_dir / "ffprobe.exe").resolve()),
        "bin_sha256": hashes,
        "build_version": lock["build_version"],
        "archive_sha256": lock["sha256"],
        "source_url": lock["url"],
        "runtime_qualification": "PENDING_NATIVE_WINDOWS_EXECUTION",
        "qualification_required": "Run backend_qualification.qualify with this exact pair; "
        "encoder listings alone do not qualify transfer, compute or codecs",
    }


def acquire_windows(root: Path, *, allow_download: bool = False) -> dict[str, Any]:
    """Return same-build controls; download only with explicit operator opt-in.

    Safe to acquire on Linux for transport validation, but this never executes a
    Windows binary there or labels PE inspection as a native-Windows runtime pass.
    A previously installed payload is fully verified, not blindly reused.
    """
    lock = read_lock()
    root = root.expanduser().resolve()
    directory = root / lock["archive_root"]
    if directory.is_symlink():
        raise ValueError("pinned installation must not be a symbolic link")
    if directory.exists():
        return {**verify_install(directory, lock), "reused": True}
    if not allow_download:
        raise PermissionError("pinned FFmpeg absent; explicit --acquire/--prepare-ffmpeg required")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ffmpeg-acquire-", dir=root) as temporary:
        staging = Path(temporary)
        archive = staging / lock["archive_name"]
        size = _download(lock["url"], archive, lock["max_archive_bytes"])
        if size != lock["archive_bytes"] or _sha(archive) != lock["sha256"]:
            raise ValueError("pinned FFmpeg archive size/SHA256 mismatch; nothing installed")
        unpack = staging / "unpack"
        unpack.mkdir()
        _safe_extract(archive, unpack, lock)
        extracted = unpack / lock["archive_root"]
        verify_install(extracted, lock)
        # Do not clobber an existing installation or another concurrent attempt.
        if directory.exists():
            raise FileExistsError("pinned installation appeared during acquisition")
        extracted.rename(directory)
    result = {
        **verify_install(directory, lock),
        "reused": False,
        "acquisition_host_os": os.name,
        "lock_sha256": _sha(LOCK_PATH),
    }
    (directory / "portable-tool-receipt.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--acquire", action="store_true", help="explicitly permit isolated download"
    )
    args = parser.parse_args()
    print(json.dumps(acquire_windows(args.root, allow_download=args.acquire), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
