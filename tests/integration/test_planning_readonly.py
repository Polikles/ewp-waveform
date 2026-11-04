from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ewp_waveform.application import service
from ewp_waveform.cli import app
from ewp_waveform.domain.diagnostics import DiagnosticCode, Severity
from tests.integration.test_render import NO_CHUNKS, TINY_PRESET, _tone_wav, _write


def _tree(root: Path) -> dict[str, tuple[int, int, str | None]]:
    """Owned project paths only; reads may update atime but must not write."""
    paths = [root, *sorted(root.rglob("*"))]
    return {
        str(p.relative_to(root)): (
            p.stat().st_mode,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,
        )
        for p in paths
    }


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("entry", ["api", "dry-run", "inspect"])
def test_planning_preserves_owned_paths(tmp_path: Path, existing: bool, entry: str) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    out = tmp_path / "nested" / "out"
    if existing:
        out.mkdir(parents=True)
        (out / "retained_results.json").write_text("retained\n")
        for name in ["work", "cache"]:
            (out / name).mkdir()
            (out / name / "sentinel").write_text(name)
    before = _tree(tmp_path)
    if entry == "api":
        _, _, _, plans, _ = service.plan_jobs(src, output_dir=out, preset_name=str(preset))
        assert len(plans) == 1
        assert plans[0].action == "PROCESS"
        assert plans[0].mov_path is not None
        assert plans[0].mov_path.is_relative_to(out)
        assert plans[0].render_signature
    else:
        args = [entry, str(src)]
        if entry == "dry-run":
            args += ["--output-dir", str(out), "--preset", str(preset)]
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "PROCESS" in result.output if entry == "dry-run" else "s0e00" in result.output
    assert _tree(tmp_path) == before


def test_default_output_and_readonly_existing_root(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    before = _tree(tmp_path)
    _, _, _, plans, _ = service.plan_jobs(src)
    assert plans[0].mov_path is not None
    assert plans[0].mov_path.is_relative_to(tmp_path / "waveform-output")
    assert _tree(tmp_path) == before
    out = tmp_path / "readonly"
    out.mkdir()
    out.chmod(0o555)
    try:
        before = _tree(tmp_path)
        service.plan_jobs(src, output_dir=out)
        assert _tree(tmp_path) == before
    finally:
        out.chmod(0o755)


@pytest.mark.parametrize("existing", [False, True])
def test_space_warning_uses_existing_volume_without_changing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    out = tmp_path / "nested" / "out"
    if existing:
        out.mkdir(parents=True)
    checked: list[Path] = []

    def disk_usage(path: Path) -> object:
        assert path.is_dir()
        checked.append(path)
        return type("Usage", (), {"free": 1})()

    monkeypatch.setattr(service.shutil, "disk_usage", disk_usage)
    before = _tree(tmp_path)
    _, _, _, plans, diagnostics = service.plan_jobs(src, output_dir=out)
    assert checked == [out if existing else tmp_path]
    assert plans[0].mov_path is not None and plans[0].mov_path.is_relative_to(out)
    assert any(d.code == DiagnosticCode.W_OUTPUT_SPACE and d.path == str(out) for d in diagnostics)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError, OSError])
def test_unavailable_space_is_typed_warning_not_a_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[OSError]
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    out = tmp_path / "missing" / "out"

    def unavailable(path: Path) -> object:
        raise failure("space unavailable")

    monkeypatch.setattr(service.shutil, "disk_usage", unavailable)
    before = _tree(tmp_path)
    _, _, _, plans, diagnostics = service.plan_jobs(src, output_dir=out)
    assert plans[0].action == "PROCESS"
    warning = next(d for d in diagnostics if d.code == DiagnosticCode.W_OUTPUT_SPACE)
    assert warning.severity == Severity.WARNING
    assert warning.path == str(out)
    assert "Could not check available space" in warning.message
    assert _tree(tmp_path) == before


def test_inaccessible_ancestor_is_typed_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    out = tmp_path / "denied" / "out"
    original_stat = Path.stat

    def guarded_stat(path: Path, *, follow_symlinks: bool = True) -> object:
        if path == out.parent:
            raise PermissionError("ancestor denied")
        return original_stat(path, follow_symlinks=follow_symlinks)

    before = _tree(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", guarded_stat)
        _, _, _, _, diagnostics = service.plan_jobs(src, output_dir=out)
    assert any(d.code == DiagnosticCode.W_OUTPUT_SPACE for d in diagnostics)
    assert _tree(tmp_path) == before


def test_file_in_output_ancestry_does_not_mutate(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    before = _tree(tmp_path)
    _, _, _, _, diagnostics = service.plan_jobs(src, output_dir=blocked / "out")
    assert any(d.code == DiagnosticCode.W_OUTPUT_SPACE for d in diagnostics)
    assert _tree(tmp_path) == before


def test_render_still_creates_output_and_results(tmp_path: Path) -> None:
    src = tmp_path / "s0e00-Test.wav"
    _tone_wav(src)
    preset = _write(tmp_path / "tiny.toml", TINY_PRESET)
    perf = _write(tmp_path / "perf.toml", NO_CHUNKS)
    before = src.stat(), src.read_bytes()
    out = tmp_path / "nested" / "render"
    planned = service.plan_jobs(src, preset_name=str(preset), output_dir=out, formats=["png"])[3][0]
    assert not out.exists()
    result = service.render(
        src, preset_name=str(preset), performance_name=str(perf), output_dir=out, formats=["png"]
    )[0]
    assert result["job"]["status"] == "SUCCEEDED"  # type: ignore[index]
    assert Path(str(result["result_json"])).is_file()
    assert Path(str(result["run_json"])).is_file()
    assert planned.png_path is not None
    assert list(planned.png_path.glob("frame_*.png"))
    assert src.read_bytes() == before[1]
    assert src.stat().st_mtime_ns == before[0].st_mtime_ns
    assert stat.S_ISREG(src.stat().st_mode)
