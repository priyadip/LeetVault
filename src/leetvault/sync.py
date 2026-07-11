"""Import (full history) and sync (incremental) engines."""

from __future__ import annotations

import hashlib
import random
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from leetvault.auth import load_github_pat, load_leetcode_credentials
from leetvault.client import LeetCodeClient, ProblemMeta, RestSubmission
from leetvault.config import ConfigStore
from leetvault.db import (
    get_or_create_sync_state,
    make_engine,
    make_session_factory,
    session_scope,
)
from leetvault.git_writer import (
    GitWriterError,
    ensure_notes,
    sync_to_github,
    write_history,
    write_latest_and_metadata,
)
from leetvault.models import Problem, Submission, SubmissionCode, Topic
from leetvault.readme import generate_readme

_PAGE_LIMIT = 20
_PAGE_DELAY_RANGE = (0.3, 0.5)


def _sleep_between_pages() -> None:
    time.sleep(random.uniform(*_PAGE_DELAY_RANGE))


def _load_problem_catalog(client: LeetCodeClient) -> dict[int, ProblemMeta]:
    return {meta.question_id: meta for meta in client.get_all_problems()}


def _last_kept_timestamps(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(Submission.question_id, func.max(Submission.timestamp)).group_by(
            Submission.question_id
        )
    ).all()
    return {question_id: ts for question_id, ts in rows}


def _upsert_problem(
    session: Session, client: LeetCodeClient, meta: ProblemMeta, console: Console
) -> Problem:
    problem = session.get(Problem, meta.question_id)
    if problem is None:
        problem = Problem(
            question_id=meta.question_id,
            frontend_id=meta.frontend_id,
            title=meta.title,
            title_slug=meta.title_slug,
            difficulty=meta.difficulty,
            paid_only=meta.paid_only,
            url=meta.url,
        )
        session.add(problem)
        # Topic tags aren't in REST's submissions dump or /api/problems/all/ - fetch once
        # per newly-seen problem (not per submission) and cache in the DB forever.
        try:
            for topic_name in client.question_topics(meta.title_slug):
                topic = session.scalar(select(Topic).where(Topic.name == topic_name))
                if topic is None:
                    topic = Topic(name=topic_name)
                    session.add(topic)
                    session.flush()
                problem.topics.append(topic)
        except Exception as exc:  # noqa: BLE001 - topics are best-effort, never fatal
            console.print(f"[yellow]Could not fetch topics for {meta.title_slug}: {exc}[/yellow]")
    return problem


def _process_submission(
    *,
    session: Session,
    client: LeetCodeClient,
    repo_path: Path,
    catalog: dict[int, ProblemMeta],
    sub: RestSubmission,
    last_kept: dict[int, int],
    keep_all: bool,
    dedup_window_seconds: int,
    console: Console,
) -> bool:
    """Store + write one accepted submission to disk. Returns True if it was kept."""
    if not sub.is_accepted:
        return False
    if session.get(Submission, sub.submission_id) is not None:
        return False

    is_first_for_problem = sub.question_id not in last_kept
    if not keep_all and not is_first_for_problem:
        prior_timestamp = last_kept[sub.question_id]
        if prior_timestamp - sub.timestamp < dedup_window_seconds:
            return False

    meta = catalog.get(sub.question_id)
    if meta is None:
        console.print(
            f"[yellow]Skipping submission {sub.submission_id}: "
            f"question_id={sub.question_id} not found in the problem catalog.[/yellow]"
        )
        return False

    code = sub.code
    runtime_percentile: float | None = None
    memory_percentile: float | None = None
    try:
        detail = client.submission_details(sub.submission_id)
        runtime_percentile = detail.runtime_percentile
        memory_percentile = detail.memory_percentile
        if not code:
            code = detail.code
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        console.print(f"[yellow]submissionDetails failed for {sub.submission_id}: {exc}[/yellow]")

    if not code:
        console.print(
            f"[yellow]No code available for submission {sub.submission_id}; skipping.[/yellow]"
        )
        return False

    problem = _upsert_problem(session, client, meta, console)
    submission = Submission(
        submission_id=sub.submission_id,
        question_id=sub.question_id,
        lang=sub.lang,
        status=sub.status_display,
        runtime=sub.runtime,
        memory=sub.memory,
        runtime_percentile=runtime_percentile,
        memory_percentile=memory_percentile,
        timestamp=sub.timestamp,
        code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        is_accepted=True,
    )
    submission.code = SubmissionCode(code=code)
    problem.submissions.append(submission)
    session.add(submission)

    write_history(repo_path, meta.title_slug, sub.submission_id, sub.lang, code)
    if is_first_for_problem:
        write_latest_and_metadata(
            repo_path,
            meta,
            sub.submission_id,
            sub.lang,
            code,
            sub.timestamp,
            sub.runtime,
            sub.memory,
            runtime_percentile,
            memory_percentile,
        )
        ensure_notes(repo_path, meta)

    last_kept[sub.question_id] = sub.timestamp
    return True


