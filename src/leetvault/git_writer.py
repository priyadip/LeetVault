"""Disk layout writer for the mirrored `Problems/<slug>/...` tree, plus the git commit/push
layer on top of it: a transient-PAT push that never persists the token to disk, and batches
every file written by one sync/import/watch run into a single commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from git import GitCommandError, Repo
from rich.console import Console

from leetvault.client import ProblemMeta, QuestionDetail

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
    runner: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    p_dir = problem_dir(repo_path, problem.title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)

    latest_path = p_dir / f"latest.{file_extension(lang)}"
    latest_path.write_text(code, encoding="utf-8")

    metadata_path = p_dir / "metadata.json"
    # `runner` is only known when the problem statement is fetched, which happens once per
    # problem - preserve whatever a previous run stored rather than dropping it.
    if runner is None and metadata_path.exists():
        try:
            runner = json.loads(metadata_path.read_text(encoding="utf-8")).get("runner")
        except (ValueError, OSError):
            runner = None

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
        "runner": runner,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return latest_path, metadata_path


def runner_info_from_meta(detail: QuestionDetail) -> dict[str, object]:
    """Distil `metaData` into what the runner actually needs.

    `manual` marks design/interactive problems (LRU Cache and friends) that have no single
    entry point; those get a null method so the runner can say so instead of failing.
    """
    meta = detail.meta_data or {}
    if meta.get("manual"):
        return {"method": None, "param_types": [], "example_testcases": ""}
    return {
        "method": meta.get("name"),
        "param_types": [p.get("type") for p in meta.get("params") or []],
        "example_testcases": detail.example_testcases,
    }


def update_metadata_runner(repo_path: Path, title_slug: str, runner: dict[str, object]) -> bool:
    """Merge runner info into an existing metadata.json. Returns False if there isn't one."""
    path = problem_dir(repo_path, title_slug) / "metadata.json"
    if not path.exists():
        return False
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    metadata["runner"] = runner
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return True


def question_md_path(repo_path: Path, title_slug: str) -> Path:
    return problem_dir(repo_path, title_slug) / "question.md"


def write_question_md(
    repo_path: Path, problem: ProblemMeta, detail: QuestionDetail, topics: list[str]
) -> Path:
    """Render the problem statement as question.md alongside the solution."""
    from leetvault.htmlmd import html_to_markdown

    p_dir = problem_dir(repo_path, problem.title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# {problem.frontend_id}. {problem.title}",
        "",
        f"**Difficulty:** {problem.difficulty}",
    ]
    if topics:
        lines.append(f"**Topics:** {', '.join(topics)}")
    lines += ["", f"[View on LeetCode]({problem.url})", ""]

    if detail.content:
        lines += ["## Description", "", html_to_markdown(detail.content), ""]
    elif detail.is_paid_only:
        lines += [
            "## Description",
            "",
            "_This is a LeetCode Premium problem; its statement is not available through the API._",
            "",
        ]

    if detail.hints:
        lines += ["## Hints", ""]
        for i, hint in enumerate(detail.hints, start=1):
            # Collapsed by default so opening the file doesn't spoil the problem.
            lines += [
                "<details>",
                f"<summary>Hint {i}</summary>",
                "",
                html_to_markdown(hint),
                "",
                "</details>",
                "",
            ]

    if detail.similar_questions:
        lines += ["## Similar Questions", ""]
        base = problem.url.split("/problems/")[0]
        for sq in detail.similar_questions:
            lines.append(f"- [{sq.title}]({base}/problems/{sq.title_slug}/) - {sq.difficulty}")
        lines.append("")

    lines += [
        "---",
        "",
        "_Problem statement retrieved from LeetCode. All problem content is the property "
        "of LeetCode._",
        "",
    ]

    path = question_md_path(repo_path, problem.title_slug)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


_RUNNER_FILENAME = "leetvault_runner.py"

_RUN_SHIM = '''"""Run this problem's stored solution against LeetCode's example inputs.

Auto-generated by leetvault - do not edit; it is rewritten on sync.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leetvault_runner import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run(Path(__file__).resolve().parent))
'''

_DEVCONTAINER = """{
  "name": "LeetCode Solutions",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python"],
      "settings": {
        "python.defaultInterpreterPath": "/usr/local/bin/python"
      }
    }
  }
}
"""


