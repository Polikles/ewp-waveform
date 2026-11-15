"""Stdlib-only exception evidence shared by bootstrap and selected workers."""

from __future__ import annotations

import os
import platform
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def interpreter_identity() -> dict[str, Any]:
    """Observe this process, never infer its identity from a selected worker path."""
    return {
        "executable": sys.executable,
        "resolved_executable": str(Path(sys.executable).resolve()),
        "version": sys.version,
        "implementation": platform.python_implementation(),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "pid": os.getpid(),
    }


@contextmanager
def failure_stage(stage: str) -> Iterator[None]:
    """Annotate the original exception without replacing its type or traceback."""
    try:
        yield
    except BaseException as exc:
        if not getattr(exc, "experiment_failure_stage", None):
            exc.experiment_failure_stage = stage  # type: ignore[attr-defined]
        raise


def exception_diagnostic(exc: BaseException, *, stage: str) -> dict[str, Any]:
    """Retain the full chained traceback, exact failing frame and actual Python."""
    frames = [
        {"filename": f.filename, "lineno": f.lineno, "function": f.name, "line": f.line}
        for f in traceback.extract_tb(exc.__traceback__)
    ]
    return {
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "missing_module": getattr(exc, "name", None) if isinstance(exc, ImportError) else None,
        "stage": getattr(exc, "experiment_failure_stage", stage),
        "interpreter": interpreter_identity(),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "frames": frames,
        "failing_frame": frames[-1] if frames else None,
    }
