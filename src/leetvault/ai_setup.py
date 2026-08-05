"""The `leetvault ai` command: detect backends, let the user choose one, or turn it off.

Kept separate from `auth.py` because this is configuration rather than credentials - the
only secret involved (an optional Anthropic key) is delegated back to `auth.py`.
"""

from __future__ import annotations

import typer
from rich.console import Console

from leetvault.ai import available_providers, provider_names
from leetvault.config import ConfigStore

_SETUP_HINTS = {
    "ollama": (
        "Install from https://ollama.com, then pull a coding model:\n"
        "    ollama pull qwen2.5-coder:7b\n"
        "  Free and unlimited; runs entirely on your machine."
    ),
    "claude-cli": (
        "Install with:\n"
        "    npm install -g @anthropic-ai/claude-code\n"
        "  Then run `claude` once to sign in. Free if you already have a Claude subscription."
    ),
    "anthropic": (
        "Install the SDK and provide a key:\n"
        "    pip install anthropic\n"
        "  Then set ANTHROPIC_API_KEY, or store one with `leetvault ai --set-key`.\n"
        "  Billed per token - roughly a few cents per problem."
    ),
}


def run_ai_setup(console: Console, *, disable: bool, set_key: bool, show: bool) -> None:
    store = ConfigStore()

    if set_key:
        from leetvault.auth import store_anthropic_key

        key = typer.prompt("Anthropic API key", hide_input=True)
        store_anthropic_key(key)
        console.print("[green]Anthropic API key stored in the OS keyring.[/green]")
        return

    if disable:
        store.set("ai_notes_enabled", False)
        console.print(
            "[green]AI analysis disabled.[/green] Existing analysis.md files are left alone."
        )
        return

    if show:
        enabled = store.get("ai_notes_enabled")
        console.print(f"Enabled : {enabled}")
        console.print(f"Provider: {store.get('ai_provider') or '(none)'}")
        console.print(f"Model   : {store.get('ai_model') or '(provider default)'}")
        return

    console.print("[bold]AI solution analysis[/bold] - optional, off by default.\n")
    console.print(
        "When enabled, leetvault writes an analysis.md next to each solution explaining the "
        "approach, walking through your code, and covering complexity and edge cases.\n"
        "Your notes.md is never touched.\n"
    )

    found = available_providers()
    if not found:
        console.print("[yellow]No AI backend detected on this machine.[/yellow]\n")
        console.print("Any one of these enables the feature:\n")
        for name in provider_names():
            console.print(f"  [bold]{name}[/bold]")
            console.print(f"    {_SETUP_HINTS[name]}\n")
        console.print("Re-run `leetvault ai` once one is set up.")
        return

    console.print("[green]Available backends:[/green]\n")
    for i, info in enumerate(found, start=1):
        console.print(f"  {i}. [bold]{info.display}[/bold] - {info.detail} ({info.cost})")
    console.print()

    try:
        choice = typer.prompt(
            f"Enable which backend? (1-{len(found)}, or 0 to leave disabled)", default="0"
        )
    except (typer.Abort, EOFError, OSError):
        return

    try:
        index = int(choice)
    except ValueError:
        console.print("[red]Not a number; leaving AI analysis disabled.[/red]")
        return

    if index <= 0 or index > len(found):
        console.print("AI analysis left disabled.")
        return

    selected = found[index - 1]
    store.set("ai_provider", selected.name)
    store.set("ai_notes_enabled", True)
    console.print(
        f"\n[green]Enabled[/green] using [bold]{selected.display}[/bold]. "
        "The next `leetvault sync` will generate analysis for problems that don't have one."
    )
    console.print(
        "Disable any time with `leetvault ai --disable`; "
        "pick a model with `leetvault config ai_model <name>`."
    )
