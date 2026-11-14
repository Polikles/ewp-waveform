"""Deterministic installer storage races, never timing-dependent churn threads."""

from __future__ import annotations

import errno
import json
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments_dependencies as deps
from ewp_waveform.application import portable_experiments_state as state
from ewp_waveform.application.portable_experiments_process import (
    ResourceAdmissionError,
    StorageObservationError,
)


def limits_for(root: Path, *, active: bool = False) -> dict[str, Any]:
    return {
        "accounting_roots": [str(root)],
        "growth_bytes": 10**12,
        "reserve_bytes": 1,
        "memory_floor_bytes": 1,
        "allow_transient_disappearance": active,
    }


@pytest.fixture(autouse=True)
def sufficient_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "resources", lambda: {"ram_available_bytes": 10**12})
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=10**12))


def disappear_repeatedly(
    monkeypatch: pytest.MonkeyPatch, root: Path, *, times: int | None = None
) -> list[Path]:
    """Create then unlink a real entry after enumeration, before its lstat."""
    original_iterdir, original_lstat = Path.iterdir, Path.lstat
    victim = root / "temporary.cpython-312.pyc"
    observations: list[Path] = []

    def enumerate_entries(path: Path) -> Iterator[Path]:
        if path == root and (times is None or len(observations) < times):
            victim.write_bytes(b"uv temporary bytecode")
        yield from original_iterdir(path)

    def observe(path: Path) -> os.stat_result:
        if path == victim:
            victim.unlink()
            observations.append(path)
        return original_lstat(path)

    monkeypatch.setattr(Path, "iterdir", enumerate_entries)
    monkeypatch.setattr(Path, "lstat", observe)
    return observations


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("action", ["remove", "rename"])
@pytest.mark.parametrize(
    "stage", ["file-lstat", "parent-lstat", "parent-iterdir", "ancestor-iterdir"]
)
def test_enumerated_file_and_parent_disappearances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool, action: str, stage: str
) -> None:
    root = tmp_path / "store"
    directory = root / "transient" / "cache"
    directory.mkdir(parents=True)
    payload = directory / "temporary.pyc"
    payload.write_bytes(b"temporary bytecode")
    victim = payload if stage == "file-lstat" else directory
    trigger = victim
    if stage == "ancestor-iterdir":
        victim = directory.parent
    original_lstat, original_iterdir = Path.lstat, Path.iterdir
    changed = False

    def change() -> None:
        nonlocal changed
        if not changed:
            changed = True
            if action == "rename":
                victim.rename(tmp_path / "renamed-outside-accounting")
            elif victim == payload:
                victim.unlink()
            else:
                shutil.rmtree(victim)

    def observe(path: Path) -> os.stat_result:
        if path == trigger and stage.endswith("lstat"):
            change()
        return original_lstat(path)

    def enumerate_entries(path: Path) -> Iterator[Path]:
        if path == trigger and stage.endswith("iterdir"):
            change()
        yield from original_iterdir(path)

    monkeypatch.setattr(Path, "lstat", observe)
    monkeypatch.setattr(Path, "iterdir", enumerate_entries)
    if not active:
        with pytest.raises(StorageObservationError, match="incomplete") as error:
            state.tree_usage([root])
        assert not isinstance(error.value, ResourceAdmissionError)
    else:
        usage = state.tree_usage([root], allow_transient_disappearance=True)
        assert usage["complete"] is False
        observations = usage["missing_observations"]
        assert len(observations) == 1
        assert observations[0]["winerror"] in (None, 2, 3)
        assert observations == [
            {
                "path": str(trigger),
                "operation": "lstat" if stage.endswith("lstat") else "iterdir",
                "errno": errno.ENOENT,
                "winerror": observations[0]["winerror"],
                "confirmed_missing": True,
            }
        ]
    assert changed


