"""Credential storage (OS keyring) and LeetCode session validation."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import jwt
import keyring
import typer
from keyring.errors import PasswordDeleteError
from rich.console import Console

from leetvault.client import LeetCodeClient, LeetCodeCredentials

SERVICE_NAME = "leetvault"
GITHUB_PAT_KEY = "github_pat"


def _session_key(site: str) -> str:
    return f"leetcode_session:{site}"


def _csrftoken_key(site: str) -> str:
    return f"leetcode_csrftoken:{site}"


def store_leetcode_credentials(site: str, leetcode_session: str, csrftoken: str) -> None:
    keyring.set_password(SERVICE_NAME, _session_key(site), leetcode_session)
    keyring.set_password(SERVICE_NAME, _csrftoken_key(site), csrftoken)


def load_leetcode_credentials(site: str) -> LeetCodeCredentials | None:
    session = keyring.get_password(SERVICE_NAME, _session_key(site))
    csrftoken = keyring.get_password(SERVICE_NAME, _csrftoken_key(site))
    if session is None or csrftoken is None:
        return None
    return LeetCodeCredentials(leetcode_session=session, csrftoken=csrftoken)


def clear_leetcode_credentials(site: str) -> None:
    for key in (_session_key(site), _csrftoken_key(site)):
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME, key)


def store_github_pat(pat: str) -> None:
    keyring.set_password(SERVICE_NAME, GITHUB_PAT_KEY, pat)


def load_github_pat() -> str | None:
    return keyring.get_password(SERVICE_NAME, GITHUB_PAT_KEY)


def clear_github_pat() -> None:
    with contextlib.suppress(PasswordDeleteError):
        keyring.delete_password(SERVICE_NAME, GITHUB_PAT_KEY)


def decode_session_expiry(leetcode_session: str) -> datetime | None:
    try:
        payload = jwt.decode(leetcode_session, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    # Real LEETCODE_SESSION tokens carry no standard "exp" claim - they carry
    # "refreshed_at" (unix seconds) + "_session_expiry" (a relative TTL in seconds,
    # observed as 1209600 = 14 days). Fall back to "exp" too in case that ever changes.
    exp = payload.get("exp")
    if exp is not None:
        return datetime.fromtimestamp(exp, tz=UTC)
    refreshed_at = payload.get("refreshed_at")
    session_expiry = payload.get("_session_expiry")
    if refreshed_at is not None and session_expiry is not None:
        return datetime.fromtimestamp(refreshed_at + session_expiry, tz=UTC)
    return None


def run_login(console: Console) -> None:
    from leetvault.config import ConfigStore

    store = ConfigStore()
    site = store.get("site") or "com"
    console.print(f"[bold]leetvault login[/bold] (site: {site})")
    console.print(
        "Paste the LEETCODE_SESSION and csrftoken cookie values from a signed-in "
        "leetcode.com browser session (DevTools -> Application -> Cookies)."
    )
    leetcode_session = typer.prompt("LEETCODE_SESSION", hide_input=True)
    csrftoken = typer.prompt("csrftoken", hide_input=True)

    credentials = LeetCodeCredentials(leetcode_session=leetcode_session, csrftoken=csrftoken)
    with LeetCodeClient(credentials, site=site) as client:
        try:
            user = client.validate_session()
        except Exception as exc:
            console.print(f"[red]Login validation failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if not user.is_signed_in:
        console.print("[red]Those cookies did not produce a signed-in session.[/red]")
        raise typer.Exit(code=1)

    store_leetcode_credentials(site, leetcode_session, csrftoken)
    expiry = decode_session_expiry(leetcode_session)
    expiry_note = f", expires {expiry.isoformat()}" if expiry else ""
    console.print(
        f"[green]Logged in as {user.username}[/green]{expiry_note}. "
        "Credentials stored in the OS keyring."
    )

    _maybe_store_github_pat(console)


def _maybe_store_github_pat(console: Console) -> None:
    from leetvault.git_writer import validate_github_pat

    try:
        wants_pat = typer.confirm(
            "Also store a GitHub PAT now, for automatic commit/push? "
            "(fine-grained, scoped to one repo, Contents: write)",
            default=False,
        )
    except (typer.Abort, EOFError, OSError):
        return  # non-interactive context (e.g. tests, piped input) - just skip

    if not wants_pat:
        return

    pat = typer.prompt("GitHub PAT", hide_input=True)
    login = validate_github_pat(pat)
    if login is None:
        console.print("[red]GitHub PAT validation failed; not stored.[/red]")
        return
    store_github_pat(pat)
    console.print(f"[green]GitHub PAT stored[/green] (validated as {login!r}).")


def run_status(console: Console) -> None:
    from leetvault.config import ConfigStore

    store = ConfigStore()
    site = store.get("site") or "com"
    creds = load_leetcode_credentials(site)
    if creds is None:
        console.print(f"[yellow]Not logged in for site '{site}'. Run `leetvault login`.[/yellow]")
        return

    expiry = decode_session_expiry(creds.leetcode_session)
    now = datetime.now(tz=UTC)
    if expiry is None:
        console.print("[yellow]Could not decode session expiry from the stored token.[/yellow]")
    elif expiry <= now:
        console.print(
            f"[red]Session expired at {expiry.isoformat()}. Run `leetvault login` again.[/red]"
        )
    else:
        remaining = expiry - now
        console.print(
            f"[green]Session valid[/green], expires {expiry.isoformat()} "
            f"({remaining.days}d remaining)."
        )

    pat = load_github_pat()
    pat_note = "[green]stored[/green]" if pat else "[yellow]not stored[/yellow]"
    console.print(f"GitHub PAT: {pat_note}")


def run_logout(console: Console) -> None:
    from leetvault.config import ConfigStore

    store = ConfigStore()
    site = store.get("site") or "com"
    clear_leetcode_credentials(site)
    console.print(f"[green]Removed stored LeetCode credentials for site '{site}'.[/green]")
