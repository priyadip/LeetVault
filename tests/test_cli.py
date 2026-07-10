from typer.testing import CliRunner

from leetvault.cli import app

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("login", "import", "sync", "watch", "status", "logout", "config"):
        assert command in result.output


def test_login_stub_runs() -> None:
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0