@pytest.mark.parametrize("operation", ["lstat", "iterdir", "stat", "reserve"])
@pytest.mark.parametrize("code", [errno.EACCES, errno.EIO, errno.ENOTDIR])
def test_non_missing_errors_fail_typed_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, code: int
) -> None:
    directory = tmp_path / "cache"
    directory.mkdir()
    original = getattr(Path, operation) if operation != "reserve" else None
    calls = 0

    def fail(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        if path == directory or operation == "reserve":
            calls += 1
            raise OSError(code, "deterministic storage observation fault", str(path))
        assert original is not None
        return original(path, *args, **kwargs)

    if operation == "reserve":
        monkeypatch.setattr(shutil, "disk_usage", fail)
    else:
        monkeypatch.setattr(Path, operation, fail)
    with pytest.raises(StorageObservationError) as error:
        state.check_budget(tmp_path, tmp_path, limits_for(tmp_path, active=True))
    assert not isinstance(error.value, ResourceAdmissionError)
    assert calls == 1
    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__cause__.errno == code


@pytest.mark.parametrize("role", ["accounting", "run", "media", "reserve"])
@pytest.mark.parametrize("when", ["initial", "after-sample", "replace"])
def test_persistent_roots_never_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, when: str
) -> None:
    roots = {name: tmp_path / name for name in ("accounting", "run", "media", "reserve")}
    for root in roots.values():
        root.mkdir()
    limits = {
        **limits_for(roots["accounting"], active=True),
        "reserve_roots": [str(roots["reserve"])],
    }
    victim = roots[role]
    original = state.tree_usage

    def remove_root(*args: Any, **kwargs: Any) -> dict[str, Any]:
        usage = original(*args, **kwargs)
        victim.rename(tmp_path / "retained-removed-root")
        if when == "replace":
            victim.mkdir()
        return usage

    if when == "initial":
        victim.rmdir()
    else:
        monkeypatch.setattr(state, "tree_usage", remove_root)
    with pytest.raises(StorageObservationError, match="required storage root"):
        state.check_budget(roots["run"], roots["media"], limits)


def test_root_loss_during_descendant_observation_is_not_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    payload = root / "temporary.pyc"
    payload.write_bytes(b"temporary")
    original = Path.lstat

    def observe(path: Path) -> os.stat_result:
        if path == payload:
            root.rename(tmp_path / "lost-store")
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    with pytest.raises(StorageObservationError, match="required storage root"):
        state.tree_usage([root], allow_transient_disappearance=True)


@pytest.mark.parametrize("active", [False, True])
def test_three_sample_bound_and_json_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    observations = disappear_repeatedly(monkeypatch, tmp_path)
    limits = limits_for(tmp_path, active=active)
    if active:
        result = state.check_budget(tmp_path, tmp_path, limits)
        storage = result["storage"]
        assert storage["complete"] is False
        assert storage["sampling_attempts"] == 3
        assert len(storage["incomplete_samples"]) == 3
        assert all(not sample["complete"] for sample in storage["incomplete_samples"])
        json.dumps(result, allow_nan=False)
    else:
        with pytest.raises(StorageObservationError, match="after 3 samples"):
            state.check_budget(tmp_path, tmp_path, limits)
    assert len(observations) == 3


@pytest.mark.parametrize("active", [False, True])
def test_recovered_complete_sample_keeps_missing_observation_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    observations = disappear_repeatedly(monkeypatch, tmp_path, times=1)
    result = state.check_budget(tmp_path, tmp_path, limits_for(tmp_path, active=active))
    storage = result["storage"]
    assert storage["complete"] is True
    assert storage["sampling_attempts"] == 2
    assert storage["missing_observations"] == []
    assert len(storage["incomplete_samples"]) == 1
    missing = storage["incomplete_samples"][0]["missing_observations"]
    assert missing[0]["path"] == str(observations[0])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("fault", ["growth", "reserve", "ram"])
@pytest.mark.parametrize("active", [False, True])
def test_incomplete_sample_still_enforces_real_lower_bound_and_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, active: bool
) -> None:
    baseline = state.tree_usage([tmp_path])["budget_bytes"]
    (tmp_path / "retained-growth").write_bytes(b"x" * 8192)
    observations = disappear_repeatedly(monkeypatch, tmp_path)
    limits = {**limits_for(tmp_path, active=active), "baseline_bytes": baseline}
    if fault == "growth":
        limits["growth_bytes"] = 1
    elif fault == "reserve":
        monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=0))
    else:
        monkeypatch.setattr(state, "resources", lambda: {"ram_available_bytes": 0})
    with pytest.raises(state.ResourceLimitError):
        state.check_budget(tmp_path, tmp_path, limits)
    assert len(observations) == 1


