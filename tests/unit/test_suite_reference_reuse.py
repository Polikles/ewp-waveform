"""Full-reference evidence reuse never substitutes an earlier timing observation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from ewp_waveform.application import experiment_suite_render as rendering
from ewp_waveform.application import experiment_suite_state as state
from ewp_waveform.application.experiments import digest_value, sha


def reference() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    return cast(
        dict[str, Any], json.loads((root / "examples/experiments/vm-reference.json").read_text())
    )


def test_full_reuse_requires_complete_byte_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = reference()
    media = tmp_path / "master.mov"
    media.write_bytes(b"tiny unit fixture, never production media")
    prior = ref["historical_full_reference"]
    prior["file_bytes"] = media.stat().st_size
    prior["file_sha256"] = sha(media)
    # Explicit synthetic trust fixture; never a claim of production validation.
    trusted = {
        key: ref[key]
        for key in ("source_input", "historical_full_reference", "provenance", "prior_validation")
    }
    monkeypatch.setattr(rendering, "TRUSTED_FULL_CONTRACT_SHA256", digest_value(trusted))
    workload = {"kind": "full", "frames": 23741}
    session = {"vm_reference": ref}
    result = rendering.reuse_full_validation(session, workload, media)
    assert result is not None and result["passed"] is True
    assert result["new_full_decode"] is False
    assert result["native_plane_sha256"] == prior["native_plane_sha256"]
    assert "wall_seconds" not in result
    media.write_bytes(b"different content, even when same byte count")
    assert rendering.reuse_full_validation(session, workload, media) is None


@pytest.mark.parametrize(
    "field", ["source_input", "historical_full_reference", "provenance", "prior_validation"]
)
def test_untrusted_prior_contract_is_never_authenticated(tmp_path: Path, field: str) -> None:
    ref = reference()
    ref[field] = {}
    # Refusal occurs before any file I/O or interpretation of incomplete claims.
    assert (
        rendering.reuse_full_validation(
            {"vm_reference": ref}, {"kind": "full", "frames": 23741}, tmp_path / "absent.mov"
        )
        is None
    )


def test_versioned_prior_receipt_contract_matches_trust_anchor() -> None:
    ref = reference()
    trusted = {
        key: ref[key]
        for key in ("source_input", "historical_full_reference", "provenance", "prior_validation")
    }
    assert digest_value(trusted) == rendering.TRUSTED_FULL_CONTRACT_SHA256


@pytest.mark.parametrize("change", ["count", "kind", "proof", "planes", "size", "digest"])
def test_incomplete_reuse_contract_falls_through_to_real_validation(
    tmp_path: Path, change: str
) -> None:
    ref = reference()
    media = tmp_path / "master.mov"
    media.write_bytes(b"test")
    prior = ref["historical_full_reference"]
    prior.update(file_bytes=4, file_sha256=sha(media))
    workload = {"kind": "full", "frames": 23741}
    if change == "count":
        workload["frames"] = 1
    elif change == "kind":
        workload["kind"] = "short"
    elif change == "proof":
        prior["native_plane_equality"] = "UNKNOWN"
    elif change == "planes":
        prior["native_plane_sha256"].pop("A")
    elif change == "size":
        prior["file_bytes"] = 5
    else:
        prior["file_sha256"] = "0" * 64
    assert rendering.reuse_full_validation({"vm_reference": ref}, workload, media) is None


def test_installed_provenance_is_verified_without_build_fabrication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {"observed": "same"}
    monkeypatch.setattr(state, "source_identity", lambda: identity)
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(state, "verify_artifact", seen.append)
    inventory = {"path": "/observed.json", "sha256": "a" * 64, "bytes": 3}
    session = {
        "source": copy.deepcopy(identity),
        "audio": {"path": "/audio"},
        "reference_artifact": {"path": "/reference"},
        "installed_provenance": {"inventory": inventory},
        "tools": {},
        "build": None,
    }
    state.verify_session(session)
    assert inventory in seen
    assert session["build"] is None
