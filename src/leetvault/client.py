"""The only module in leetvault allowed to talk HTTP to LeetCode.

Wraps REST (`/api/submissions/`) and GraphQL (`userStatus`, `submissionDetails`,
`recentAcSubmissionList`) access behind one client, with a defensive rate limiter and
exponential-backoff retries per CLAUDE.md's empirical rate-limit notes.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import httpx
from httpx_retries import Retry, RetryTransport

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "leetvault/0.1 (+https://github.com/leetvault/leetvault)"

SITE_BASE_URLS: dict[str, str] = {
    "com": "https://leetcode.com",
    "cn": "https://leetcode.cn",
}

# (max_requests, window_seconds) - empirically ~480 sequential requests trips a 403 on .com;
# .cn is undocumented so we apply a much stricter default per CLAUDE.md.
_RATE_LIMITS: dict[str, tuple[int, float]] = {
    "com": (20, 10.0),
    "cn": (1, 10.0),
}


class LeetCodeAPIError(RuntimeError):
    """Raised on a GraphQL `errors` payload or an unexpected/missing response shape."""


@dataclass(frozen=True)
class LeetCodeCredentials:
    leetcode_session: str
    csrftoken: str


@dataclass
class RestSubmission:
    submission_id: int
    question_id: int
    title: str
    title_slug: str
    status_display: str
    lang: str
    runtime: str
    memory: str
    timestamp: int
    url: str
    code: str | None

    @property
    def is_accepted(self) -> bool:
        return self.status_display == "Accepted"


@dataclass
class SubmissionsPage:
    submissions: list[RestSubmission]
    has_next: bool
    last_key: str | None


@dataclass
class UserStatus:
    username: str
    is_signed_in: bool


@dataclass
class SubmissionDetail:
    # Unlike REST's pre-formatted "52 ms" / "16.1 MB" strings, GraphQL returns these
    # unformatted: runtime in milliseconds, memory in bytes (confirmed live).
    runtime: int | None
    runtime_percentile: float | None
    memory: int | None
    memory_percentile: float | None
    code: str | None
    lang: str | None


@dataclass
class RecentAcSubmission:
    submission_id: int
    title: str
    title_slug: str
    timestamp: int


@dataclass
class ProblemMeta:
    question_id: int
    frontend_id: int
    title: str
    title_slug: str
    difficulty: str
    paid_only: bool
    url: str


# stat_status_pairs[].difficulty.level from /api/problems/all/ - confirmed live.
_DIFFICULTY_LEVELS: dict[int, str] = {1: "Easy", 2: "Medium", 3: "Hard"}


class RateLimiter:
    """Sliding-window limiter: at most `max_requests` calls per `window_seconds`."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def _evict_expired(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
            self._timestamps.popleft()

    def acquire(self) -> None:
        now = time.monotonic()
        self._evict_expired(now)
        if len(self._timestamps) >= self.max_requests:
            sleep_for = self.window_seconds - (now - self._timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            self._evict_expired(now)
        self._timestamps.append(now)


class LeetCodeRetry(Retry):
    """1 -> 3 -> 9 -> 27s backoff on 403/429, per CLAUDE.md's empirical rate-limit notes."""

    def backoff_strategy(self) -> float:
        if self.backoff_factor == 0:
            return 0.0
        backoff: float = self.backoff_factor * (3**self.attempts_made)
        return min(backoff, self.max_backoff_wait)


_USER_STATUS_QUERY = """
query globalData {
  userStatus {
    username
    isSignedIn
  }
}
"""

_SUBMISSION_DETAILS_QUERY = """
query submissionDetails($submissionId: Int!) {
  submissionDetails(submissionId: $submissionId) {
    runtime
    runtimePercentile
    memory
    memoryPercentile
    code
    lang {
      name
    }
  }
}
"""

_RECENT_AC_SUBMISSIONS_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""


def _parse_submissions_page(payload: dict[str, Any]) -> SubmissionsPage:
    submissions = [
        RestSubmission(
            submission_id=int(item["id"]),
            question_id=int(item["question_id"]),
            title=item["title"],
            title_slug=item["title_slug"],
            status_display=item["status_display"],
            lang=item["lang"],
            runtime=item.get("runtime") or "",
            memory=item.get("memory") or "",
            timestamp=int(item["timestamp"]),
            url=item.get("url") or "",
            code=item.get("code"),
        )
        for item in payload.get("submissions_dump", [])
    ]
    return SubmissionsPage(
        submissions=submissions,
        has_next=bool(payload.get("has_next", False)),
        last_key=payload.get("last_key"),
    )


class LeetCodeClient:
    """Authed HTTP access to one LeetCode site (`com` or `cn`) for one account."""

    def __init__(
        self,
        credentials: LeetCodeCredentials,
        site: str = "com",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if site not in SITE_BASE_URLS:
            raise ValueError(f"unknown site {site!r}; expected one of {sorted(SITE_BASE_URLS)}")
        self.site = site
        max_requests, window = _RATE_LIMITS[site]
        self._limiter = RateLimiter(max_requests=max_requests, window_seconds=window)
        retry = LeetCodeRetry(
            total=5,
            backoff_factor=1.0,
            backoff_jitter=0.0,
            status_forcelist=(403, 429),
            allowed_methods=("GET", "POST"),
            respect_retry_after_header=True,
            max_backoff_wait=60.0,
        )
        base_url = SITE_BASE_URLS[site]
        self._client = httpx.Client(
            base_url=base_url,
            transport=RetryTransport(retry=retry),
            timeout=timeout,
            cookies={
                "LEETCODE_SESSION": credentials.leetcode_session,
                "csrftoken": credentials.csrftoken,
            },
            headers={
                "x-csrftoken": credentials.csrftoken,
                "Referer": f"{base_url}/",
                "User-Agent": USER_AGENT,
            },
        )

    def __enter__(self) -> LeetCodeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._limiter.acquire()
        return self._client.request(method, url, **kwargs)

    def get_submissions_page(self, offset: int, limit: int = 20) -> SubmissionsPage:
        response = self._request(
            "GET", "/api/submissions/", params={"offset": offset, "limit": limit}
        )
        response.raise_for_status()
        return _parse_submissions_page(response.json())

    def get_all_problems(self) -> list[ProblemMeta]:
        """Fetch the full problem catalog in one call - REST's submissions dump gives no
        difficulty/paid_only/frontend_id, so this fills those in for the `problems` table."""
        response = self._request("GET", "/api/problems/all/")
        response.raise_for_status()
        payload = response.json()
        base_url = SITE_BASE_URLS[self.site]
        problems = []
        for pair in payload.get("stat_status_pairs", []):
            stat = pair["stat"]
            title_slug = stat["question__title_slug"]
            level: int | None = (pair.get("difficulty") or {}).get("level")
            difficulty = (
                _DIFFICULTY_LEVELS.get(level, "Unknown") if level is not None else "Unknown"
            )
            problems.append(
                ProblemMeta(
                    question_id=int(stat["question_id"]),
                    frontend_id=int(stat["frontend_question_id"]),
                    title=stat["question__title"],
                    title_slug=title_slug,
                    difficulty=difficulty,
                    paid_only=bool(pair.get("paid_only", False)),
                    url=f"{base_url}/problems/{title_slug}/",
                )
            )
        return problems

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._request(
            "POST", "/graphql", json={"query": query, "variables": variables or {}}
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if payload.get("errors"):
            raise LeetCodeAPIError(str(payload["errors"]))
        return payload

    def validate_session(self) -> UserStatus:
        data = self.graphql(_USER_STATUS_QUERY)
        status = data.get("data", {}).get("userStatus") or {}
        return UserStatus(
            username=status.get("username") or "",
            is_signed_in=bool(status.get("isSignedIn")),
        )

    def submission_details(self, submission_id: int) -> SubmissionDetail:
        data = self.graphql(_SUBMISSION_DETAILS_QUERY, {"submissionId": submission_id})
        detail = data.get("data", {}).get("submissionDetails")
        if detail is None:
            raise LeetCodeAPIError(f"submissionDetails returned null for id={submission_id}")
        lang = detail.get("lang") or {}
        return SubmissionDetail(
            runtime=detail.get("runtime"),
            runtime_percentile=detail.get("runtimePercentile"),
            memory=detail.get("memory"),
            memory_percentile=detail.get("memoryPercentile"),
            code=detail.get("code"),
            lang=lang.get("name"),
        )

    def recent_ac_submissions(self, username: str, limit: int = 20) -> list[RecentAcSubmission]:
        data = self.graphql(_RECENT_AC_SUBMISSIONS_QUERY, {"username": username, "limit": limit})
        items = data.get("data", {}).get("recentAcSubmissionList") or []
        return [
            RecentAcSubmission(
                submission_id=int(item["id"]),
                title=item["title"],
                title_slug=item["titleSlug"],
                timestamp=int(item["timestamp"]),
            )
            for item in items
        ]