def test_partial_baseline_and_compatibility_total_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deps, "outside_git", lambda paths: None)
    observations = disappear_repeatedly(monkeypatch, tmp_path)
    with pytest.raises(StorageObservationError, match="incomplete"):
        deps.setup_limits(tmp_path, 1, 0)
    with pytest.raises(StorageObservationError, match="incomplete"):
        state.tree_bytes(tmp_path)
    assert len(observations) == 2


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("bound", ["entries", "deadline"])
def test_inspection_bounds_never_return_partial_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: bool, bound: str
) -> None:
    (tmp_path / "payload").write_bytes(b"x")
    kwargs: dict[str, Any] = {"allow_transient_disappearance": active}
    if bound == "entries":
        kwargs["max_entries"] = 1
    else:
        ticks = iter([0.0, 2.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
        kwargs["timeout_seconds"] = 1.0
    with pytest.raises(StorageObservationError, match="bound exceeded; no partial total"):
        state.tree_usage([tmp_path], **kwargs)


def test_dedup_and_symlinks_use_only_lstat_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    child = root / "cache"
    child.mkdir()
    payload = child / "payload"
    payload.write_bytes(b"one physical payload")
    try:
        os.link(payload, root / "hardlink")
        (root / "directory-link").symlink_to(child, target_is_directory=True)
        (root / "dangling-link").symlink_to(tmp_path / "absent")
    except OSError:
        pytest.skip("filesystem does not support fixture hardlinks/symlinks")

    def forbidden(path: Path) -> bool:
        raise AssertionError(f"secondary TOCTOU classification: {path}")

    with monkeypatch.context() as patch:
        for name in ("is_dir", "is_file", "is_symlink", "exists"):
            patch.setattr(Path, name, forbidden)
        usage = state.tree_usage([root, child, root])
        assert usage == state.tree_usage([root])
    assert usage["complete"] is True
    assert usage["files"] == 1
    assert usage["logical_bytes"] == len(b"one physical payload")


def test_windows_logical_allocation_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "payload"
    payload.write_bytes(b"logical bytes")
    original = Path.lstat

    def windows_info(path: Path) -> Any:
        info = original(path)
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_mode=info.st_mode,
            st_size=info.st_size,
        )

    monkeypatch.setattr(Path, "lstat", windows_info)
    usage = state.tree_usage([tmp_path])
    assert usage["complete"] is True
    assert usage["allocated_bytes"] is None
    assert usage["budget_bytes"] == tmp_path.stat().st_size + payload.stat().st_size
    assert usage["budget_basis"] == "logical fallback (allocation unavailable)"


@pytest.mark.parametrize("recover", [False, True])
def test_nested_campaign_observations_propagate_without_mutating_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recover: bool
) -> None:
    setup_root, campaign_root = tmp_path / "setup", tmp_path / "campaign"
    setup_root.mkdir()
    campaign_root.mkdir()
    disappear_repeatedly(monkeypatch, campaign_root, times=1 if recover else None)
    campaign_limits = limits_for(campaign_root)
    limits = {**limits_for(setup_root, active=True), "campaign_limits": campaign_limits}
    result = state.check_budget(setup_root, setup_root, limits)
    storage = result["storage"]
    assert storage["complete"] is recover
    assert storage["campaign_storage"]["complete"] is recover
    assert len(storage["incomplete_samples"]) == (1 if recover else 3)
    assert all(sample["scope"] == "campaign" for sample in storage["incomplete_samples"])
    assert campaign_limits["allow_transient_disappearance"] is False
    json.dumps(result, allow_nan=False)


def test_final_check_forces_nested_campaign_strictness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_root, campaign_root = tmp_path / "setup", tmp_path / "campaign"
    setup_root.mkdir()
    campaign_root.mkdir()
    observations = disappear_repeatedly(monkeypatch, campaign_root)
    limits = {
        **limits_for(setup_root),
        "campaign_limits": limits_for(campaign_root, active=True),
    }
    with pytest.raises(StorageObservationError, match="after 3 samples"):
        state.check_budget(setup_root, setup_root, limits)
    assert len(observations) == 3


@pytest.mark.parametrize("operation", ["lstat", "iterdir"])
def test_missing_required_root_during_traversal_never_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    original = getattr(Path, operation)

    def remove(path: Path) -> Any:
        if path == root:
            root.rename(tmp_path / "lost-store")
        return original(path)

    monkeypatch.setattr(Path, operation, remove)
    with pytest.raises(StorageObservationError, match="required storage root"):
        state.tree_usage([root], allow_transient_disappearance=True)


@pytest.mark.parametrize("code", [None, errno.EACCES, errno.EIO])
def test_file_not_found_subclass_requires_verified_missing_errno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int | None
) -> None:
    payload = tmp_path / "payload"
    payload.write_bytes(b"still here")
    original = Path.lstat

    def observe(path: Path) -> os.stat_result:
        if path == payload:
            raise FileNotFoundError(code, "not a verified disappearance", str(path))
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    with pytest.raises(StorageObservationError, match="unverified storage disappearance"):
        state.tree_usage([tmp_path], allow_transient_disappearance=True)


