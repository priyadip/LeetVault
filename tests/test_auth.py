from __future__ import annotations

import time

import jwt
import pytest
import respx
from httpx import Response
from rich.console import Console

from leetvault import auth


def _make_token(exp: int) -> str:
    return jwt.encode({"exp": exp}, key="x" * 32, algorithm="HS256")


def test_store_and_load_roundtrip() -> None:
    auth.store_leetcode_credentials("com", "session-value", "csrf-value")
    creds = auth.load_leetcode_credentials("com")
    assert creds is not None
    assert creds.leetcode_session == "session-value"
    assert creds.csrftoken == "csrf-value"


def test_load_missing_returns_none() -> None:
    assert auth.load_leetcode_credentials("com") is None


def test_sites_are_isolated() -> None:
    auth.store_leetcode_credentials("com", "com-session", "com-csrf")
    assert auth.load_leetcode_credentials("cn") is None


def test_clear_is_idempotent() -> None:
    auth.store_leetcode_credentials("com", "s", "c")
    auth.clear_leetcode_credentials("com")
    assert auth.load_leetcode_credentials("com") is None
    auth.clear_leetcode_credentials("com")


def test_github_pat_roundtrip() -> None:
    assert auth.load_github_pat() is None
    auth.store_github_pat("ghp_example")
    assert auth.load_github_pat() == "ghp_example"
    auth.clear_github_pat()
    assert auth.load_github_pat() is None


def test_decode_session_expiry() -> None:
    exp = int(time.time()) + 3600
    decoded = auth.decode_session_expiry(_make_token(exp))
    assert decoded is not None
    assert int(decoded.timestamp()) == exp


def test_decode_session_expiry_invalid_token_returns_none() -> None:
    assert auth.decode_session_expiry("not-a-jwt") is None


def test_decode_session_expiry_real_leetcode_shape() -> None:
    # Real LEETCODE_SESSION tokens carry no "exp" claim - only "refreshed_at" (unix
    # seconds) + "_session_expiry" (relative TTL seconds), confirmed against a live login.
    refreshed_at = int(time.time())
    session_expiry = 1_209_600  # 14 days, as observed live
    token = jwt.encode(
        {"refreshed_at": refreshed_at, "_session_expiry": session_expiry},
        key="x" * 32,
        algorithm="HS256",
    )
    decoded = auth.decode_session_expiry(token)
    assert decoded is not None
    assert int(decoded.timestamp()) == refreshed_at + session_expiry


def test_run_login_stores_credentials_on_valid_session(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(["fake.jwt.token", "csrf-value"])
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: next(prompts))  # type: ignore[attr-defined]

    with respx.mock:
        respx.post("https://leetcode.com/graphql").mock(
            return_value=Response(
                200, json={"data": {"userStatus": {"username": "tester", "isSignedIn": True}}}
            )
        )
        auth.run_login(Console(record=True))

    creds = auth.load_leetcode_credentials("com")
    assert creds is not None
    assert creds.leetcode_session == "fake.jwt.token"
    assert creds.csrftoken == "csrf-value"


def test_run_login_rejects_signed_out_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import typer

    prompts = iter(["fake.jwt.token", "csrf-value"])
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: next(prompts))  # type: ignore[attr-defined]

    with respx.mock:
        respx.post("https://leetcode.com/graphql").mock(
            return_value=Response(
                200, json={"data": {"userStatus": {"username": "", "isSignedIn": False}}}
            )
        )
        try:
            auth.run_login(Console(record=True))
            raised = False
        except typer.Exit:
            raised = True

    assert raised
    assert auth.load_leetcode_credentials("com") is None


def test_run_login_declines_github_pat_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(["fake.jwt.token", "csrf-value"])
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: next(prompts))  # type: ignore[attr-defined]
    monkeypatch.setattr(auth.typer, "confirm", lambda *a, **k: False)  # type: ignore[attr-defined]

    with respx.mock:
        respx.post("https://leetcode.com/graphql").mock(
            return_value=Response(
                200, json={"data": {"userStatus": {"username": "tester", "isSignedIn": True}}}
            )
        )
        auth.run_login(Console(record=True))

    assert auth.load_github_pat() is None


def test_run_login_stores_github_pat_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(["fake.jwt.token", "csrf-value", "ghp_mytoken"])
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: next(prompts))  # type: ignore[attr-defined]
    monkeypatch.setattr(auth.typer, "confirm", lambda *a, **k: True)  # type: ignore[attr-defined]

    with respx.mock:
        respx.post("https://leetcode.com/graphql").mock(
            return_value=Response(
                200, json={"data": {"userStatus": {"username": "tester", "isSignedIn": True}}}
            )
        )
        respx.get("https://api.github.com/user").mock(
            return_value=Response(200, json={"login": "octocat"})
        )
        auth.run_login(Console(record=True))

    assert auth.load_github_pat() == "ghp_mytoken"


def test_run_login_does_not_store_invalid_github_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(["fake.jwt.token", "csrf-value", "bad-token"])
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: next(prompts))  # type: ignore[attr-defined]
    monkeypatch.setattr(auth.typer, "confirm", lambda *a, **k: True)  # type: ignore[attr-defined]

    with respx.mock:
        respx.post("https://leetcode.com/graphql").mock(
            return_value=Response(
                200, json={"data": {"userStatus": {"username": "tester", "isSignedIn": True}}}
            )
        )
        respx.get("https://api.github.com/user").mock(return_value=Response(401, json={}))
        auth.run_login(Console(record=True))

    assert auth.load_github_pat() is None


def test_run_status_reports_not_logged_in() -> None:
    console = Console(record=True)
    auth.run_status(console)
    assert "Not logged in" in console.export_text()


def test_run_status_reports_valid_session() -> None:
    exp = int(time.time()) + 3600
    auth.store_leetcode_credentials("com", _make_token(exp), "csrf")
    console = Console(record=True)
    auth.run_status(console)
    assert "Session valid" in console.export_text()


def test_run_logout_clears_credentials() -> None:
    auth.store_leetcode_credentials("com", "s", "c")
    console = Console(record=True)
    auth.run_logout(console)
    assert auth.load_leetcode_credentials("com") is None
