import json
import tomllib

from typer.testing import CliRunner

from ewp_waveform import __version__
from ewp_waveform.application.results import build_run_summary
from ewp_waveform.cli import app
from ewp_waveform.paths import project_root


def test_scaffold_version_is_defined() -> None:
    assert __version__ == "0.2.1"


def test_product_version_declarations_agree() -> None:
    root = project_root()
    project = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    package = next(p for p in lock["package"] if p["name"] == "ewp-waveform")
    example = json.loads((root / "examples/results.example.json").read_text())
    assert project["project"]["version"] == package["version"] == __version__
    assert example["tool"]["version"] == __version__
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
    summary = build_run_summary(
        [], started_at="2026-11-04T00:00:00Z", completed_at="2026-11-04T00:00:01Z"
    )
    assert summary["tool"]["version"] == __version__