@pytest.mark.parametrize("scope", [None, "GLOBAL_RESOURCE_ADMISSION", "GLOBAL_STORAGE_OBSERVATION"])
def test_retained_dispatch_refusal_preserves_storage_classification(
    tmp_path: Path, scope: str | None
) -> None:
    value = {"error": "retained storage or resource refusal"}
    if scope is not None:
        value["failure_scope"] = scope
    state.append_event(
        tmp_path, {"event": "DISPATCH_REFUSED", "name": "post-evidence", "value": value}
    )
    expected = (
        StorageObservationError if scope == "GLOBAL_STORAGE_OBSERVATION" else ResourceAdmissionError
    )
    with pytest.raises(expected, match="retained post-evidence dispatch refusal") as error:
        state.completed_steps(tmp_path)
    if scope == "GLOBAL_STORAGE_OBSERVATION":
        assert not isinstance(error.value, ResourceAdmissionError)


@pytest.mark.parametrize("recover", [False, True])
def test_reappeared_entry_requires_a_new_sample_even_in_active_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recover: bool
) -> None:
    payload = tmp_path / "payload"
    payload.write_bytes(b"present during confirmation")
    original = Path.lstat
    calls = 0

    def observe(path: Path) -> os.stat_result:
        nonlocal calls
        if path == payload:
            calls += 1
            if calls == 1 or (not recover and calls % 2 == 1):
                raise FileNotFoundError(
                    errno.ENOENT, "enumerated entry temporarily absent", str(path)
                )
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    if not recover:
        with pytest.raises(StorageObservationError, match="after 3 samples"):
            state.check_budget(tmp_path, tmp_path, limits_for(tmp_path, active=True))
        assert calls == 6
    else:
        result = state.check_budget(tmp_path, tmp_path, limits_for(tmp_path, active=True))
        storage = result["storage"]
        assert storage["complete"] is True
        assert storage["sampling_attempts"] == 2
        sample = storage["incomplete_samples"][0]
        assert sample["requires_resample"] is True
        assert sample["missing_observations"][0]["confirmed_missing"] is False
        assert calls == 3


@pytest.mark.parametrize("code", [errno.EACCES, errno.EIO])
def test_missing_confirmation_never_swallows_other_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    payload = tmp_path / "payload"
    payload.write_bytes(b"payload")
    original = Path.lstat
    calls = 0

    def observe(path: Path) -> os.stat_result:
        nonlocal calls
        if path == payload:
            calls += 1
            if calls == 1:
                raise FileNotFoundError(errno.ENOENT, "first lookup absent", str(path))
            raise OSError(code, "confirmation forbidden", str(path))
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    with pytest.raises(StorageObservationError, match="verification failed") as error:
        state.check_budget(tmp_path, tmp_path, limits_for(tmp_path, active=True))
    assert isinstance(error.value.__cause__, OSError)
    assert error.value.__cause__.errno == code
    assert calls == 2


def test_missing_observation_payload_is_bounded_without_losing_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(70):
        (tmp_path / f"temporary-{index}.pyc").write_bytes(b"temporary")
    original = Path.iterdir

    def enumerate_then_remove(path: Path) -> Iterator[Path]:
        entries = list(original(path))
        yield from entries
        if path == tmp_path:
            for entry in entries:
                entry.unlink()

    monkeypatch.setattr(Path, "iterdir", enumerate_then_remove)
    usage = state.tree_usage([tmp_path], allow_transient_disappearance=True)
    assert usage["complete"] is False
    assert usage["missing_observation_count"] == 70
    assert len(usage["missing_observations"]) == 64
    assert usage["missing_observations_truncated"] is True
    json.dumps(usage, allow_nan=False)


def test_max_observed_growth_survives_later_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = state.tree_usage([tmp_path])["budget_bytes"]
    persistent = tmp_path / "retained-during-first-sample"
    persistent.write_bytes(b"x" * 8192)
    disappear_repeatedly(monkeypatch, tmp_path, times=1)
    original = state.tree_usage
    samples: list[dict[str, Any]] = []

    def sample_then_cleanup(*args: Any, **kwargs: Any) -> dict[str, Any]:
        usage = original(*args, **kwargs)
        samples.append(usage)
        if len(samples) == 1:
            persistent.unlink()
        return usage

    monkeypatch.setattr(state, "tree_usage", sample_then_cleanup)
    limits = {**limits_for(tmp_path, active=True), "baseline_bytes": baseline}
    result = state.check_budget(tmp_path, tmp_path, limits)
    assert len(samples) == 2
    assert result["storage"]["complete"] is True
    assert samples[0]["budget_bytes"] > samples[1]["budget_bytes"]
    assert result["growth_bytes"] == samples[0]["budget_bytes"] - baseline
    assert result["storage"]["max_observed_budget_bytes"] == samples[0]["budget_bytes"]