def _regenerate_readme(factory: sessionmaker[Session], repo_path: Path) -> None:
    with session_scope(factory) as session:
        generate_readme(session, repo_path)


def _maybe_push_to_github(console: Console, repo_path: Path, message: str) -> None:
    store = ConfigStore()
    repo_url = store.get("repo_url")
    pat = load_github_pat()
    if not repo_url or not pat:
        console.print(
            "[yellow]GitHub not configured - skipping commit/push. Set a repo URL with "
            "`leetvault config repo_url <url>` and store a GitHub PAT via `leetvault login` "
            "to enable automatic commits.[/yellow]"
        )
        return
    try:
        sync_to_github(console, repo_path, repo_url, pat, message)
    except GitWriterError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


def run_import(console: Console, site: str, keep_all: bool) -> None:
    creds = load_leetcode_credentials(site)
    if creds is None:
        console.print(f"[red]Not logged in for site '{site}'. Run `leetvault login` first.[/red]")
        raise typer.Exit(code=1)

    store = ConfigStore()
    dedup_window = 0 if keep_all else int(store.get("dedup_window_seconds") or 86400)
    repo_path = store.resolved_repo_path()
    repo_path.mkdir(parents=True, exist_ok=True)

    engine = make_engine(store.resolved_db_path())
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site)
        if state.last_full_import_completed_at is not None:
            completed = datetime.fromtimestamp(
                state.last_full_import_completed_at, tz=UTC
            ).isoformat()
            console.print(
                f"[green]Full import already completed[/green] ({completed}). "
                "Run `leetvault sync` for incremental updates."
            )
            return
        offset = state.last_offset
        last_kept = _last_kept_timestamps(session)

    stored_count = 0
    newest_submission_id: int | None = None
    newest_timestamp: int | None = None

    with LeetCodeClient(creds, site=site) as client:
        console.print("Fetching problem catalog...")
        catalog = _load_problem_catalog(client)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Importing submissions", total=None)
            while True:
                page = client.get_submissions_page(offset=offset, limit=_PAGE_LIMIT)
                with session_scope(factory) as session:
                    for sub in page.submissions:
                        if newest_submission_id is None:
                            newest_submission_id = sub.submission_id
                            newest_timestamp = sub.timestamp
                        if _process_submission(
                            session=session,
                            client=client,
                            repo_path=repo_path,
                            catalog=catalog,
                            sub=sub,
                            last_kept=last_kept,
                            keep_all=keep_all,
                            dedup_window_seconds=dedup_window,
                            console=console,
                        ):
                            stored_count += 1
                    offset += len(page.submissions)
                    state = get_or_create_sync_state(session, site)
                    state.last_offset = offset
                    session.add(state)
                progress.update(
                    task,
                    advance=len(page.submissions),
                    description=f"Importing submissions (offset {offset})",
                )
                if not page.has_next or not page.submissions:
                    break
                _sleep_between_pages()

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site)
        state.last_offset = offset
        # Prefer this run's newest-seen submission, but a resumed run that lands on an
        # already-drained page sees none - fall back to the DB's true newest so sync_state
        # never finalizes with a completed import but no last_submission_id (which would
        # make `sync` unable to find its starting point).
        if newest_submission_id is not None:
            state.last_submission_id = newest_submission_id
            state.last_synced_timestamp = newest_timestamp
        elif state.last_submission_id is None:
            newest_row = session.execute(
                select(Submission.submission_id, Submission.timestamp)
                .order_by(Submission.timestamp.desc())
                .limit(1)
            ).first()
            if newest_row is not None:
                state.last_submission_id, state.last_synced_timestamp = newest_row
        state.last_full_import_completed_at = int(time.time())
        session.add(state)

    console.print(f"[green]Import complete[/green]: {stored_count} submissions stored.")
    _regenerate_readme(factory, repo_path)
    _maybe_push_to_github(
        console, repo_path, f"leetvault: import {stored_count} accepted submissions"
    )


