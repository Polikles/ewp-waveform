from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ewp_waveform.application.render_fixed import _read_lut_diagnostic
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_performance
from ewp_waveform.config.models import PerformanceProfile
from ewp_waveform.ffmpeg import encode, ribbon_lut


@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [], {}])
def test_profile_requires_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError, match="explicit boolean"):
        PerformanceProfile(schema_version=1, name="bad", processing={"ribbon_finish_lut": value})


def test_profile_is_explicit_and_default_profiles_unchanged() -> None:
    profile = load_performance("ribbon-lut")
    assert profile.processing["ribbon_finish_lut"] is True
    assert profile.processing["jobs"] == 1
    assert "ribbon_finish_lut" not in load_performance("balanced").processing


@pytest.mark.parametrize(
    "options",
    [
        {"png_dir": Path("png")},
        {"prores_path": None},
        {"ribbon_finish": None},
        {"ribbon_finish_lut": "true"},
    ],
)
def test_encoder_refuses_unsupported_before_tool_or_feed(
    monkeypatch: pytest.MonkeyPatch, options: dict[str, Any]
) -> None:
    tool = Mock()
    monkeypatch.setattr(encode, "require_tool", tool)
    kwargs: dict[str, Any] = dict(
        width=32,
        height=32,
        fps=10,
        glow=0,
        png_dir=None,
        prores_path=Path("out.mov"),
        ribbon_finish=(0.45, True, 1, 0.96, 0.55),
        ribbon_finish_lut=True,
    )
    with pytest.raises(ValueError):
        encode.encode_rgba_stream(iter(()), **{**kwargs, **options})
    tool.assert_not_called()


@pytest.mark.parametrize("gate", [False, "true", 1, None])
def test_failed_gate_never_feeds_and_keeps_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: object
) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))
    qualifier = Mock(return_value={"passed": gate, "sampling": "identity"})
    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", qualifier)
    feed = Mock()
    monkeypatch.setattr(encode, "run_argv_stdin", feed)
    phases = PhaseTimes()
    out = tmp_path / "out.mov"
    with pytest.raises(encode.EncodeError, match="did not pass"):
        encode.encode_rgba_stream(
            iter(()),
            width=32,
            height=32,
            fps=10,
            glow=0,
            png_dir=None,
            prores_path=out,
            color="#C7E6EC",
            pix_fmt="gray",
            ribbon_finish=(0.45, True, 1, 0.96, 0.55),
            ribbon_finish_lut=True,
            phases=phases,
        )
    feed.assert_not_called()
    assert qualifier.call_args.args[0] == "/selected/ffmpeg"
    value = json.loads(out.with_suffix(".ribbon-lut.json").read_text())
    assert value["status"] == "failed" and value["temporary_masks_removed"]
    assert value == phases.extras["ribbon_finish_lut"]
    assert not list(tmp_path.glob(".ribbon-lut-*")) and not out.exists()


def test_default_encoder_never_qualifies_or_writes_lut_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))
    qualifier = Mock()
    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", qualifier)
    feed = Mock(return_value=Mock(returncode=0, stderr=b""))
    monkeypatch.setattr(encode, "run_argv_stdin", feed)
    selections: tuple[dict[str, Any], ...] = ({}, {"ribbon_finish_lut": False})
    for index, options in enumerate(selections):
        encode.encode_rgba_stream(
            iter(()),
            width=32,
            height=32,
            fps=10,
            glow=0,
            png_dir=None,
            prores_path=tmp_path / f"out-{index}.mov",
            color="#C7E6EC",
            pix_fmt="gray",
            ribbon_finish=(0.45, True, 1, 0.96, 0.55),
            **options,
        )
    qualifier.assert_not_called()
    commands = [call.args[0][:-1] for call in feed.call_args_list]
    assert (
        commands[0] == commands[1]
        and ",geq=" in commands[0][commands[0].index("-filter_complex") + 1]
    )
    assert not list(tmp_path.glob("*.ribbon-lut.json"))


@pytest.mark.parametrize("width,height", [(2, 32), (32, 2), (16385, 32)])
def test_unsupported_geometry_never_feeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int, height: int
) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))
    monkeypatch.setattr(
        ribbon_lut, "qualify_ribbon_lut", lambda *args: {"passed": True, "sampling": "identity"}
    )
    feed = Mock()
    monkeypatch.setattr(encode, "run_argv_stdin", feed)
    with pytest.raises(encode.EncodeError, match="canvas dimensions"):
        encode.encode_rgba_stream(
            iter(()),
            width=width,
            height=height,
            fps=10,
            glow=0,
            png_dir=None,
            prores_path=tmp_path / "out.mov",
            color="#C7E6EC",
            pix_fmt="gray",
            ribbon_finish=(0.45, True, 1, 0.96, 0.55),
            ribbon_finish_lut=True,
        )
    feed.assert_not_called()
    assert not list(tmp_path.glob(".ribbon-lut-*"))


def test_failed_qualifier_retains_stderr_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))

    def fail(ffmpeg: str, root: Path) -> dict[str, object]:
        root.mkdir()
        (root / "control.stderr").write_text("real failure diagnostic")
        raise ValueError("oracle execution failed")

    monkeypatch.setattr(ribbon_lut, "qualify_ribbon_lut", fail)
    with pytest.raises(encode.EncodeError, match="oracle execution failed"):
        encode.encode_rgba_stream(
            iter(()),
            width=32,
            height=32,
            fps=10,
            glow=0,
            png_dir=None,
            prores_path=tmp_path / "out.mov",
            color="#C7E6EC",
            pix_fmt="gray",
            ribbon_finish=(0.45, True, 1, 0.96, 0.55),
            ribbon_finish_lut=True,
        )
    value = json.loads((tmp_path / "out.ribbon-lut.json").read_text())
    assert value["qualification_diagnostics"] == {
        "qualification/control.stderr": "real failure diagnostic"
    }
    assert value["qualification_seconds"] > 0 and value["temporary_masks_removed"]


def test_generator_failure_keeps_drained_stderr_and_cleans_masks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(encode, "require_tool", lambda _: Path("/selected/ffmpeg"))
    monkeypatch.setattr(
        ribbon_lut, "qualify_ribbon_lut", lambda *args: {"passed": True, "sampling": "identity"}
    )

    def feed(argv: list[str], frames: object, *, phases: object, stderr_path: Path) -> None:
        stderr_path.write_text("retained encoder stderr before iterator failure")
        raise RuntimeError("iterator failed")

    monkeypatch.setattr(encode, "run_argv_stdin", feed)
    with pytest.raises(RuntimeError, match="iterator failed"):
        encode.encode_rgba_stream(
            iter(()),
            width=32,
            height=32,
            fps=10,
            glow=0,
            png_dir=None,
            prores_path=tmp_path / "out.mov",
            color="#C7E6EC",
            pix_fmt="gray",
            ribbon_finish=(0.45, True, 1, 0.96, 0.55),
            ribbon_finish_lut=True,
        )
    value = json.loads((tmp_path / "out.ribbon-lut.json").read_text())
    assert value["status"] == "failed" and value["temporary_masks_removed"]
    assert value["stderr"] == "retained encoder stderr before iterator failure"
    assert not Path(value["prepared"]["mask_path"]).exists()


@pytest.mark.parametrize("text", ["{", "[]", "null"])
def test_damaged_worker_diagnostic_cannot_mask_failure(tmp_path: Path, text: str) -> None:
    path = tmp_path / "worker.json"
    path.write_text(text)
    assert _read_lut_diagnostic(path)["status"] == "unavailable"
