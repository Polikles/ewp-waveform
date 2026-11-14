"""Real subprocess/storage checks; no media or runtime acquisition."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ewp_waveform.application.portable_experiments_dependencies import require_process_safe
from ewp_waveform.application.portable_experiments_process import (
    ResourceAdmissionError,
    StorageObservationError,
    run_command,
)
from ewp_waveform.application.portable_experiments_state import check_budget, tree_usage


@pytest.mark.parametrize("remove_root", [False, True])
def test_real_writer_limit_and_root_loss_are_distinct(tmp_path: Path, remove_root: bool) -> None:
    managed = tmp_path / "managed"
    media = tmp_path / "media"
    run = tmp_path / "run"
    for path in (managed, media, run):
        path.mkdir()
    limits = {
        "accounting_roots": [str(managed)],
        "baseline_bytes": tree_usage([managed])["budget_bytes"],
        "growth_bytes": 32768,
        "reserve_bytes": 0,
        "memory_floor_bytes": 0,
    }
    action = (
        f"Path({str(managed)!r}).rmdir()"
        if remove_root
        else f"Path({str(managed / 'payload')!r}).write_bytes(b'x' * 262144)"
    )
    result = run_command(
        [sys.executable, "-c", "from pathlib import Path; " + action],
        run / "command",
        timeout=15,
        monitor=lambda: check_budget(run, media, limits),
    )
    assert result["shutdown_verified"]
    assert result["resource_refused"] is not remove_root
    assert result["storage_observation_failed"] is remove_root
    assert result["failure_scope"] == (
        "GLOBAL_STORAGE_OBSERVATION" if remove_root else "GLOBAL_RESOURCE_ADMISSION"
    )
    with pytest.raises(StorageObservationError if remove_root else ResourceAdmissionError):
        require_process_safe(result)
