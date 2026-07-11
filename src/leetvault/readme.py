"""Stats aggregation + Jinja2 rendering for the dashboard README, regenerated after every
import/sync/watch cycle so it never drifts from the DB.
"""

from __future__ import annotations

from collections import Counter
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
class TopicStat:
    name: str
    count: int


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


def _latest_submission(problem: Problem) -> Submission | None:
    if not problem.submissions:
        return None
    return max(problem.submissions, key=lambda s: s.timestamp)


def _to_entry(problem: Problem, submission: Submission) -> SolutionEntry:
    ext = file_extension(submission.lang)
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


def aggregate_stats(session: Session) -> ReadmeStats:
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
    for problem in problems:
        for topic in problem.topics:
            topic_counts[topic.name] += 1
    by_topic = [TopicStat(name=name, count=count) for name, count in topic_counts.most_common()]

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
    recent = [_to_entry(p, s) for p, s in all_submissions[:_RECENT_LIMIT]]

    table = sorted(
        (
            _to_entry(problem, latest)
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
    stats = aggregate_stats(session)
    content = render_readme(stats)
    readme_path = repo_path / "README.md"
    readme_path.write_text(content, encoding="utf-8")
    return readme_path
