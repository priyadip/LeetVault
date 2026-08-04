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
    problem_dir,
    question_md_path,
    runner_info_from_meta,
    sync_to_github,
    update_metadata_counts,
    update_metadata_runner,
    write_devcontainer,
    write_history,
    write_latest_and_metadata,
    write_question_md,
    write_run_shim,
    write_shared_runner,
    write_solutions_gitignore,
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
    session: Session,
    client: LeetCodeClient,
    meta: ProblemMeta,
    console: Console,
    repo_path: Path,
    write_question: bool,
) -> Problem:
    problem = session.get(Problem, meta.question_id)
    is_new = problem is None
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

    # Neither topics nor the problem statement are in REST's submissions dump or
    # /api/problems/all/, so they need one `question(titleSlug)` call. Only make it when
    # there's something to gain: a brand-new problem (needs topics) or a missing
    # question.md (backfills problems synced before this feature existed).
    needs_question_md = write_question and not question_md_path(repo_path, meta.title_slug).exists()
    if not (is_new or needs_question_md):
        return problem

    try:
        detail = client.question_detail(meta.title_slug)
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        console.print(f"[yellow]Could not fetch details for {meta.title_slug}: {exc}[/yellow]")
        return problem

    if is_new:
        for topic_name in detail.topics:
            topic = session.scalar(select(Topic).where(Topic.name == topic_name))
            if topic is None:
                topic = Topic(name=topic_name)
                session.add(topic)
                session.flush()
            problem.topics.append(topic)

    if needs_question_md:
        topic_names = detail.topics or [t.name for t in problem.topics]
        write_question_md(repo_path, meta, detail, topic_names)
        update_metadata_runner(repo_path, meta.title_slug, runner_info_from_meta(detail))
        write_run_shim(repo_path, meta.title_slug)

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
    write_question: bool = True,
) -> bool:
    """Store + write one accepted submission to disk. Returns True if it was kept."""
    if not sub.is_accepted:
        return False
    if session.get(Submission, sub.submission_id) is not None:
        return False

    known_latest_timestamp = last_kept.get(sub.question_id)
    is_newest_for_problem = known_latest_timestamp is None or sub.timestamp > known_latest_timestamp
    # Only dedupe a submission that is *older* than the current latest known one for this
    # problem, and only within the window - a solve from outside the window is a distinct,
    # later attempt and must never be dropped just because a stale kept timestamp precedes
    # it (comparing by raw subtraction here previously went negative for exactly that case,
    # silently discarding every subsequent solve forever).
    if (
        not keep_all
        and known_latest_timestamp is not None
        and not is_newest_for_problem
        and abs(known_latest_timestamp - sub.timestamp) < dedup_window_seconds
    ):
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
    total_correct: int | None = None
    total_testcases: int | None = None
    try:
        detail = client.submission_details(sub.submission_id)
        runtime_percentile = detail.runtime_percentile
        memory_percentile = detail.memory_percentile
        total_correct = detail.total_correct
        total_testcases = detail.total_testcases
        if not code:
            code = detail.code
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        console.print(f"[yellow]submissionDetails failed for {sub.submission_id}: {exc}[/yellow]")

    if not code:
        console.print(
            f"[yellow]No code available for submission {sub.submission_id}; skipping.[/yellow]"
        )
        return False

    problem = _upsert_problem(
        session, client, meta, console, repo_path=repo_path, write_question=write_question
    )
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
        total_correct=total_correct,
        total_testcases=total_testcases,
    )
    submission.code = SubmissionCode(code=code)
    problem.submissions.append(submission)
    session.add(submission)

    write_history(repo_path, meta.title_slug, sub.submission_id, sub.lang, code)
    if is_newest_for_problem:
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
            total_correct=total_correct,
            total_testcases=total_testcases,
        )
        ensure_notes(repo_path, meta)
        last_kept[sub.question_id] = sub.timestamp

    return True