def run_sync(console: Console, site: str, keep_all: bool) -> None:
    creds = load_leetcode_credentials(site)
    if creds is None:
        console.print(f"[red]Not logged in for site '{site}'. Run `leetvault login` first.[/red]")
        raise typer.Exit(code=1)

    store = ConfigStore()
    dedup_window = 0 if keep_all else int(store.get("dedup_window_seconds") or 86400)
    repo_path = store.resolved_repo_path()
    repo_path.mkdir(parents=True, exist_ok=True)

    engine = make_engine(store.resolved_db_path())
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site)
        last_known_id = state.last_submission_id
        last_known_timestamp = state.last_synced_timestamp
        last_kept = _last_kept_timestamps(session)

    if last_known_id is None:
        console.print(
            "[yellow]No prior sync state found. Run `leetvault import` first for full "
            "history.[/yellow]"
        )
        raise typer.Exit(code=1)

    stored_count = 0
    newest_submission_id: int | None = None
    newest_timestamp: int | None = None
    offset = 0
    stop = False

    with LeetCodeClient(creds, site=site) as client:
        catalog = _load_problem_catalog(client)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing new submissions", total=None)
            while not stop:
                page = client.get_submissions_page(offset=offset, limit=_PAGE_LIMIT)
                if not page.submissions:
                    break
                with session_scope(factory) as session:
                    for sub in page.submissions:
                        already_known = sub.submission_id == last_known_id or (
                            last_known_timestamp is not None
                            and sub.timestamp <= last_known_timestamp
                        )
                        if already_known:
                            stop = True
                            break
                        if newest_submission_id is None:
                            newest_submission_id = sub.submission_id
                            newest_timestamp = sub.timestamp
                        if _process_submission(
                            session=session,
                            client=client,
                            repo_path=repo_path,
                            catalog=catalog,
                            sub=sub,
                            last_kept=last_kept,
                            keep_all=keep_all,
                            dedup_window_seconds=dedup_window,
                            console=console,
                        ):
                            stored_count += 1
                progress.update(task, advance=len(page.submissions))
                offset += len(page.submissions)
                if not page.has_next:
                    break
                if not stop:
                    _sleep_between_pages()

    if newest_submission_id is not None:
        with session_scope(factory) as session:
            state = get_or_create_sync_state(session, site)
            state.last_submission_id = newest_submission_id
            state.last_synced_timestamp = newest_timestamp
            session.add(state)

    console.print(f"[green]Sync complete[/green]: {stored_count} new submissions stored.")
    _regenerate_readme(factory, repo_path)
    _maybe_push_to_github(
        console, repo_path, f"leetvault: sync {stored_count} new accepted submissions"
    )
