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
    "gemini": (
        "Get a free API key at https://aistudio.google.com/apikey, then:\n"
        "    leetvault ai --set-key gemini\n"
        "  Free tier, cloud-hosted - needs no local hardware and no subscription."
    ),
    "groq": (
        "Get a free API key at https://console.groq.com/keys, then:\n"
        "    leetvault ai --set-key groq\n"
        "  Free tier, very fast, cloud-hosted - needs no local hardware."
    ),
    "nvidia": (
        "Get a free API key at https://build.nvidia.com, then:\n"
        "    leetvault ai --set-key nvidia\n"
        "  Free tier, cloud-hosted, very large open models - separate quota from Gemini/Groq."
    ),
    "anthropic": (
        "Install the SDK and provide a key:\n"
        "    pip install anthropic\n"
        "  Then set ANTHROPIC_API_KEY, or `leetvault ai --set-key anthropic`.\n"
        "  Billed per token - roughly a few cents per problem."
    ),
}

# Providers whose credential is a plain API key leetvault can store for the user.
_KEY_PROVIDERS = ("gemini", "groq", "nvidia", "anthropic")


def run_ai_setup(console: Console, *, disable: bool, set_key: str | None, show: bool) -> None:
    store = ConfigStore()

    if set_key is not None:
        from leetvault.auth import store_provider_key

        provider = set_key.strip().lower()
        if provider not in _KEY_PROVIDERS:
            console.print(
                f"[red]{provider!r} does not take an API key.[/red] "
                f"Key-based providers: {', '.join(_KEY_PROVIDERS)}."
            )
            raise typer.Exit(code=1)
        key = typer.prompt(f"{provider} API key", hide_input=True)
        store_provider_key(provider, key)
        console.print(f"[green]{provider} API key stored in the OS keyring.[/green]")
        console.print("Run `leetvault ai` to enable it.")
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