def _backfill_testcase_counts(
    console: Console,
    factory: sessionmaker[Session],
    client: LeetCodeClient,
    repo_path: Path,
) -> int:
    """Fetch judge test-case counts for submissions stored before they were recorded.

    Only touches rows where the count is still unknown, so this is a zero-call no-op once
    every stored submission has one.
    """
    with session_scope(factory) as session:
        pending = [
            (s.submission_id, s.question_id)
            for s in session.scalars(select(Submission).where(Submission.total_testcases.is_(None)))
        ]

    if not pending:
        return 0

    updated = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching judge test-case counts", total=len(pending))
        for submission_id, _ in pending:
            try:
                detail = client.submission_details(submission_id)
            except Exception:  # noqa: BLE001 - best-effort enrichment
                progress.advance(task)
                continue
            if detail.total_testcases is not None:
                with session_scope(factory) as session:
                    row = session.get(Submission, submission_id)
                    if row is not None:
                        row.total_correct = detail.total_correct
                        row.total_testcases = detail.total_testcases
                        session.add(row)
                updated += 1
            progress.advance(task)

    # metadata.json is rewritten from the DB below, so refresh the "latest" rows on disk.
    if updated:
        with session_scope(factory) as session:
            for problem in session.scalars(select(Problem)):
                if not problem.submissions:
                    continue
                latest = max(problem.submissions, key=lambda s: s.timestamp)
                if latest.total_testcases is None:
                    continue
                update_metadata_counts(
                    repo_path, problem.title_slug, latest.total_correct, latest.total_testcases
                )
        console.print(
            f"[green]Recorded judge test-case counts[/green] for {updated} submission(s)."
        )
    return updated


def _backfill_question_md(
    console: Console,
    factory: sessionmaker[Session],
    client: LeetCodeClient,
    repo_path: Path,
) -> int:
    """Write question.md for any already-known problem that's missing one.

    Needed because `_upsert_problem` only runs while processing a *submission*, so a run
    with no new submissions would never backfill problems synced before this feature
    existed. Only fetches for problems whose file is actually missing, so this is a no-op
    (zero API calls) once every problem has one.
    """
    with session_scope(factory) as session:
        pending = [
            (p.question_id, p.frontend_id, p.title, p.title_slug, p.difficulty, p.paid_only, p.url)
            for p in session.scalars(select(Problem))
            if not question_md_path(repo_path, p.title_slug).exists()
            or not (problem_dir(repo_path, p.title_slug) / "run.py").exists()
        ]

    # The shared runner and devcontainer are repo-level and cheap; keep them current so an
    # upgrade picks up runner fixes without needing to delete anything.
    write_shared_runner(repo_path)
    write_devcontainer(repo_path)
    write_solutions_gitignore(repo_path)

    if not pending:
        return 0

    written = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching problem statements", total=len(pending))
        for question_id, frontend_id, title, slug, difficulty, paid_only, url in pending:
            meta = ProblemMeta(
                question_id=question_id,
                frontend_id=frontend_id,
                title=title,
                title_slug=slug,
                difficulty=difficulty,
                paid_only=paid_only,
                url=url,
            )
            try:
                detail = client.question_detail(slug)
            except Exception as exc:  # noqa: BLE001 - best-effort, never fatal
                console.print(f"[yellow]Could not fetch statement for {slug}: {exc}[/yellow]")
                progress.advance(task)
                continue
            write_question_md(repo_path, meta, detail, detail.topics)
            update_metadata_runner(repo_path, slug, runner_info_from_meta(detail))
            write_run_shim(repo_path, slug)
            written += 1
            progress.advance(task)

    if written:
        console.print(
            f"[green]Wrote {written} problem statement(s)[/green] (question.md + runnable run.py)."
        )
    return written


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


def _resolve_dedup_window(store: ConfigStore, keep_all: bool) -> int:
    if keep_all:
        return 0
    raw = store.get("dedup_window_seconds")
    # `raw or 86400` would silently ignore an explicit `0` (falsy) - that's exactly the
    # value someone would set via `leetvault config dedup_window_seconds 0` to make
    # --keep-all the persistent default instead of retyping the flag every run.
    return int(raw) if raw is not None else 86400


def run_import(console: Console, site: str, keep_all: bool) -> None:
    creds = load_leetcode_credentials(site)
    if creds is None:
        console.print(f"[red]Not logged in for site '{site}'. Run `leetvault login` first.[/red]")
        raise typer.Exit(code=1)

    store = ConfigStore()
    dedup_window = _resolve_dedup_window(store, keep_all)
    write_question = bool(store.get("write_question_md"))
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
                            write_question=write_question,
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

        if write_question:
            _backfill_question_md(console, factory, client, repo_path)
        _backfill_testcase_counts(console, factory, client, repo_path)

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
    dedup_window = _resolve_dedup_window(store, keep_all)
    write_question = bool(store.get("write_question_md"))
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
                            write_question=write_question,
                            console=console,
                        ):
                            stored_count += 1
                progress.update(task, advance=len(page.submissions))
                offset += len(page.submissions)
                if not page.has_next:
                    break
                if not stop:
                    _sleep_between_pages()

        if write_question:
            _backfill_question_md(console, factory, client, repo_path)
        _backfill_testcase_counts(console, factory, client, repo_path)

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
