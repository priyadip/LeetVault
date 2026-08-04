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


def check_leetcode_session(site: str) -> tuple[bool, str]:
    """Is the stored LeetCode session usable? Returns (ok, human-readable reason).

    Checks expiry locally first so an obviously-dead session costs no network call.
    """
    creds = load_leetcode_credentials(site)
    if creds is None:
        return False, "no session stored"

    expiry = decode_session_expiry(creds.leetcode_session)
    if expiry is not None and expiry <= datetime.now(tz=UTC):
        return False, f"session expired at {expiry.isoformat()}"

    try:
        with LeetCodeClient(creds, site=site) as client:
            user = client.validate_session()
    except Exception as exc:  # noqa: BLE001 - any failure means "can't rely on it"
        return False, f"session check failed: {exc}"

    if not user.is_signed_in:
        return False, "session rejected by LeetCode"
    return True, f"signed in as {user.username}"


def check_github_pat() -> tuple[bool, str]:
    """Is the stored GitHub PAT usable? Returns (ok, human-readable reason)."""
    from leetvault.git_writer import validate_github_pat

    pat = load_github_pat()
    if pat is None:
        return False, "no PAT stored"
    login = validate_github_pat(pat)
    if login is None:
        return False, "stored PAT was rejected by GitHub (revoked or expired?)"
    return True, f"valid for {login}"


def run_login(
    console: Console,
    *,
    leetcode_only: bool = False,
    github_only: bool = False,
    force: bool = False,
) -> None:
    from leetvault.config import ConfigStore

    store = ConfigStore()
    site = store.get("site") or "com"
    console.print(f"[bold]leetvault login[/bold] (site: {site})")

    did_anything = False
    if not github_only:
        did_anything |= _login_leetcode(console, site, force=force)
    if not leetcode_only:
        # `--github` is itself the user asking for a PAT, so don't also ask "do you want
        # one?" - only the implicit (bare `leetvault login`) path needs that opt-in.
        did_anything |= _login_github(console, force=force, explicit=github_only)

    if not did_anything:
        console.print(
            "\n[green]Nothing to do - all credentials are already valid.[/green] "
            "Use --force to replace them anyway."
        )


def _login_leetcode(console: Console, site: str, *, force: bool) -> bool:
    """Prompt for + store LeetCode cookies. Returns True if anything was changed."""
    if not force:
        ok, reason = check_leetcode_session(site)
        if ok:
            console.print(f"[green]LeetCode:[/green] already valid ({reason}) - skipping.")
            return False
        console.print(f"[yellow]LeetCode:[/yellow] needs refresh ({reason}).")

    console.print(
        "Paste the LEETCODE_SESSION and csrftoken cookie values from a signed-in "
        f"leetcode.{'cn' if site == 'cn' else 'com'} browser session "
        "(DevTools -> Application -> Cookies)."
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
    return True


def _login_github(console: Console, *, force: bool, explicit: bool = False) -> bool:
    """Prompt for + store a GitHub PAT. Returns True if anything was changed."""
    from leetvault.git_writer import validate_github_pat

    if not force:
        ok, reason = check_github_pat()
        if ok:
            console.print(f"[green]GitHub:[/green] PAT already stored and {reason} - skipping.")
            return False
        if load_github_pat() is None and not explicit:
            # Nothing stored and none required - GitHub push is optional, so ask first.
            try:
                wants_pat = typer.confirm(
                    "Store a GitHub PAT now, for automatic commit/push? "
                    "(fine-grained, scoped to one repo, Contents: write)",
                    default=False,
                )
            except (typer.Abort, EOFError, OSError):
                return False  # non-interactive (tests, piped input) - just skip
            if not wants_pat:
                return False
        else:
            console.print(f"[yellow]GitHub:[/yellow] {reason}")

    pat = typer.prompt("GitHub PAT", hide_input=True)
    login = validate_github_pat(pat)
    if login is None:
        console.print("[red]GitHub PAT validation failed; not stored.[/red]")
        return False
    store_github_pat(pat)
    console.print(f"[green]GitHub PAT stored[/green] (validated as {login!r}).")
    return True


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
            f"[red]Session expired at {expiry.isoformat()}. Run `leetvault login --leetcode`.[/red]"
        )
    else:
        remaining = expiry - now
        console.print(
            f"[green]Session valid[/green], expires {expiry.isoformat()} "
            f"({remaining.days}d remaining)."
        )

    if load_github_pat() is None:
        console.print("GitHub PAT: [yellow]not stored[/yellow]")
    else:
        pat_ok, pat_reason = check_github_pat()
        if pat_ok:
            console.print(f"GitHub PAT: [green]stored, {pat_reason}[/green]")
        else:
            console.print(f"GitHub PAT: [red]{pat_reason}[/red] - run `leetvault login --github`.")


def run_logout(console: Console) -> None:
    from leetvault.config import ConfigStore

    store = ConfigStore()
    site = store.get("site") or "com"
    clear_leetcode_credentials(site)
    console.print(f"[green]Removed stored LeetCode credentials for site '{site}'.[/green]")
