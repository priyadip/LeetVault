"""The `leetvault site` command: a browsable GitHub Pages site for the solutions repo.

The repository already holds everything a reader wants - the statement, the code, every
earlier submission, the analysis, your notes - but only as files you have to click through
one at a time. This publishes a page over the same files: an index you can filter, and a
problem view with question, code and analysis side by side in panes you can drag.

Nothing is duplicated. The page fetches `Problems/<slug>/question.md` and friends at the
paths sync already writes, so editing a file on GitHub changes what the page shows without
regenerating anything. Only the catalogue - which problems exist, which have an analysis,
which submissions are in history - is generated, into `assets/index.json`.

That constraint is why Pages is served from the repository root rather than `/docs`: a site
rooted at `/docs` can only serve files inside it, which would mean copying all 145 problems
into a second tree and keeping the copies in step forever.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import typer
from rich.console import Console

from leetvault.bot import Step
from leetvault.config import ConfigStore
from leetvault.git_writer import file_extension


class HistoryEntry(TypedDict):
    file: str
    id: int


class ProblemEntry(TypedDict):
    id: int
    slug: str
    title: str
    difficulty: str
    lang: str
    ext: str
    url: str
    date: str
    topics: list[str]
    has_analysis: bool
    has_notes: bool
    history: list[HistoryEntry]


class CourseNode(TypedDict):
    title: str
    path: str
    children: list[CourseNode]


class SiteIndex(TypedDict):
    repo: str
    branch: str
    generated_at: str
    problems: list[ProblemEntry]
    course: list[CourseNode]


# Written at the repository root so the whole tree is published, not just a subdirectory.
SITE_FILES = ("index.html", "assets/style.css", "assets/app.js")
INDEX_JSON = "assets/index.json"
# Pages runs Jekyll by default, which silently drops paths beginning with an underscore and
# reinterprets others. None of this is a Jekyll site.
NOJEKYLL = ".nojekyll"
COURSE_DIR = "Course"


def _templates() -> Path:
    return Path(__file__).parent / "templates" / "site"


def _history_entries(problem_dir: Path) -> list[HistoryEntry]:
    """Every earlier submission stored for a problem, newest first.

    The submission id is monotonic, so sorting by it puts the most recent attempt at the
    top - which is the one a reader almost always wants.
    """
    history = problem_dir / "history"
    if not history.is_dir():
        return []
    entries: list[HistoryEntry] = []
    for path in history.iterdir():
        if not path.is_file():
            continue
        stem = path.stem.removeprefix("submission_")
        entries.append({"file": path.name, "id": int(stem) if stem.isdigit() else 0})
    entries.sort(key=lambda e: e["id"], reverse=True)
    return entries


def _topics(problem_dir: Path) -> list[str]:
    """Topics as written into question.md.

    metadata.json does not carry them - they live in the database - and the site has to be
    buildable from a checkout alone, including on a CI runner with no database at all.
    """
    path = problem_dir / "question.md"
    if not path.is_file():
        return []
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        if line.startswith("**Topics:**"):
            raw = line.removeprefix("**Topics:**").strip()
            return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _course_tree(repo_path: Path) -> list[CourseNode]:
    """The `Course/` folder as a nested outline.

    Folders become sections and Markdown files become pages, so the hierarchy is just the
    directory layout - nothing to keep in sync, and it reorganises with a normal file move.
    """

    def walk(directory: Path) -> list[CourseNode]:
        nodes: list[CourseNode] = []
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                nodes.append(
                    {
                        "title": child.name,
                        "path": "",
                        "children": walk(child),
                    }
                )
            elif child.suffix.lower() in (".md", ".markdown"):
                nodes.append(
                    {
                        "title": child.stem,
                        "path": child.relative_to(repo_path).as_posix(),
                        "children": [],
                    }
                )
        return nodes

    root = repo_path / COURSE_DIR
    return walk(root) if root.is_dir() else []


def build_index(repo_path: Path, repo_slug: str, branch: str = "main") -> SiteIndex:
    """The catalogue the page reads. Content itself is never copied in here."""
    problems: list[ProblemEntry] = []
    root = repo_path / "Problems"
    if root.is_dir():
        for directory in sorted(root.iterdir()):
            meta_file = directory / "metadata.json"
            if not directory.is_dir() or not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            lang = str(meta.get("lang") or "")
            timestamp = meta.get("timestamp")
            problems.append(
                {
                    "id": int(meta.get("frontend_id") or 0),
                    "slug": directory.name,
                    "title": str(meta.get("title") or directory.name),
                    "difficulty": str(meta.get("difficulty") or "Unknown"),
                    "lang": lang,
                    "ext": file_extension(lang),
                    "url": str(meta.get("url") or ""),
                    "date": (
                        datetime.fromtimestamp(int(timestamp), tz=UTC).date().isoformat()
                        if timestamp
                        else ""
                    ),
                    "topics": _topics(directory),
                    "has_analysis": (directory / "analysis.md").is_file(),
                    "has_notes": (directory / "notes.md").is_file(),
                    "history": _history_entries(directory),
                }
            )
    problems.sort(key=lambda p: p["id"])
    return {
        "repo": repo_slug,
        "branch": branch,
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "problems": problems,
        "course": _course_tree(repo_path),
    }


def write_site(repo_path: Path, repo_slug: str, branch: str = "main") -> list[Path]:
    """Copy the page in and regenerate its index. Returns the files written."""
    written: list[Path] = []
    templates = _templates()
    for name in SITE_FILES:
        target = repo_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(templates / name, target)
        written.append(target)

    nojekyll = repo_path / NOJEKYLL
    nojekyll.touch()
    written.append(nojekyll)

    index = repo_path / INDEX_JSON
    index.write_text(
        json.dumps(build_index(repo_path, repo_slug, branch), indent=1), encoding="utf-8"
    )
    written.append(index)
    return written


def refresh_index(repo_path: Path, repo_slug: str, branch: str = "main") -> bool:
    """Regenerate only the catalogue, and only when the page is already installed.

    Called from sync so a newly solved problem appears without re-running `site`. It does
    not install anything: a repository with no site should not grow one because a sync ran.
    """
    if not (repo_path / "index.html").is_file():
        return False
    (repo_path / INDEX_JSON).write_text(
        json.dumps(build_index(repo_path, repo_slug, branch), indent=1), encoding="utf-8"
    )
    return True


def _enable_pages(slug: str, branch: str) -> Step:
    """Turn on Pages, serving the repository root."""
    from leetvault.bot import _run_gh

    ok, message = _run_gh(["api", f"repos/{slug}/pages"])
    if ok:
        ok, message = _run_gh(
            [
                "api",
                "-X",
                "PUT",
                f"repos/{slug}/pages",
                "-f",
                f"source[branch]={branch}",
                "-f",
                "source[path]=/",
            ]
        )
        return Step("GitHub Pages (already on, source updated)", ok, message)
    ok, message = _run_gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{slug}/pages",
            "-f",
            f"source[branch]={branch}",
            "-f",
            "source[path]=/",
        ]
    )
    return Step("GitHub Pages enabled", ok, message)


def run_site(console: Console, *, repo: Path | None, publish: bool, branch: str = "main") -> None:
    from leetvault.bot import _commit_and_push, _gh, repo_slug

    store = ConfigStore()
    repo_path = repo or store.resolved_repo_path()
    slug = repo_slug(str(store.get("repo_url") or "")) or ""

    written = write_site(repo_path, slug, branch)
    for path in written:
        console.print(f"[green]Wrote[/green] {path}")

    index = json.loads((repo_path / INDEX_JSON).read_text(encoding="utf-8"))
    console.print(
        f"\n[bold]{len(index['problems'])} problem(s)[/bold] indexed, "
        f"{sum(1 for p in index['problems'] if p['has_analysis'])} with analysis, "
        f"{len(index['course'])} course section(s)."
    )

    if not publish:
        console.print("\nCommit and push these, then enable Pages yourself, or re-run with")
        console.print("[bold]leetvault site --publish[/bold] to do both.")
        return

    if not slug:
        console.print(
            "\n[red]No GitHub repo configured.[/red] Set one with "
            "`leetvault config repo_url <url>`."
        )
        raise typer.Exit(code=1)
    if _gh() is None:
        console.print(
            "\n[yellow]The GitHub CLI (gh) is not installed[/yellow], so Pages cannot be "
            "enabled automatically. Install it from https://cli.github.com, or turn Pages on "
            "under Settings -> Pages with the source set to the repository root."
        )
        return

    steps = [_commit_and_push(repo_path, branch), _enable_pages(slug, branch)]
    console.print()
    for step in steps:
        mark = "[green]OK[/green]  " if step.ok else "[red]FAIL[/red]"
        console.print(f"  {mark} {step.name}" + ("" if step.ok else f" - {step.detail}"))

    if all(s.ok for s in steps):
        owner, _, name = slug.partition("/")
        console.print(
            f"\n[green]Published.[/green] Your site will be live in a minute or two at\n"
            f"  [bold]https://{owner}.github.io/{name}/[/bold]"
        )
        console.print(
            "[dim]The first build takes longest. `leetvault sync` refreshes the index "
            "afterwards, so new problems appear on their own.[/dim]"
        )
