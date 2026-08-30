from typer.testing import CliRunner

from ewp_waveform.cli import app

runner = CliRunner()


def test_preset_list_includes_iuris_default() -> None:
    result = runner.invoke(app, ["preset", "list"])
    assert result.exit_code == 0
    assert "iuris-default" in result.stdout
    assert "iuris-spectrum" in result.stdout
    assert "builtin" in result.stdout


def test_preset_show_iuris_default() -> None:
    result = runner.invoke(app, ["preset", "show", "iuris-default"])
    assert result.exit_code == 0
    assert "name: iuris-default" in result.stdout
    assert "domain: time" in result.stdout
    assert "fps: 60" in result.stdout


def test_performance_list_includes_balanced() -> None:
    result = runner.invoke(app, ["performance", "list"])
    assert result.exit_code == 0
    assert "balanced" in result.stdout


def test_performance_show_unknown_is_config_error() -> None:
    result = runner.invoke(app, ["performance", "show", "no-such-profile"])
    assert result.exit_code == 2
