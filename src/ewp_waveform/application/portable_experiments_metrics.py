"""Compact phase measurements; raw per-call diagnostics remain separately retained."""

from __future__ import annotations

import statistics
from typing import Any

_SAMPLES = {"calls", "frame_calls", "batch_calls", "numpy_phases"}
_EXCLUDE = {"commands", "command", "diagnostic_excerpts", "stderr", "stdout", "artifacts"}


def compact_metrics(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: compact_metrics(v, k) for k, v in value.items() if k not in _EXCLUDE}
    if isinstance(value, list):
        if key in _SAMPLES and len(value) > 16:
            rows = [v if isinstance(v, dict) else {"seconds": v} for v in value]
            fields = sorted({k for row in rows for k in row})
            numeric: dict[str, Any] = {}
            constants: dict[str, Any] = {}
            for field in fields:
                items = [row[field] for row in rows if field in row]
                nums = [v for v in items if type(v) in (int, float)]
                if nums:
                    numeric[field] = {
                        "n": len(nums),
                        "sum": sum(nums),
                        "min": min(nums),
                        "max": max(nums),
                        "median": statistics.median(nums),
                        "null_n": sum(v is None for v in items),
                    }
                elif items and all(item == items[0] for item in items):
                    constants[field] = items[0]
                else:
                    constants[field] = {"values": list(dict.fromkeys(map(str, items)))}
            return {
                "sample_count": len(rows),
                "numeric_fields": numeric,
                "constant_fields": constants,
                "scope": "per-field aggregates only; phase totals overlap, never sum phases; "
                "raw ordered calls remain in main report JSON",
            }
        return [compact_metrics(v) for v in value]
    return value
