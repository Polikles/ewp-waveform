"""Missing Unix-only resource telemetry must not prevent native Windows rendering."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from ewp_waveform.application import evidence


def test_unix_resource_absence_is_explicit(monkeypatch: Any) -> None:
    monkeypatch.setattr(evidence, "resource", None)
    observation = evidence.parent_resource_observation()
    assert observation["parent_lifetime_ru_maxrss"] is None
    assert observation["parent_lifetime_ru_maxrss_unit"] is None
    assert "unavailable" in observation["scope"]
    assert observation["process_tree_peak_rss_bytes"] is None


def test_module_import_without_unix_resource(monkeypatch: Any) -> None:
    try:
        with monkeypatch.context() as patcher:
            patcher.setitem(sys.modules, "resource", None)
            importlib.reload(evidence)
            assert evidence.__dict__["resource"] is None
            assert evidence.parent_resource_observation()["parent_lifetime_ru_maxrss"] is None
    finally:
        importlib.reload(evidence)


def test_unix_resource_scope_stays_lifetime_parent() -> None:
    if evidence.__dict__["resource"] is None:
        return
    observation = evidence.parent_resource_observation()
    assert observation["parent_lifetime_ru_maxrss"] > 0
    assert "process-lifetime" in observation["scope"]
    assert observation["per_cell_peak_rss_bytes"] is None
