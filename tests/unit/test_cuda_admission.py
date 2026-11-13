"""A GPU backend label must never qualify CPU work as CUDA execution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application.torch_experiment import render_experiment
from ewp_waveform.ffmpeg import torch_finish as finish


@pytest.mark.parametrize("backend", ["cuda", "transfer-cuda"])
@pytest.mark.parametrize("device", ["cpu", "cuda", "cuda:-1", "mps:0", "cuda:\u0660", ""])
def test_cuda_rejects_non_cuda_selector_before_import_or_allocation(
    backend: str, device: str, tmp_path: Path, monkeypatch: Any
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("optional GPU worker must not be constructed")

    monkeypatch.setattr(finish, "TorchFinisher", forbidden)
    with pytest.raises(ValueError, match="cuda:N"):
        finish.qualify(backend, device=device)
    output = tmp_path / "must-not-exist" / "native.mov"
    with pytest.raises(ValueError, match="cuda:N"):
        render_experiment(
            source=tmp_path / "absent.wav",
            start=0,
            duration=0.1,
            output=output,
            backend=backend,
            device=device,
        )
    assert not output.parent.exists()


def test_transfer_qualification_is_compute_free(monkeypatch: Any) -> None:
    class TransferOnly:
        cuda = True

        def __init__(self, *args: Any) -> None:
            pass

        def transfer(self, mask: Any) -> Any:
            return mask.copy()

        def finish_alpha(self, mask: Any) -> Any:
            pytest.fail("transfer-only qualification must not require finishing compute")

        def evidence(self) -> dict[str, Any]:
            return {"device": "cuda:0", "device_name": "unit stand-in, not hardware evidence"}

    monkeypatch.setattr(finish, "TorchFinisher", TransferOnly)
    result = finish.qualify("transfer-cuda", device="cuda:0")
    assert result["passed"] and result["transfer_qualified"]
    assert not result["gpu_qualified"]
    assert len([r for r in result["cases"] if r.get("bytes_equal")]) == 10


@pytest.mark.parametrize("backend", ["cuda", "transfer-cuda"])
def test_cuda_claim_requires_actual_cuda_worker(backend: str, monkeypatch: Any) -> None:
    # Admission-control stand-in only, not hardware execution evidence.
    monkeypatch.setattr(finish, "TorchFinisher", lambda *args: SimpleNamespace(cuda=False))
    with pytest.raises(ValueError, match="actual CUDA worker"):
        finish.qualify(backend, device="cuda:0")
