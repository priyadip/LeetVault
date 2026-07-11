from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import typer
from httpx import Response
from rich.console import Console
from sqlalchemy import select

from leetvault import auth, sync
from leetvault.config import ConfigStore
from leetvault.db import get_or_create_sync_state, make_engine, make_session_factory, session_scope
from leetvault.models import Problem, Submission, SubmissionCode
from leetvault.sync import _resolve_dedup_window

_CATALOG_PAYLOAD = {
    "stat_status_pairs": [
        {
            "stat": {
                "question_id": 1,
                "question__title": "Two Sum",
                "question__title_slug": "two-sum",
                "frontend_question_id": 1,
            },
            "difficulty": {"level": 1},
            "paid_only": False,
        },
        {
            "stat": {
                "question_id": 2,
                "question__title": "Validate BST",
                "question__title_slug": "validate-bst",
                "frontend_question_id": 98,
            },
            "difficulty": {"level": 2},
            "paid_only": False,
        },
    ]
}

_TOPIC_TAGS = {
    "two-sum": ["Array", "Hash Table"],
    "validate-bst": ["Tree", "Binary Search Tree"],
}


def _submission(
    sub_id: int, question_id: int, slug: str, status: str, timestamp: int, code: str = "code"
) -> dict[str, object]:
    return {
        "id": sub_id,
        "question_id": question_id,
        "title": slug,
        "title_slug": slug,
        "status_display": status,
        "lang": "python3",
        "runtime": "10 ms",
        "memory": "10 MB",
        "timestamp": timestamp,
        "url": f"/submissions/detail/{sub_id}/",
        "code": code,
    }


def _graphql_callback(request: httpx.Request) -> Response:
    body = json.loads(request.content)
    query = body["query"]
    if "submissionDetails" in query:
        return Response(
            200,
            json={
                "data": {
                    "submissionDetails": {
                        "runtime": 10,
                        "runtimePercentile": 50.0,
                        "memory": 1000,
                        "memoryPercentile": 60.0,
                        "code": None,
                        "lang": {"name": "python3"},
                    }
                }
            },
        )
    if "questionData" in query:
        slug = body["variables"]["titleSlug"]
        tags = _TOPIC_TAGS.get(slug, [])
        return Response(
            200,
            json={"data": {"question": {"topicTags": [{"name": t} for t in tags]}}},
        )
    raise AssertionError(f"unexpected graphql query: {query}")


@pytest.fixture(autouse=True)
def _logged_in() -> None:
    auth.store_leetcode_credentials("com", "session-token", "csrf-token")


def _db_paths(tmp_path: Path) -> tuple[Path, Path]:
    store = ConfigStore()
    return store.resolved_db_path(), store.resolved_repo_path()


def test_run_import_requires_login() -> None:
    auth.clear_leetcode_credentials("com")
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        sync.run_import(console, site="com", keep_all=False)


def test_run_sync_requires_prior_import() -> None:
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        sync.run_sync(console, site="com", keep_all=False)


