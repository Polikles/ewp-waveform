from __future__ import annotations

from copy import deepcopy

from tests.render_oracles import semantic_result


def _payload() -> dict[str, object]:
    return {
        "job": {"render_signature": "abc", "status": "SUCCEEDED"},
        "renderer": {"visual_contract_version": 13},
        "inputs": [{"path": "/tmp/a.wav", "duration_seconds": 0.6}],
        "outputs": [{"path": "/tmp/a.mov", "format": "prores4444"}],
        "warnings": [{"code": "W_TEST"}],
        "analysis": {"chunk_count": 3},
        "normalization": {"global_peak": 0.75},
        "validation": {"passed": True, "frames": 6, "duration_seconds": 0.6},
        "performance": {
            "seconds": {"decode": 0.1},
            "counts": {"decode": 1},
            "extras": {"render_path": "mask_fast"},
        },
        "timestamps": {
            "started_at": "2026-10-04T00:00:00Z",
            "completed_at": "2026-10-04T00:00:01Z",
            "duration_seconds": 1.0,
        },
    }


def test_semantic_result_excludes_only_runtime_values() -> None:
    left = _payload()
    right = deepcopy(left)
    right["inputs"] = [{"path": "/different/source.wav", "duration_seconds": 0.6}]
    right["outputs"] = [{"path": "/different/output.mov", "format": "prores4444"}]
    right["performance"] = {
        "seconds": {"decode": 9.9},
        "counts": {"decode": 1},
        "extras": {"render_path": "mask_fast"},
    }
    right["timestamps"] = {
        "started_at": "2026-10-05T00:00:00Z",
        "completed_at": "2026-10-05T00:00:10Z",
        "duration_seconds": 10.0,
    }

    normalized = semantic_result(left)
    assert normalized == semantic_result(right)
    assert normalized["job"] == {"render_signature": "abc", "status": "SUCCEEDED"}
    assert normalized["renderer"] == {"visual_contract_version": 13}
    assert normalized["warnings"] == [{"code": "W_TEST"}]
    assert normalized["analysis"] == {"chunk_count": 3}
    assert normalized["normalization"] == {"global_peak": 0.75}
    assert normalized["validation"] == {
        "passed": True,
        "frames": 6,
        "duration_seconds": 0.6,
    }


def test_semantic_result_retains_renderer_semantics() -> None:
    left = _payload()
    right = deepcopy(left)
    renderer = right["renderer"]
    assert isinstance(renderer, dict)
    renderer["visual_contract_version"] = 14

    assert semantic_result(left) != semantic_result(right)
