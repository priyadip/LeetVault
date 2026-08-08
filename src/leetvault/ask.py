"""The `leetvault ask` command: a question about one problem, answered and logged.

Reads its context entirely from the repository - `question.md`, `latest.*`, `analysis.md` -
rather than from the SQLite database. That is a deliberate constraint, not a shortcut: it
means the command runs anywhere a checkout exists, including a GitHub Actions runner that has
no database, no keyring and no LeetCode session. That is what makes `leetvault bot` possible,
where the repository itself becomes the interface and questions arrive as GitHub issues.

Answers append to `qa.md` rather than replacing anything. The value of a Q&A log is being
able to re-read what you asked months ago next to what you were told, so it accumulates the
way a conversation does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console

from leetvault.client import ProblemMeta
from leetvault.config import ConfigStore
from leetvault.git_writer import (
    analysis_md_path,
    append_qa,
    problem_dir,
    qa_md_path,
    question_md_path,
)

# How much of an earlier conversation to carry into the next question. Enough for follow-ups
# like "why?" to make sense, bounded so a long thread cannot crowd out the code itself.
_HISTORY_CHARS = 4000


@dataclass
class ProblemContext:
    meta: ProblemMeta
    statement: str
    lang: str
    code: str
    analysis: str
    history: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def find_problem_dir(repo_path: Path, target: str) -> Path | None:
    """Locate a problem by slug, number, or part of its title.

    Deliberately tolerant: this is reached from a GitHub issue title as often as from a
    shell, and "3348" or "smallest divisible" should both work.
    """
    root = repo_path / "Problems"
    if not root.is_dir():
        return None
    needle = target.strip().lower().replace(" ", "-")
    candidates = sorted(p for p in root.iterdir() if p.is_dir())

    for path in candidates:
        if path.name.lower() == needle:
            return path

    bare = target.strip()
    if bare.isdigit():
        for path in candidates:
            meta = _read(path / "metadata.json")
            if meta:
                try:
                    if str(json.loads(meta).get("frontend_id")) == bare:
                        return path
                except ValueError:
                    continue

    partial = [p for p in candidates if needle in p.name.lower()]
    return partial[0] if len(partial) == 1 else None


def load_context(repo_path: Path, problem_path: Path) -> ProblemContext | None:
    """Everything known about a problem, read off disk."""
    try:
        metadata = json.loads(_read(problem_path / "metadata.json") or "{}")
    except ValueError:
        metadata = {}
    slug = problem_path.name
    solutions = sorted(problem_path.glob("latest.*"))
    if not solutions:
        return None

    history = _read(qa_md_path(repo_path, slug))
    meta = ProblemMeta(
        question_id=int(metadata.get("question_id") or 0),
        frontend_id=int(metadata.get("frontend_id") or 0),
        title=str(metadata.get("title") or slug.replace("-", " ").title()),
        title_slug=slug,
        difficulty=str(metadata.get("difficulty") or "Unknown"),
        paid_only=bool(metadata.get("paid_only")),
        url=str(metadata.get("url") or f"https://leetcode.com/problems/{slug}/"),
    )
    return ProblemContext(
        meta=meta,
        statement=_read(question_md_path(repo_path, slug)),
        lang=str(metadata.get("lang") or "python3"),
        code=_read(solutions[0]),
        analysis=_read(analysis_md_path(repo_path, slug)),
        history=history[-_HISTORY_CHARS:],
    )


def answer_question(
    context: ProblemContext, question: str, provider_name: str, model: str | None
) -> tuple[str | None, str | None]:
    """Ask the configured backend one question. Returns (answer, error)."""
    from leetvault.ai import get_provider
    from leetvault.ai.prompt import QA_SYSTEM_PROMPT, build_question_prompt

    provider = get_provider(provider_name, model)
    if provider is None:
        return None, f"unknown AI provider {provider_name!r}"

    prompt = build_question_prompt(
        title=context.meta.title,
        difficulty=context.meta.difficulty,
        statement=context.statement,
        lang=context.lang,
        code=context.code,
        question=question,
        analysis=context.analysis,
        history=context.history,
    )
    answer = provider.generate(prompt, QA_SYSTEM_PROMPT)
    if not answer:
        return None, provider.last_error or "the model returned nothing"
    return answer, None


def run_ask(
    console: Console,
    *,
    problem: str,
    question: str,
    provider_name: str | None,
    model: str | None,
    repo: Path | None,
    save: bool,
    push: bool,
) -> None:
    store = ConfigStore()
    repo_path = repo or store.resolved_repo_path()

    problem_path = find_problem_dir(repo_path, problem)
    if problem_path is None:
        console.print(
            f"[red]No problem matches {problem!r}[/red] under {problem_dir(repo_path, '').parent}."
        )
        raise typer.Exit(code=1)

    context = load_context(repo_path, problem_path)
    if context is None:
        console.print(f"[red]{problem_path.name} has no stored solution to reason about.[/red]")
        raise typer.Exit(code=1)

    chosen = provider_name or store.get("ai_provider")
    if not chosen:
        console.print("[red]No AI provider configured.[/red] Run `leetvault ai` first.")
        raise typer.Exit(code=1)

    # Name the model, not just the provider. A model belonging to a different backend is an
    # easy mistake to make - the two are configured separately - and it comes back as a bare
    # 401, which reads like a bad key rather than a mismatch.
    requested_model = model or store.get("ai_model")
    from leetvault.ai import get_provider

    resolved = get_provider(str(chosen), str(requested_model) if requested_model else None)
    using = f"{chosen} ({resolved.model})" if resolved and resolved.model else str(chosen)
    console.print(f"[dim]{context.meta.frontend_id}. {context.meta.title} - asking {using}[/dim]")

    answer, error = answer_question(
        context, question, str(chosen), str(requested_model) if requested_model else None
    )
    if answer is None:
        console.print(f"[red]No answer from {using}:[/red] {error}")
        if error and ("401" in error or "404" in error):
            console.print(
                "[dim]A 401 or 404 here usually means the model is not one this provider "
                "serves - check that the model and provider belong together.[/dim]"
            )
        raise typer.Exit(code=1)

    console.print()
    console.print(answer)

    if not save:
        return

    from leetvault.ai import get_provider

    provider = get_provider(str(chosen), model or store.get("ai_model"))
    path = append_qa(
        repo_path,
        context.meta,
        question,
        answer,
        str(chosen),
        provider.model if provider else "",
        datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )
    console.print(f"\n[green]Saved to[/green] {path}")

    if push:
        from leetvault.sync import _maybe_push_to_github

        _maybe_push_to_github(console, repo_path, f"leetvault: Q&A on {context.meta.title}")
