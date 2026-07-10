from typer.testing import CliRunner

from leetvault.cli import app

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("login", "import", "sync", "watch", "status", "logout", "config"):
        assert command in result.output


def test_status_runs_when_logged_out() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Not logged in" in result.output


def test_logout_runs() -> None:
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
