from __future__ import annotations

import typer
from rich.console import Console

from leetvault.cli import app
from leetvault.commands import collect_commands, run_commands


def _registered() -> dict[str, object]:
    """The commands Typer actually exposes - the only authority on what exists."""
    group = typer.main.get_command(app)
    return dict(group.commands)  # type: ignore[attr-defined]


def test_every_registered_command_is_collected() -> None:
    """The point of the command: a listing that cannot fall behind the CLI."""
    assert {c.name for c in collect_commands()} == set(_registered())


def test_every_registered_command_appears_in_the_output() -> None:
    """Collection being right is not enough - a rendering bug loses commands just as
    effectively. rich markup silently ate `[problem]` once already."""
    console = Console(record=True, width=200)
    run_commands(console, full=False)
    output = console.export_text()
    for name in _registered():
        assert name in output, f"{name} missing from the overview"


def test_full_output_lists_every_command_and_every_parameter() -> None:
    console = Console(record=True, width=200)
    run_commands(console, full=True)
    output = console.export_text()
    for name, command in _registered().items():
        assert f"leetvault {name}" in output, f"{name} missing from --full"
        for param in command.params:  # type: ignore[attr-defined]
            if param.name == "help":
                continue
            longest = max(param.opts, key=len)
            assert longest in output, f"{name}: parameter {longest} missing from --full"


def test_known_commands_are_present() -> None:
    """A blunt guard against a command being dropped from the CLI by accident."""
    names = {c.name for c in collect_commands()}
    assert {
        "ai",
        "analyze",
        "commands",
        "config",
        "import",
        "login",
        "logout",
        "status",
        "sync",
        "watch",
    } <= names


def test_every_command_has_a_summary() -> None:
    """A command with no docstring lists as a blank row, which is worse than useless."""
    for command in collect_commands():
        assert command.summary, f"{command.name} has no summary"


def test_arguments_and_options_are_classified_correctly() -> None:
    by_name = {c.name: c for c in collect_commands()}
    analyze = by_name["analyze"]
    assert [a.flags for a in analyze.arguments] == ["problem"]
    assert "--provider, -p" in [o.flags for o in analyze.options]
    assert [a.flags for a in by_name["config"].arguments] == ["key", "value"]
    assert by_name["status"].arguments == []
    assert by_name["status"].options == []


def test_optional_arguments_survive_rich_markup() -> None:
    """`[problem]` is valid rich markup for a style. Unescaped, the table rendered the row
    without it and the argument simply vanished."""
    console = Console(record=True, width=200)
    run_commands(console, full=False)
    output = console.export_text()
    assert "analyze [problem]" in output
    assert "config [key] [value]" in output


def test_commands_lists_itself() -> None:
    """It is a command too; omitting it would be its own kind of incompleteness."""
    assert "commands" in {c.name for c in collect_commands()}


def test_global_flags_are_listed_too() -> None:
    """Flags typed before a subcommand are still things a user can run. A listing that
    claims completeness cannot quietly stop at subcommands."""
    console = Console(record=True, width=200)
    run_commands(console, full=False)
    output = console.export_text()
    assert "--install-completion" in output
    assert "--show-completion" in output
    # click supplies --help implicitly, so it is absent from group.params and has to be
    # added deliberately - exactly the kind of omission this command exists to prevent.
    assert "--help" in output


def test_readme_documents_every_command() -> None:
    """The README drifted behind the CLI twice: `analyze` and `commands` both shipped
    without reaching it, and two edits meant to fix that silently matched nothing because
    they targeted "## Licence" against a file spelling it "## License". Checking against
    the live app is the only version of this that stays true."""
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for name in _registered():
        assert f"leetvault {name}" in readme, f"README does not mention `leetvault {name}`"


def test_readme_lists_every_ai_backend() -> None:
    """A backend nobody knows about is a backend nobody uses - and the quotas are separate,
    which is the whole reason to have several."""
    from pathlib import Path

    from leetvault.ai import provider_names

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    aliases = {"claude-cli": "Claude Code CLI", "nvidia": "NVIDIA", "anthropic": "Anthropic"}
    for name in provider_names():
        needle = aliases.get(name, name)
        assert needle.lower() in readme.lower(), f"README does not mention the {name} backend"
