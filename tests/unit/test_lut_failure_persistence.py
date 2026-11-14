from __future__ import annotations

import errno
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from unittest.mock import Mock

import pytest

from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.ffmpeg import encode, ribbon_lut


def invoke(root: Path, phases: PhaseTimes) -> None:
    encode.encode_rgba_stream(
        iter(()),
        width=32,
        height=32,
        fps=10,
        glow=0,
        png_dir=None,
        prores_path=root / "out.mov",
        color="#C7E6EC",
        pix_fmt="gray",
        ribbon_finish=(0.45, True, 1, 0.96, 0.55),
        ribbon_finish_lut=True,
        phases=phases,
    )


def deny_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.write_text

    def write(path: Path, *args: Any, **kwargs: Any) -> int:
        if path.name.endswith(".ribbon-lut.json"):
            raise OSError(errno.ENOSPC, "unit sidecar fault")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)


def setup_gate(monkeypatch: pytest.MonkeyPatch, passed: bool) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))
    monkeypatch.setattr(
        ribbon_lut, "qualify_ribbon_lut", lambda *args: {"passed": passed, "sampling": "identity"}
    )


def test_false_gate_remains_primary_when_sidecar_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_gate(monkeypatch, False)
    deny_sidecar(monkeypatch)
    feed = Mock()
    monkeypatch.setattr(encode, "run_argv_stdin", feed)
    phases = PhaseTimes()
    with pytest.raises(encode.EncodeError, match="qualification did not pass") as caught:
        invoke(tmp_path, phases)
    assert "persistence failed" in " ".join(caught.value.__notes__)
    assert phases.extras["ribbon_finish_lut"]["diagnostic_persistence_error"]
    assert phases.extras["ribbon_finish_lut"]["temporary_masks_removed"]
    feed.assert_not_called()


@pytest.mark.parametrize("read_fault", [False, True])
def test_iterator_error_survives_diagnostic_write_and_optional_read_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_fault: bool,
) -> None:
    setup_gate(monkeypatch, True)
    deny_sidecar(monkeypatch)
    primary = RuntimeError("unit iterator primary")

    def fail(*args: Any, **kwargs: Any) -> Any:
        kwargs["stderr_path"].write_text("unit drained stderr")
        raise primary

    monkeypatch.setattr(encode, "run_argv_stdin", fail)
    original = Path.read_text

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if read_fault and path.name == "encode.stderr":
            raise PermissionError(errno.EACCES, "unit diagnostic read fault")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    phases = PhaseTimes()
    with pytest.raises(RuntimeError, match="iterator primary") as caught:
        invoke(tmp_path, phases)
    assert caught.value is primary
    value = phases.extras["ribbon_finish_lut"]
    assert value["status"] == "failed" and value["temporary_masks_removed"]
    assert value["diagnostic_persistence_error"]
    assert ("diagnostic_errors" in value) is read_fault
    assert "persistence failed" in " ".join(primary.__notes__)


def test_sidecar_only_failure_is_explicit_after_successful_encode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_gate(monkeypatch, True)
    deny_sidecar(monkeypatch)
    monkeypatch.setattr(
        encode, "run_argv_stdin", Mock(return_value=CompletedProcess([], 0, b"", b""))
    )
    phases = PhaseTimes()
    with pytest.raises(OSError, match="unit sidecar fault"):
        invoke(tmp_path, phases)
    value = phases.extras["ribbon_finish_lut"]
    assert value["returncode"] == 0 and value["status"] == "failed"
    assert value["diagnostic_persistence_error"] and value["temporary_masks_removed"]


def test_qualification_diagnostic_read_does_not_replace_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_gate(monkeypatch, False)

    def qualify(tool: str, root: Path) -> Any:
        root.mkdir()
        (root / "unit.stderr").write_text("unit qualifier stderr")
        raise ValueError("unit qualifier primary")

    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", qualify)
    original = Path.read_text

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path.name == "unit.stderr":
            raise PermissionError(errno.EACCES, "unit qualifier read fault")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    phases = PhaseTimes()
    with pytest.raises(encode.EncodeError, match="qualifier primary") as caught:
        invoke(tmp_path, phases)
    assert caught.value.__cause__ is not None
    assert "diagnostic read failed" in " ".join(caught.value.__cause__.__notes__)
    value = phases.extras["ribbon_finish_lut"]
    assert value["diagnostic_errors"] and value["temporary_masks_removed"]
