"""Stats aggregation + Jinja2 rendering for the dashboard README, regenerated after every
import/sync/watch cycle so it never drifts from the DB.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from leetvault.git_writer import file_extension
from leetvault.models import Problem, Submission

_DIFFICULTY_ORDER = ("Easy", "Medium", "Hard")
_BAR_WIDTH = 20
_RECENT_LIMIT = 10


def _percent(count: int, total: int) -> float:
    return (count / total * 100) if total else 0.0


def _bar(percent: float, width: int = _BAR_WIDTH) -> str:
    filled = round(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


def _anchor(heading: str) -> str:
    """GitHub's heading-anchor rules: lowercase, drop punctuation, spaces -> hyphens.

    e.g. "Heap (Priority Queue)" -> "heap-priority-queue", "Depth-First Search" ->
    "depth-first-search". Must match GitHub exactly or the topic links silently 404.
    """
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug)


@dataclass
class DifficultyStat:
    difficulty: str
    count: int
    percent: float
    bar: str


@dataclass
class LanguageStat:
    lang: str
    count: int
    percent: float
    bar: str


@dataclass
class SolutionEntry:
    frontend_id: int
    title: str
    difficulty: str
    lang: str
    date: str
    url: str
    file_path: str
    file_name: str
    question_path: str
    # None when this problem has no analysis yet. AI analysis is optional and fills in
    # gradually - free tiers cap out daily - so the table has to render a partial state.
    analysis_path: str | None = None


@dataclass
class TopicStat:
    name: str
    count: int
    anchor: str
    problems: list[SolutionEntry] = field(default_factory=list)


@dataclass
class ReadmeStats:
    total_solved: int
    by_difficulty: list[DifficultyStat] = field(default_factory=list)
    by_language: list[LanguageStat] = field(default_factory=list)
    by_topic: list[TopicStat] = field(default_factory=list)
    current_streak: int = 0
    longest_streak: int = 0
    recent: list[SolutionEntry] = field(default_factory=list)
    table: list[SolutionEntry] = field(default_factory=list)
    generated_at: str = ""
    # Only add the Analysis column once something is there to link to, so users who never
    # enable the feature do not get a column of dashes.
    has_analysis: bool = False


def _latest_submission(problem: Problem) -> Submission | None:
    if not problem.submissions:
        return None
    return max(problem.submissions, key=lambda s: s.timestamp)


def _to_entry(
    problem: Problem, submission: Submission, repo_path: Path | None = None
) -> SolutionEntry:
    ext = file_extension(submission.lang)
    analysis_rel = f"Problems/{problem.title_slug}/analysis.md"
    has_analysis = repo_path is not None and (repo_path / analysis_rel).exists()
    solved_date = datetime.fromtimestamp(submission.timestamp, tz=UTC).date().isoformat()
    return SolutionEntry(
        frontend_id=problem.frontend_id,
        title=problem.title,
        difficulty=problem.difficulty,
        lang=submission.lang,
        date=solved_date,
        url=problem.url,
        file_path=f"Problems/{problem.title_slug}/latest.{ext}",
        file_name=f"latest.{ext}",
        question_path=f"Problems/{problem.title_slug}/question.md",
        analysis_path=analysis_rel if has_analysis else None,
    )


def _compute_streaks(dates: list[date]) -> tuple[int, int]:
    if not dates:
        return 0, 0
    longest = 1
    current = 1
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap == 1:
            current += 1
            longest = max(longest, current)
        elif gap > 1:
            current = 1
    return current, longest


def aggregate_stats(session: Session, repo_path: Path | None = None) -> ReadmeStats:
    problems = list(session.scalars(select(Problem)))
    total_solved = len(problems)

    difficulty_counts: Counter[str] = Counter(p.difficulty for p in problems)
    by_difficulty = [
        DifficultyStat(
            difficulty=d,
            count=difficulty_counts.get(d, 0),
            percent=_percent(difficulty_counts.get(d, 0), total_solved),
            bar=_bar(_percent(difficulty_counts.get(d, 0), total_solved)),
        )
        for d in _DIFFICULTY_ORDER
    ]

    language_counts: Counter[str] = Counter()
    for problem in problems:
        latest = _latest_submission(problem)
        if latest is not None:
            language_counts[latest.lang] += 1
    by_language = [
        LanguageStat(
            lang=lang,
            count=count,
            percent=_percent(count, total_solved),
            bar=_bar(_percent(count, total_solved)),
        )
        for lang, count in language_counts.most_common()
    ]

    topic_counts: Counter[str] = Counter()
    topic_entries: defaultdict[str, list[SolutionEntry]] = defaultdict(list)
    for problem in problems:
        latest = _latest_submission(problem)
        for topic in problem.topics:
            topic_counts[topic.name] += 1
            if latest is not None:
                topic_entries[topic.name].append(_to_entry(problem, latest, repo_path))
    by_topic = [
        TopicStat(
            name=name,
            count=count,
            anchor=_anchor(name),
            problems=sorted(topic_entries[name], key=lambda row: row.frontend_id),
        )
        for name, count in topic_counts.most_common()
    ]

    solved_dates = sorted(
        {
            datetime.fromtimestamp(s.timestamp, tz=UTC).date()
            for p in problems
            for s in p.submissions
        }
    )
    current_streak, longest_streak = _compute_streaks(solved_dates)

    all_submissions = [
        (problem, submission) for problem in problems for submission in problem.submissions
    ]
    all_submissions.sort(key=lambda ps: ps[1].timestamp, reverse=True)
    recent = [_to_entry(p, s, repo_path) for p, s in all_submissions[:_RECENT_LIMIT]]

    table = sorted(
        (
            _to_entry(problem, latest, repo_path)
            for problem in problems
            if (latest := _latest_submission(problem)) is not None
        ),
        key=lambda row: row.frontend_id,
    )

    return ReadmeStats(
        total_solved=total_solved,
        by_difficulty=by_difficulty,
        by_language=by_language,
        by_topic=by_topic,
        current_streak=current_streak,
        longest_streak=longest_streak,
        recent=recent,
        table=table,
        generated_at=datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
        has_analysis=any(row.analysis_path for row in table),
    )


def render_readme(stats: ReadmeStats) -> str:
    env = Environment(
        loader=PackageLoader("leetvault", "templates"),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("README.md.j2")
    return template.render(stats=stats)


def generate_readme(session: Session, repo_path: Path) -> Path:
    stats = aggregate_stats(session, repo_path)
    content = render_readme(stats)
    readme_path = repo_path / "README.md"
    readme_path.write_text(content, encoding="utf-8")
    return readme_path
