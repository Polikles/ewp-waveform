"""Subprocess helpers. Never uses shell=True."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path


class ToolNotFoundError(RuntimeError):
    pass


def require_tool(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        msg = f"Required tool not on PATH: {name}"
        raise ToolNotFoundError(msg)
    return Path(found)


def run_argv(argv: list[str]) -> subprocess.CompletedProcess[str]:
    if not argv:
        msg = "empty argv"
        raise ValueError(msg)
    return subprocess.run(argv, check=False, capture_output=True, text=True)


def _drain(stream: object, store: list[bytes]) -> None:
    read = getattr(stream, "read", None)
    if read is None:
        return
    while True:
        block = read(65536)
        if not block:
            break
        store.append(block)


def run_argv_stdin(argv: list[str], chunks: Iterable[bytes]) -> subprocess.CompletedProcess[bytes]:
    """Feed binary chunks to stdin.

    Stdout/stderr are drained on threads so a chatty child cannot deadlock
    against a long stdin write (FFmpeg stats on a PIPE).
    """
    if not argv:
        msg = "empty argv"
        raise ValueError(msg)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.stdin is None:
        msg = "failed to open ffmpeg stdin"
        raise RuntimeError(msg)
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_parts), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_parts), daemon=True)
    t_out.start()
    t_err.start()
    try:
        for chunk in chunks:
            proc.stdin.write(chunk)
    except BrokenPipeError:
        pass
    finally:
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.close()
    t_out.join()
    t_err.join()
    proc.wait()
    return subprocess.CompletedProcess(
        argv, proc.returncode, b"".join(stdout_parts), b"".join(stderr_parts)
    )
