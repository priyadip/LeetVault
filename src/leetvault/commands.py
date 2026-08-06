"""The `leetvault commands` command: every command in the package, and what it does.

Built by introspecting the Typer app rather than from a hand-written list. A hand-written
overview is wrong the moment someone adds a command and forgets to update it, and the
failure is silent - the reader simply never learns the command exists. Generating it from
the same object that defines the CLI makes that impossible: a command that runs is a
command that is listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table


@dataclass
class ParamInfo:
    flags: str
    help: str
    required: bool


@dataclass
class CommandInfo:
    name: str
    summary: str
    description: str
    arguments: list[ParamInfo] = field(default_factory=list)
    options: list[ParamInfo] = field(default_factory=list)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def collect_commands() -> list[CommandInfo]:
    """Every registered command, read off the live Typer app."""
    from leetvault.cli import app

    group = typer.main.get_command(app)
    commands = getattr(group, "commands", {})

    collected: list[CommandInfo] = []
    for name, command in sorted(commands.items()):
        full = (command.help or "").strip()
        # The first paragraph is the summary; the rest is detail worth keeping for --full.
        summary = _clean(full.split("\n\n")[0]) if full else ""
        arguments: list[ParamInfo] = []
        options: list[ParamInfo] = []
        for param in command.params:
            if param.name == "help":
                continue
            info = ParamInfo(
                flags=", ".join(param.opts),
                help=_clean(getattr(param, "help", None)),
                required=bool(param.required),
            )
            # `param_type_name` is click's own public discriminator, which avoids importing
            # click directly - typer vendors it, so a plain `import click` is not reliable.
            if getattr(param, "param_type_name", "") == "argument":
                arguments.append(info)
            else:
                options.append(info)
        collected.append(
            CommandInfo(
                name=name,
                summary=summary,
                description=full,
                arguments=arguments,
                options=options,
            )
        )
    return collected


def _print_overview(console: Console, commands: list[CommandInfo]) -> None:
    table = Table(title=f"leetvault - {len(commands)} commands")
    table.add_column("Command", style="bold")
    table.add_column("What it does")
    for command in commands:
        usage = command.name
        if command.arguments:
            usage += " " + " ".join(
                f"<{a.flags}>" if a.required else f"[{a.flags}]" for a in command.arguments
            )
        # Optional arguments render as [name], which rich reads as a style tag and drops
        # silently - the column simply loses them. Escape before handing it to the table.
        table.add_row(escape(usage), escape(command.summary))
    console.print(table)
    console.print(
        "\n[dim]leetvault commands --full[/dim] for every flag, "
        "or [dim]leetvault <command> --help[/dim] for one command."
    )


def _print_full(console: Console, commands: list[CommandInfo]) -> None:
    for index, command in enumerate(commands):
        if index:
            console.print()
        console.print(f"[bold]leetvault {command.name}[/bold]")
        for line in command.description.splitlines():
            console.print(f"  {escape(line)}" if line.strip() else "")
        # One width across both lists so arguments and options line up as a single column.
        params = command.arguments + command.options
        width = max((len(p.flags) for p in params), default=0)
        if command.arguments:
            console.print("\n  [bold]Arguments[/bold]")
            for arg in command.arguments:
                required = "required" if arg.required else "optional"
                flags = escape(arg.flags.ljust(width))
                console.print(f"    {flags}  {escape(arg.help)} [dim]({required})[/dim]")
        if command.options:
            console.print("\n  [bold]Options[/bold]")
            for opt in command.options:
                console.print(f"    {escape(opt.flags.ljust(width))}  {escape(opt.help)}")


def collect_global_options() -> list[ParamInfo]:
    """Flags accepted before any subcommand.

    These come from Typer rather than from leetvault, but they are still things a user can
    type, and a listing that claims to be complete has to account for them.
    """
    from leetvault.cli import app

    group = typer.main.get_command(app)
    return [
        ParamInfo(
            flags=", ".join(param.opts),
            help=_clean(getattr(param, "help", None)),
            required=bool(param.required),
        )
        for param in group.params
        if param.name != "help"
    ]


def run_commands(console: Console, *, full: bool) -> None:
    commands = collect_commands()
    if full:
        _print_full(console, commands)
    else:
        _print_overview(console, commands)

    globals_ = collect_global_options()
    # --help is real and universal but click supplies it implicitly, so it is not in
    # group.params; a listing that omits it would be incomplete in the one way this
    # command exists to prevent.
    rows = [*globals_, ParamInfo("--help", "Show help for the CLI or any command.", False)]
    width = max(len(p.flags) for p in rows)
    console.print("\n[bold]Global flags[/bold] [dim](usable with any command)[/dim]")
    for param in rows:
        console.print(f"  {escape(param.flags.ljust(width))}  {escape(param.help)}")
