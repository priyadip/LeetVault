"""Disk layout writer for the mirrored `Problems/<slug>/...` tree.

Git commit/push (transient-PAT injection, batching) lands in Phase 4 on top of this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from leetvault.client import ProblemMeta

_LANG_EXTENSIONS: dict[str, str] = {
    "python3": "py",
    "python": "py",
    "java": "java",
    "cpp": "cpp",
    "c": "c",
    "csharp": "cs",
    "javascript": "js",
    "typescript": "ts",
    "golang": "go",
    "go": "go",
    "ruby": "rb",
    "swift": "swift",
    "kotlin": "kt",
    "scala": "scala",
    "rust": "rs",
    "php": "php",
    "dart": "dart",
    "racket": "rkt",
    "erlang": "erl",
    "elixir": "ex",
    "mysql": "sql",
    "mssql": "sql",
    "oraclesql": "sql",
    "postgresql": "sql",
    "bash": "sh",
}


def file_extension(lang: str) -> str:
    return _LANG_EXTENSIONS.get(lang, "txt")


def problem_dir(repo_path: Path, title_slug: str) -> Path:
    return repo_path / "Problems" / title_slug


@dataclass
class WrittenHistoryEntry:
    path: Path
    is_new: bool


def write_history(
    repo_path: Path, title_slug: str, submission_id: int, lang: str, code: str
) -> WrittenHistoryEntry:
    history_dir = problem_dir(repo_path, title_slug) / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"submission_{submission_id}.{file_extension(lang)}"
    is_new = not path.exists()
    if is_new:
        path.write_text(code, encoding="utf-8")
    return WrittenHistoryEntry(path=path, is_new=is_new)


def write_latest_and_metadata(
    repo_path: Path,
    problem: ProblemMeta,
    submission_id: int,
    lang: str,
    code: str,
    timestamp: int,
    runtime: str,
    memory: str,
    runtime_percentile: float | None,
    memory_percentile: float | None,
) -> tuple[Path, Path]:
    p_dir = problem_dir(repo_path, problem.title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)

    latest_path = p_dir / f"latest.{file_extension(lang)}"
    latest_path.write_text(code, encoding="utf-8")

    metadata = {
        "question_id": problem.question_id,
        "frontend_id": problem.frontend_id,
        "title": problem.title,
        "title_slug": problem.title_slug,
        "difficulty": problem.difficulty,
        "paid_only": problem.paid_only,
        "url": problem.url,
        "latest_submission_id": submission_id,
        "lang": lang,
        "timestamp": timestamp,
        "runtime": runtime,
        "memory": memory,
        "runtime_percentile": runtime_percentile,
        "memory_percentile": memory_percentile,
    }
    metadata_path = p_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return latest_path, metadata_path


def ensure_notes(repo_path: Path, problem: ProblemMeta) -> Path:
    """Create notes.md once; never overwrite - it's the user's own scratch space."""
    p_dir = problem_dir(repo_path, problem.title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)
    notes_path = p_dir / "notes.md"
    if not notes_path.exists():
        notes_path.write_text(f"# {problem.title}\n\n{problem.url}\n", encoding="utf-8")
    return notes_path
