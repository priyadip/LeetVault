from __future__ import annotations

import pytest
import respx
from httpx import Response

from leetvault.client import (
    LeetCodeAPIError,
    LeetCodeClient,
    LeetCodeCredentials,
    RateLimiter,
)

CREDS = LeetCodeCredentials(leetcode_session="session-token", csrftoken="csrf-token")


def test_unknown_site_rejected() -> None:
    with pytest.raises(ValueError, match="unknown site"):
        LeetCodeClient(CREDS, site="net")


@respx.mock
def test_get_submissions_page_parses_rest_shape() -> None:
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    {
                        "id": 42,
                        "question_id": 1,
                        "title": "Two Sum",
                        "title_slug": "two-sum",
                        "status_display": "Accepted",
                        "lang": "python3",
                        "runtime": "52 ms",
                        "memory": "16.1 MB",
                        "timestamp": 1700000000,
                        "url": "/submissions/detail/42/",
                        "code": "class Solution: pass",
                    }
                ],
                "has_next": True,
                "last_key": "abc",
            },
        )
    )
    with LeetCodeClient(CREDS) as client:
        page = client.get_submissions_page(offset=0)

    assert page.has_next is True
    assert page.last_key == "abc"
    assert len(page.submissions) == 1
    sub = page.submissions[0]
    assert sub.submission_id == 42
    assert sub.is_accepted is True
    assert sub.code == "class Solution: pass"


@respx.mock
def test_validate_session() -> None:
    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(
            200, json={"data": {"userStatus": {"username": "tester", "isSignedIn": True}}}
        )
    )
    with LeetCodeClient(CREDS) as client:
        status = client.validate_session()
    assert status.username == "tester"
    assert status.is_signed_in is True


@respx.mock
def test_graphql_errors_raise() -> None:
    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(200, json={"errors": [{"message": "boom"}]})
    )
    with LeetCodeClient(CREDS) as client, pytest.raises(LeetCodeAPIError):
        client.validate_session()


@respx.mock
def test_submission_details_parses_shape() -> None:
    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "submissionDetails": {
                        "runtime": "52 ms",
                        "runtimePercentile": 88.5,
                        "memory": "16.1 MB",
                        "memoryPercentile": 42.1,
                        "code": "class Solution: pass",
                        "lang": {"name": "python3"},
                    }
                }
            },
        )
    )
    with LeetCodeClient(CREDS) as client:
        detail = client.submission_details(42)
    assert detail.runtime_percentile == 88.5
    assert detail.lang == "python3"


@respx.mock
def test_recent_ac_submissions_parses_shape() -> None:
    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "recentAcSubmissionList": [
                        {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "100"}
                    ]
                }
            },
        )
    )
    with LeetCodeClient(CREDS) as client:
        items = client.recent_ac_submissions("tester")
    assert items[0].submission_id == 1
    assert items[0].title_slug == "two-sum"


def test_rate_limiter_sleeps_when_window_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_now = [0.0]
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return fake_now[0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now[0] += seconds

    monkeypatch.setattr("leetvault.client.time.monotonic", fake_monotonic)
    monkeypatch.setattr("leetvault.client.time.sleep", fake_sleep)

    limiter = RateLimiter(max_requests=2, window_seconds=10.0)
    limiter.acquire()
    fake_now[0] += 1.0
    limiter.acquire()
    fake_now[0] += 1.0
    limiter.acquire()  # third call within window must sleep

    assert sleeps == [pytest.approx(8.0)]


@respx.mock
def test_retries_on_403_then_succeeds() -> None:
    route = respx.get("https://leetcode.com/api/submissions/")
    route.side_effect = [
        Response(403, json={}),
        Response(200, json={"submissions_dump": [], "has_next": False, "last_key": None}),
    ]
    with LeetCodeClient(CREDS) as client:
        page = client.get_submissions_page(offset=0)  # one 1s backoff before the retry succeeds
    assert page.has_next is False
    assert route.call_count == 2


def test_leetcode_retry_backoff_sequence() -> None:
    from leetvault.client import LeetCodeRetry

    retry = LeetCodeRetry(backoff_factor=1.0, backoff_jitter=0.0, max_backoff_wait=120.0)
    delays = []
    for attempts in range(4):
        retry.attempts_made = attempts
        delays.append(retry.backoff_strategy())
    assert delays == [1.0, 3.0, 9.0, 27.0]


def test_close_is_safe_without_context_manager() -> None:
    client = LeetCodeClient(CREDS)
    client.close()
