from __future__ import annotations

import time

import jwt
import pytest
import typer
from rich.console import Console

from leetvault import auth, watch


def _make_token(exp_in_seconds: int) -> str:
    refreshed_at = int(time.time())
    return jwt.encode(
        {"refreshed_at": refreshed_at, "_session_expiry": exp_in_seconds},
        key="x" * 32,
        algorithm="HS256",
    )


def test_run_watch_requires_login() -> None:
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        watch.run_watch(console, interval=90, site="com")


def test_run_watch_warns_below_recommended_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.store_leetcode_credentials("com", _make_token(1_000_000), "csrf")
    calls: list[int] = []
    monkeypatch.setattr(watch, "run_sync", lambda console, site, keep_all: calls.append(1))

    console = Console(record=True, width=200)
    watch.run_watch(console, interval=10, site="com", sleep_fn=lambda s: None, max_iterations=1)
    assert "below the recommended 60-120s" in console.export_text()
    assert calls == [1]


def test_run_watch_runs_sync_each_iteration_until_max(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.store_leetcode_credentials("com", _make_token(1_000_000), "csrf")
    calls: list[int] = []
    monkeypatch.setattr(watch, "run_sync", lambda console, site, keep_all: calls.append(1))

    sleeps: list[float] = []
    console = Console(record=True, width=200)
    watch.run_watch(
        console,
        interval=5,
        site="com",
        sleep_fn=lambda s: sleeps.append(s),
        max_iterations=3,
    )
    assert len(calls) == 3
    # 5 one-second sleeps between each pair of iterations while running (not after the last)
    assert len(sleeps) == 2 * 5


def test_run_watch_continues_after_a_failed_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.store_leetcode_credentials("com", _make_token(1_000_000), "csrf")
    calls: list[int] = []

    def fake_run_sync(console: Console, site: str, keep_all: bool) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise typer.Exit(code=1)

    monkeypatch.setattr(watch, "run_sync", fake_run_sync)

    console = Console(record=True, width=200)
    watch.run_watch(console, interval=60, site="com", sleep_fn=lambda s: None, max_iterations=2)
    assert len(calls) == 2
    assert "will retry next interval" in console.export_text()


def test_run_watch_continues_after_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.store_leetcode_credentials("com", _make_token(1_000_000), "csrf")
    calls: list[int] = []

    def fake_run_sync(console: Console, site: str, keep_all: bool) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(watch, "run_sync", fake_run_sync)

    console = Console(record=True, width=200)
    watch.run_watch(console, interval=60, site="com", sleep_fn=lambda s: None, max_iterations=2)
    assert len(calls) == 2
    assert "unexpected error this cycle" in console.export_text()


def test_warn_if_session_expiring_close_to_expiry() -> None:
    console = Console(record=True, width=200)
    watch._warn_if_session_expiring(console, _make_token(3600))  # 1h left
    assert "expires soon" in console.export_text()


def test_warn_if_session_expiring_far_from_expiry() -> None:
    console = Console(record=True, width=200)
    watch._warn_if_session_expiring(console, _make_token(30 * 24 * 3600))  # 30d left
    assert console.export_text() == ""


def test_warn_if_session_expiring_already_expired() -> None:
    console = Console(record=True, width=200)
    watch._warn_if_session_expiring(console, _make_token(-3600))  # expired 1h ago
    assert "expired at" in console.export_text()