def test_confirmed_windows_path_not_found_preserves_winerror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "temporary.cpython-312.pyc"
    payload.write_bytes(b"temporary")
    original = Path.lstat
    calls = 0

    def observe(path: Path) -> os.stat_result:
        nonlocal calls
        if path == payload:
            calls += 1
            error = FileNotFoundError(errno.ENOENT, "Windows path no longer present", str(path))
            error.winerror = 3  # type: ignore[attr-defined]
            raise error
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    usage = state.tree_usage([tmp_path], allow_transient_disappearance=True)
    assert usage["complete"] is False
    assert usage["requires_resample"] is False
    assert usage["missing_observations"][0]["winerror"] == 3
    assert usage["missing_observations"][0]["confirmed_missing"] is True
    assert calls == 2


@pytest.mark.parametrize("later_fault", ["reserve", "root", "resample", "campaign"])
def test_incomplete_history_survives_later_observation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later_fault: str
) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    disappear_repeatedly(monkeypatch, root)
    original = state.tree_usage
    samples = 0

    def sample(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal samples
        samples += 1
        if later_fault == "resample" and samples == 2:
            raise StorageObservationError("later sample I/O failure")
        if later_fault == "campaign" and args[0] == [tmp_path, tmp_path]:
            raise StorageObservationError("nested campaign permission failure")
        result = original(*args, **kwargs)
        if later_fault == "root":
            root.rename(tmp_path / "lost-root")
        return result

    def reserve(path: Path) -> Any:
        raise PermissionError(errno.EACCES, "later reserve permission failure", str(path))

    monkeypatch.setattr(state, "tree_usage", sample)
    if later_fault == "reserve":
        monkeypatch.setattr(shutil, "disk_usage", reserve)
    policy = limits_for(root, active=True)
    if later_fault == "campaign":
        policy["campaign_limits"] = limits_for(tmp_path)
        policy["campaign_limits"].pop("accounting_roots")
    live, _ = deps.installation_monitors(tmp_path, tmp_path, policy, tmp_path / "evidence")
    with pytest.raises(StorageObservationError) as error:
        live()
    assert error.value.storage_observations
    assert error.value.storage_observations[0]["missing_observations"][0]["confirmed_missing"]
    event = json.loads((tmp_path / "evidence/storage-samples.jsonl").read_text())
    assert event["incomplete_samples"] == error.value.storage_observations


@pytest.mark.parametrize("replace_during_scan", [False, True])
def test_required_root_symlink_never_claims_complete_zero_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_during_scan: bool
) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    (root / "payload").write_bytes(b"x" * 32768)
    original = state.tree_usage

    def replace() -> None:
        retained = tmp_path / "retained"
        root.rename(retained)
        root.symlink_to(retained, target_is_directory=True)

    def sample(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        replace()
        return result

    if replace_during_scan:
        monkeypatch.setattr(state, "tree_usage", sample)
    else:
        replace()
    with pytest.raises(StorageObservationError, match="required storage root"):
        state.check_budget(tmp_path, tmp_path, limits_for(root, active=True))


@pytest.mark.parametrize("outer_incomplete", [False, True])
def test_successful_nested_history_survives_final_outer_root_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outer_incomplete: bool
) -> None:
    root, campaign, run, media = (
        tmp_path / name for name in ("managed", "campaign", "run", "media")
    )
    for path in (root, campaign, run, media):
        path.mkdir()
    if outer_incomplete:
        disappear_repeatedly(monkeypatch, root)
    disappear_repeatedly(monkeypatch, campaign)
    original = state.tree_usage
    nested_samples = 0

    def sample(roots: list[Path], **kwargs: Any) -> dict[str, Any]:
        nonlocal nested_samples
        result = original(roots, **kwargs)
        if roots == [campaign]:
            nested_samples += 1
            if nested_samples == 3:
                root.rename(tmp_path / "lost-managed-root")
        return result

    monkeypatch.setattr(state, "tree_usage", sample)
    policy = {**limits_for(root, active=True), "campaign_limits": limits_for(campaign)}
    live, _ = deps.installation_monitors(run, media, policy, tmp_path / "evidence")
    with pytest.raises(StorageObservationError, match="required storage root") as error:
        live()
    observations = error.value.storage_observations
    assert len(observations) == (6 if outer_incomplete else 3)
    assert sum(item.get("scope") == "campaign" for item in observations) == 3
    event = json.loads((tmp_path / "evidence/storage-samples.jsonl").read_text())
    assert event["incomplete_samples"] == observations
