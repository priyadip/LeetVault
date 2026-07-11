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
def login() -> None:
    """Store LEETCODE_SESSION + csrftoken (and optionally a GitHub PAT) in the OS keyring."""
    from leetvault.auth import run_login

    run_login(console)


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
