"""Polling loop: reconcile SyncState and sync -> write -> README -> commit -> push.

Honest limit (per CLAUDE.md): this is polling, not real-time - LeetCode has no
webhook/streaming API. Each cycle is just a normal `sync` call, which already does the
DB write + README regenerate + commit/push in one pass.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime

import typer
from rich.console import Console

from leetvault.auth import decode_session_expiry, load_leetcode_credentials
from leetvault.sync import run_sync

_RECOMMENDED_MIN_INTERVAL_SECONDS = 60
_POLL_STEP_SECONDS = 1.0
_EXPIRY_WARNING_WINDOW = 24 * 3600


def _warn_if_session_expiring(console: Console, leetcode_session: str) -> None:
    expiry = decode_session_expiry(leetcode_session)
    if expiry is None:
        return
    remaining_seconds = (expiry - datetime.now(tz=UTC)).total_seconds()
    if 0 < remaining_seconds < _EXPIRY_WARNING_WINDOW:
        console.print(
            f"[yellow]LeetCode session expires soon ({expiry.isoformat()}) - "
            "run `leetvault login` again to refresh it.[/yellow]"
        )
    elif remaining_seconds <= 0:
        console.print(
            f"[red]LeetCode session expired at {expiry.isoformat()} - "
            "run `leetvault login` again.[/red]"
        )


def run_watch(
    console: Console,
    interval: int,
    site: str,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_iterations: int | None = None,
) -> None:
    creds = load_leetcode_credentials(site)
    if creds is None:
        console.print(f"[red]Not logged in for site '{site}'. Run `leetvault login` first.[/red]")
        raise typer.Exit(code=1)

    if interval < _RECOMMENDED_MIN_INTERVAL_SECONDS:
        console.print(
            f"[yellow]--interval {interval}s is below the recommended 60-120s polling "
            "window - LeetCode has no push/webhook API, so tighter polling just adds load "
            "without making detection meaningfully faster.[/yellow]"
        )

    console.print(
        f"[bold]leetvault watch[/bold]: polling every {interval}s (site: {site}). "
        "Press Ctrl+C to stop."
    )

    stop_requested = False

    def _handle_stop(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigint = signal.signal(signal.SIGINT, _handle_stop)
    previous_sigterm = (
        signal.signal(signal.SIGTERM, _handle_stop) if hasattr(signal, "SIGTERM") else None
    )

    iterations = 0
    try:
        while not stop_requested:
            _warn_if_session_expiring(console, creds.leetcode_session)
            try:
                run_sync(console, site=site, keep_all=False)
            except typer.Exit:
                console.print(
                    "[yellow]watch: this cycle failed; will retry next interval.[/yellow]"
                )
            except Exception as exc:  # noqa: BLE001 - a bad cycle must not kill the watcher
                console.print(f"[red]watch: unexpected error this cycle: {exc}[/red]")

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

            waited = 0.0
            while waited < interval and not stop_requested:
                sleep_fn(_POLL_STEP_SECONDS)
                waited += _POLL_STEP_SECONDS
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        console.print("[green]watch stopped.[/green]")