def write_shared_runner(repo_path: Path) -> Path:
    """Write the single shared runner at the repo root."""
    from jinja2 import Environment, PackageLoader, select_autoescape

    env = Environment(
        loader=PackageLoader("leetvault", "templates"),
        autoescape=select_autoescape(enabled_extensions=()),
        keep_trailing_newline=True,
    )
    path = repo_path / _RUNNER_FILENAME
    path.write_text(env.get_template("runner.py.j2").render(), encoding="utf-8")
    return path


def write_run_shim(repo_path: Path, title_slug: str) -> Path:
    """Write the tiny per-problem run.py that delegates to the shared runner."""
    p_dir = problem_dir(repo_path, title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)
    path = p_dir / "run.py"
    path.write_text(_RUN_SHIM, encoding="utf-8")
    return path


_SOLUTIONS_GITIGNORE = """__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.DS_Store
"""


def write_solutions_gitignore(repo_path: Path) -> Path:
    """Keep run.py's bytecode out of the solutions repo.

    Running a solution creates __pycache__ next to it, which `git add -A` would otherwise
    commit as noise on the next sync.
    """
    path = repo_path / ".gitignore"
    if not path.exists():
        path.write_text(_SOLUTIONS_GITIGNORE, encoding="utf-8")
    return path


def write_devcontainer(repo_path: Path) -> Path:
    """Write a devcontainer so GitHub Codespaces boots Python-ready."""
    dc_dir = repo_path / ".devcontainer"
    dc_dir.mkdir(parents=True, exist_ok=True)
    path = dc_dir / "devcontainer.json"
    path.write_text(_DEVCONTAINER, encoding="utf-8")
    return path


def ensure_notes(repo_path: Path, problem: ProblemMeta) -> Path:
    """Create notes.md once; never overwrite - it's the user's own scratch space."""
    p_dir = problem_dir(repo_path, problem.title_slug)
    p_dir.mkdir(parents=True, exist_ok=True)
    notes_path = p_dir / "notes.md"
    if not notes_path.exists():
        notes_path.write_text(f"# {problem.title}\n\n{problem.url}\n", encoding="utf-8")
    return notes_path


class GitWriterError(RuntimeError):
    """Raised on a git or GitHub API failure. Messages are always PAT-scrubbed."""


def ensure_repo(repo_path: Path) -> Repo:
    repo_path.mkdir(parents=True, exist_ok=True)
    if (repo_path / ".git").exists():
        return Repo(repo_path)
    return Repo.init(repo_path, initial_branch="main")


def stage_and_commit(repo: Repo, message: str) -> bool:
    """Stage every change and commit. Returns False (no-op) if nothing changed."""
    repo.git.add(A=True)
    if not repo.git.status(porcelain=True).strip():
        return False
    repo.index.commit(message)
    return True


def _authenticated_url(repo_url: str, pat: str) -> str:
    parts = urlsplit(repo_url)
    netloc = f"x-access-token:{pat}@{parts.hostname}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _scrub(pat: str, text: str) -> str:
    return text.replace(pat, "***")


def push(repo: Repo, repo_url: str, pat: str, branch: str = "main") -> None:
    """Push HEAD to `branch`, injecting the PAT into the push URL only for this call -
    never as a named remote, so it never lands in .git/config."""
    url = _authenticated_url(repo_url, pat)
    try:
        repo.git.push(url, f"HEAD:refs/heads/{branch}")
    except GitCommandError as exc:
        raise GitWriterError(_scrub(pat, str(exc))) from None


def validate_github_pat(pat: str) -> str | None:
    """Check the PAT is live by hitting GitHub's /user endpoint. Returns the login, or
    None if the token is invalid/unauthorized."""
    try:
        response = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            timeout=10.0,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    login = response.json().get("login")
    return str(login) if login else None


def sync_to_github(
    console: Console, repo_path: Path, repo_url: str, pat: str, message: str
) -> None:
    """Commit everything written by this run (no-op if nothing changed), then always
    attempt a push - even with nothing new to commit, an earlier run's commit may still be
    sitting unpushed (e.g. a prior push attempt failed), and this must not strand it."""
    repo = ensure_repo(repo_path)
    committed = stage_and_commit(repo, message)
    if not committed:
        console.print("[green]Nothing new to commit.[/green]")

    if not repo.head.is_valid():
        return  # no commits exist yet at all - nothing to push

    try:
        push(repo, repo_url, pat)
    except GitWriterError as exc:
        console.print(f"[red]Push failed:[/red] {exc}")
        raise

    if committed:
        console.print(f"[green]Committed and pushed[/green]: {message}")
    else:
        console.print("[green]Pushed[/green] previously committed changes.")
    console.print(f"[green]Committed and pushed[/green]: {message}")
