"""Subprocess helpers. Never uses shell=True."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_COMMAND_EVIDENCE: ContextVar[Path | None] = ContextVar("ffmpeg_command_evidence", default=None)


@contextlib.contextmanager
def command_evidence(path: Path) -> Iterator[None]:
    """Explicit same-process observation only; no default command or output changes."""
    token = _COMMAND_EVIDENCE.set(path)
    try:
        yield
    finally:
        _COMMAND_EVIDENCE.reset(token)


def _record_command(argv: list[str]) -> None:
    path = _COMMAND_EVIDENCE.get()
    if path is not None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "production-subprocess", "argv": argv}) + "\n")


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
    _record_command(argv)
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


def run_argv_stdin(
    argv: list[str],
    chunks: Iterable[bytes],
    *,
    phases: Any | None = None,
    stderr_path: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Feed binary chunks to stdin.

    Stdout/stderr are drained on threads so a chatty child cannot deadlock
    against a long stdin write (FFmpeg stats on a PIPE).
    """
    if not argv:
        msg = "empty argv"
        raise ValueError(msg)
    _record_command(argv)
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
    rgba_bytes = 0
    raw_feed_bytes = 0
    try:
        iterator = iter(chunks)
        while True:
            t0 = time.perf_counter()
            try:
                chunk = next(iterator)
            except StopIteration:
                break
            t1 = time.perf_counter()
            rgba_bytes += len(chunk)
            written = proc.stdin.write(chunk)
            raw_feed_bytes += written if written is not None else 0
            t2 = time.perf_counter()
            if phases is not None:
                phases.add("generator", t1 - t0)
                phases.add("ffmpeg_feed", t2 - t1)
    except BrokenPipeError:
        pass
    finally:
        t_close = time.perf_counter()
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.close()
        t_out.join()
        t_err.join()
        proc.wait()
        if stderr_path is not None:
            # The generator may have raised: retain the drained child bytes in
            # cleanup rather than relying on a CompletedProcess being returned.
            original_error = sys.exception()
            try:
                stderr_path.write_bytes(b"".join(stderr_parts))
            except OSError as evidence_error:
                if original_error is None:
                    raise
                original_error.add_note(f"child stderr persistence failed: {evidence_error}")
        if phases is not None:
            phases.add("ffmpeg_wait", time.perf_counter() - t_close)
            phases.extras["rgba_bytes"] = rgba_bytes
            phases.extras["rgba_bytes_scope"] = "legacy last-feed attempted bytes; may be gray"
            phases.extras["raw_feed_bytes"] = (
                phases.extras.get("raw_feed_bytes", 0) + raw_feed_bytes
            )
            phases.extras["raw_feed_bytes_scope"] = (
                "sum of chunks whose blocking write returned; parent instrumented feeds only"
            )
    return subprocess.CompletedProcess(
        argv, proc.returncode, b"".join(stdout_parts), b"".join(stderr_parts)
    )
