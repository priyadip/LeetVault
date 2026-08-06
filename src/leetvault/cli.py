"""Typer entry point wiring all leetvault subcommands."""

from __future__ import annotations

import sys

import typer
from rich.console import Console

if sys.platform == "win32":
    # Legacy Windows consoles (cp1252 etc.) can't encode the Unicode spinner/bar glyphs
    # rich's Win32 console API path emits, which crashes `import`/`sync`/`watch` progress
    # bars outright. Force UTF-8 + a non-legacy render path so those glyphs just work.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(
    name="leetvault",
    help="Mirror your LeetCode account into a normalized SQLite DB and a GitHub dashboard repo.",
    no_args_is_help=True,
)
console = Console(legacy_windows=False)


@app.command()
def login(
    leetcode_only: bool = typer.Option(
        False, "--leetcode", help="Only refresh the LeetCode session; leave the GitHub PAT alone."
    ),
    github_only: bool = typer.Option(
        False, "--github", help="Only refresh the GitHub PAT; leave the LeetCode session alone."
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-prompt even for credentials that are still valid."
    ),
) -> None:
    """Store LEETCODE_SESSION + csrftoken (and optionally a GitHub PAT) in the OS keyring.

    Only prompts for what's actually missing or expired - already-valid credentials are
    left untouched.
    """
    from leetvault.auth import run_login

    if leetcode_only and github_only:
        console.print("[red]--leetcode and --github are mutually exclusive.[/red]")
        raise typer.Exit(code=1)

    run_login(console, leetcode_only=leetcode_only, github_only=github_only, force=force)


@app.command(name="import")
def import_(
    site: str = typer.Option("com", "--site", help="LeetCode site: com or cn."),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Disable same-day dedup; keep every accepted submission."
    ),
) -> None:
    """Full history import of all accepted submissions (resumable)."""
    from leetvault.sync import run_import

    run_import(console, site=site, keep_all=keep_all)


@app.command()
def sync(
    site: str = typer.Option("com", "--site", help="LeetCode site: com or cn."),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Disable same-day dedup; keep every accepted submission."
    ),
) -> None:
    """Incremental sync: pick up new accepted submissions since the last sync."""
    from leetvault.sync import run_sync

    run_sync(console, site=site, keep_all=keep_all)


@app.command()
def watch(
    interval: int = typer.Option(90, "--interval", help="Polling interval in seconds (60-120)."),
    site: str = typer.Option("com", "--site", help="LeetCode site: com or cn."),
) -> None:
    """Poll for new accepted submissions and sync+push automatically."""
    from leetvault.watch import run_watch

    run_watch(console, interval=interval, site=site)


@app.command()
def ai(
    disable: bool = typer.Option(False, "--disable", help="Turn AI analysis off."),
    set_key: str | None = typer.Option(
        None,
        "--set-key",
        metavar="PROVIDER",
        help="Store an API key for gemini, groq, nvidia, or anthropic.",
    ),
    show: bool = typer.Option(False, "--show", help="Print the current AI settings."),
) -> None:
    """Set up optional AI-generated solution analysis (off by default).

    Detects which backends are usable on this machine - a local model via Ollama, the
    Claude Code CLI, a free Gemini, Groq or NVIDIA NIM API key, or the Anthropic API - and
    lets you pick one. Nothing is enabled, downloaded, or billed unless you choose it.
    """
    from leetvault.ai_setup import run_ai_setup

    run_ai_setup(console, disable=disable, set_key=set_key, show=show)


@app.command()
def analyze(
    problem: str | None = typer.Argument(
        None, help="Problem slug, number, or part of its title. Omit with --all or --from."
    ),
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Backend to use instead of the configured one."
    ),
    model: str | None = typer.Option(None, "--model", help="Model override for this run."),
    all_: bool = typer.Option(False, "--all", help="Re-analyse every problem."),
    from_: str | None = typer.Option(
        None, "--from", help="Re-analyse only what a given provider generated, e.g. groq."
    ),
    list_: bool = typer.Option(
        False, "--list", help="Show which model wrote each analysis and exit."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the overwrite confirmation."),
) -> None:
    """Regenerate an existing analysis.md with a different AI backend.

    `sync` only fills gaps, so an analysis you dislike stays forever. This overwrites on
    purpose: one problem, everything a given provider wrote, or the lot.

        leetvault analyze --list                 # who wrote what
        leetvault analyze two-sum -p nvidia      # redo one problem
        leetvault analyze --from groq -p nvidia  # redo everything Groq wrote
    """
    from leetvault.analyze import run_analyze

    run_analyze(
        console,
        target=problem,
        provider_name=provider,
        model=model,
        all_=all_,
        from_=from_,
        show_list=list_,
        assume_yes=yes,
    )


@app.command()
def commands(
    full: bool = typer.Option(
        False, "--full", help="Include every argument and option for each command."
    ),
) -> None:
    """List every leetvault command and what it does.

    Generated from the CLI itself, so it can never fall behind the actual commands.
    """
    from leetvault.commands import run_commands

    run_commands(console, full=full)


@app.command()
def status() -> None:
    """Show session validity/expiry, sync state, and repo config."""
    from leetvault.auth import run_status

    run_status(console)


@app.command()
def logout() -> None:
    """Remove stored credentials from the OS keyring."""
    from leetvault.auth import run_logout

    run_logout(console)


@app.command()
def config(
    key: str | None = typer.Argument(None, help="Config key to get/set, e.g. repo.url."),
    value: str | None = typer.Argument(None, help="Value to set; omit to read."),
) -> None:
    """Get or set persistent config (repo URL, DB path, dedup window, etc.)."""
    from leetvault.config import run_config

    run_config(console, key=key, value=value)


if __name__ == "__main__":
    app()