@respx.mock
def test_run_import_dedups_same_day_and_writes_files(tmp_path: Path) -> None:
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(300, 2, "validate-bst", "Accepted", 3000, code="q2-code"),
                    _submission(200, 1, "two-sum", "Accepted", 2000, code="q1-newer"),
                    _submission(150, 1, "two-sum", "Wrong Answer", 1500),
                    _submission(100, 1, "two-sum", "Accepted", 1000, code="q1-older"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    db_path, repo_path = _db_paths(tmp_path)
    engine = make_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        ids = set(session.scalars(select(Submission.submission_id)))
        assert ids == {300, 200}  # 100 deduped (same-day as 200), 150 not accepted

        two_sum = session.scalar(select(Problem).where(Problem.title_slug == "two-sum"))
        assert two_sum is not None
        assert {t.name for t in two_sum.topics} == {"Array", "Hash Table"}

    two_sum_dir = repo_path / "Problems" / "two-sum"
    assert (two_sum_dir / "latest.py").read_text(encoding="utf-8") == "q1-newer"
    assert (two_sum_dir / "history" / "submission_200.py").exists()
    assert not (two_sum_dir / "history" / "submission_100.py").exists()
    assert (two_sum_dir / "notes.md").exists()
    assert (two_sum_dir / "metadata.json").exists()

    validate_bst_dir = repo_path / "Problems" / "validate-bst"
    assert (validate_bst_dir / "latest.py").read_text(encoding="utf-8") == "q2-code"


@respx.mock
def test_run_import_second_call_is_noop(tmp_path: Path) -> None:
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(300, 2, "validate-bst", "Accepted", 3000, code="q2-code"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    # No routes registered this time: any stray HTTP call would raise inside respx.mock.
    with respx.mock:
        console2 = Console(record=True, width=200)
        sync.run_import(console2, site="com", keep_all=False)
    assert "already completed" in console2.export_text()


@respx.mock
def test_run_import_keep_all_disables_dedup(tmp_path: Path) -> None:
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(200, 1, "two-sum", "Accepted", 2000, code="q1-newer"),
                    _submission(100, 1, "two-sum", "Accepted", 1000, code="q1-older"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=True)

    db_path, repo_path = _db_paths(tmp_path)
    engine = make_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        ids = set(session.scalars(select(Submission.submission_id)))
    assert ids == {200, 100}

    history_dir = repo_path / "Problems" / "two-sum" / "history"
    assert (history_dir / "submission_200.py").exists()
    assert (history_dir / "submission_100.py").exists()
    # "latest" still reflects the newest submission only, not the older kept one.
    latest = repo_path / "Problems" / "two-sum" / "latest.py"
    assert latest.read_text(encoding="utf-8") == "q1-newer"


@respx.mock
def test_run_sync_only_processes_new_submissions(tmp_path: Path) -> None:
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    submissions_route = respx.get("https://leetcode.com/api/submissions/")
    submissions_route.mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(200, 1, "two-sum", "Accepted", 2000, code="q1-first"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    submissions_route.mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(400, 2, "validate-bst", "Accepted", 4000, code="q2-new"),
                    _submission(200, 1, "two-sum", "Accepted", 2000, code="q1-first"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )

    console2 = Console(record=True, width=200)
    sync.run_sync(console2, site="com", keep_all=False)

    db_path, repo_path = _db_paths(tmp_path)
    engine = make_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        ids = set(session.scalars(select(Submission.submission_id)))
    assert ids == {200, 400}
    assert (repo_path / "Problems" / "validate-bst" / "latest.py").read_text(
        encoding="utf-8"
    ) == "q2-new"


@respx.mock
def test_run_sync_updates_latest_when_problem_resolved_again_later(tmp_path: Path) -> None:
    # Regression test for a real bug: a first `import`/`sync` stores an accepted submission
    # for a problem; solving that same problem again later (even the same day, well within
    # the dedup window) must still update latest.py to the newer code, and must not be
    # silently dropped forever. The original dedup comparison used a raw subtraction that
    # went negative for this exact case (new timestamp > previously-kept timestamp),
    # and a negative number is always < the window, so it discarded every subsequent
    # solve to an already-known problem permanently.
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    submissions_route = respx.get("https://leetcode.com/api/submissions/")
    submissions_route.mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(100, 1, "two-sum", "Accepted", 1000, code="v1"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    # Solve the same problem again a minute later - well within the default 24h window.
    submissions_route.mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(300, 1, "two-sum", "Accepted", 1000 + 120, code="v3"),
                    _submission(200, 1, "two-sum", "Accepted", 1000 + 60, code="v2"),
                    _submission(100, 1, "two-sum", "Accepted", 1000, code="v1"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )

    console2 = Console(record=True, width=200)
    sync.run_sync(console2, site="com", keep_all=False)

    db_path, repo_path = _db_paths(tmp_path)
    engine = make_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        ids = set(session.scalars(select(Submission.submission_id)))
    # 100 (already in DB from import) and 300 (the newest resolve) are kept; 200, a
    # redundant in-between attempt within the window of the new latest, is dropped.
    assert ids == {100, 300}

    latest = repo_path / "Problems" / "two-sum" / "latest.py"
    assert latest.read_text(encoding="utf-8") == "v3"


@respx.mock
def test_run_import_backfills_sync_state_when_resumed_page_is_empty(tmp_path: Path) -> None:
    # Regression test: a run_import that resumes past the last real page (e.g. a prior run
    # committed data per-page but crashed before finalizing sync_state - this happened for
    # real against the live account, see PLAN.md Phase 3) must still backfill
    # last_submission_id/last_synced_timestamp from the DB, or a later `sync` can never find
    # its starting point.
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200, json={"submissions_dump": [], "has_next": False, "last_key": None}
        )
    )

    store = ConfigStore()
    engine = make_engine(store.resolved_db_path())
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        problem = Problem(
            question_id=1,
            frontend_id=1,
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            paid_only=False,
            url="https://leetcode.com/problems/two-sum/",
        )
        submission = Submission(
            submission_id=200,
            question_id=1,
            lang="python3",
            status="Accepted",
            runtime="10 ms",
            memory="10 MB",
            timestamp=2000,
            code_hash="hash",
            is_accepted=True,
        )
        submission.code = SubmissionCode(code="q1-code")
        problem.submissions.append(submission)
        session.add(problem)
        state = get_or_create_sync_state(session, "com")
        state.last_offset = 25  # simulates a prior run having already paged past all data
        session.add(state)

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, "com")
        assert state.last_submission_id == 200
        assert state.last_synced_timestamp == 2000
        assert state.last_full_import_completed_at is not None


def test_run_import_skips_github_when_unconfigured() -> None:
    console = Console(record=True, width=200)
    with respx.mock:
        respx.get("https://leetcode.com/api/problems/all/").mock(
            return_value=Response(200, json=_CATALOG_PAYLOAD)
        )
        respx.get("https://leetcode.com/api/submissions/").mock(
            return_value=Response(
                200, json={"submissions_dump": [], "has_next": False, "last_key": None}
            )
        )
        sync.run_import(console, site="com", keep_all=False)
    assert "GitHub not configured" in console.export_text()


@respx.mock
def test_run_import_commits_and_pushes_when_github_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get("https://leetcode.com/api/problems/all/").mock(
        return_value=Response(200, json=_CATALOG_PAYLOAD)
    )
    respx.get("https://leetcode.com/api/submissions/").mock(
        return_value=Response(
            200,
            json={
                "submissions_dump": [
                    _submission(200, 1, "two-sum", "Accepted", 2000, code="q1-code"),
                ],
                "has_next": False,
                "last_key": None,
            },
        )
    )
    respx.post("https://leetcode.com/graphql").mock(side_effect=_graphql_callback)

    store = ConfigStore()
    store.set("repo_url", "https://github.com/owner/repo.git")
    auth.store_github_pat("ghp_faketoken")

    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "leetvault.git_writer.push",
        lambda repo, repo_url, pat, branch="main": pushed.append((repo_url, pat)),
    )

    console = Console(record=True, width=200)
    sync.run_import(console, site="com", keep_all=False)

    assert pushed == [("https://github.com/owner/repo.git", "ghp_faketoken")]
    assert "Committed and pushed" in console.export_text()

    _, repo_path = _db_paths(tmp_path)
    from git import Repo

    repo = Repo(repo_path)
    assert "leetvault: import 1 accepted submissions" in repo.head.commit.message


def test_resolve_dedup_window_keep_all_flag() -> None:
    store = ConfigStore()
    assert _resolve_dedup_window(store, keep_all=True) == 0


def test_resolve_dedup_window_default() -> None:
    store = ConfigStore()
    assert _resolve_dedup_window(store, keep_all=False) == 86400


def test_resolve_dedup_window_explicit_zero_disables_dedup_persistently() -> None:
    # Regression test: `raw or 86400` previously treated an explicit 0 (falsy) the same as
    # unset, silently ignoring `leetvault config dedup_window_seconds 0` - the only way to
    # make --keep-all's effect permanent without retyping the flag every run.
    store = ConfigStore()
    store.set("dedup_window_seconds", 0)
    assert _resolve_dedup_window(store, keep_all=False) == 0


def test_resolve_dedup_window_custom_value() -> None:
    store = ConfigStore()
    store.set("dedup_window_seconds", 3600)
    assert _resolve_dedup_window(store, keep_all=False) == 3600
