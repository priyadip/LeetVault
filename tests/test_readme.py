from __future__ import annotations

from pathlib import Path

import pytest

from leetvault.db import make_engine, make_session_factory, session_scope
from leetvault.models import Problem, Submission, SubmissionCode, Topic
from leetvault.readme import _bar, _compute_streaks, aggregate_stats, generate_readme


def _make_problem(
    question_id: int,
    frontend_id: int,
    slug: str,
    difficulty: str,
    topics: list[str] | None = None,
) -> Problem:
    problem = Problem(
        question_id=question_id,
        frontend_id=frontend_id,
        title=slug.replace("-", " ").title(),
        title_slug=slug,
        difficulty=difficulty,
        paid_only=False,
        url=f"https://leetcode.com/problems/{slug}/",
    )
    if topics:
        problem.topics = [Topic(name=name) for name in topics]
    return problem


def _make_submission(
    submission_id: int, question_id: int, lang: str, timestamp: int, code: str = "code"
) -> Submission:
    submission = Submission(
        submission_id=submission_id,
        question_id=question_id,
        lang=lang,
        status="Accepted",
        runtime="10 ms",
        memory="10 MB",
        timestamp=timestamp,
        code_hash="hash",
        is_accepted=True,
    )
    submission.code = SubmissionCode(code=code)
    return submission


def test_bar_renders_proportional_fill() -> None:
    assert _bar(0.0, width=10) == "░" * 10
    assert _bar(100.0, width=10) == "█" * 10
    assert _bar(50.0, width=10) == "█" * 5 + "░" * 5


def test_compute_streaks_empty() -> None:
    assert _compute_streaks([]) == (0, 0)


def test_compute_streaks_single_day() -> None:
    from datetime import date

    assert _compute_streaks([date(2026, 1, 1)]) == (1, 1)


def test_compute_streaks_consecutive_and_gap() -> None:
    from datetime import date

    dates = [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 5),  # gap
        date(2026, 1, 6),
    ]
    current, longest = _compute_streaks(dates)
    assert longest == 3  # Jan 1-3
    assert current == 2  # Jan 5-6, the trailing run


def test_aggregate_stats_math(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)

    day = 86400
    with session_scope(factory) as session:
        array_topic = Topic(name="Array")
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Hash Table"])
        p1.topics.append(array_topic)
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]

        p2 = _make_problem(2, 2, "add-two-numbers", "Medium", topics=["Linked List"])
        p2.submissions = [_make_submission(200, 2, "python3", 1000 + day)]

        p3 = _make_problem(3, 3, "median-of-two-sorted-arrays", "Hard")
        p3.topics.append(array_topic)
        p3.submissions = [_make_submission(300, 3, "java", 1000 + 2 * day)]

        session.add_all([p1, p2, p3])

    with session_scope(factory) as session:
        stats = aggregate_stats(session)

    assert stats.total_solved == 3

    by_difficulty = {d.difficulty: d for d in stats.by_difficulty}
    assert by_difficulty["Easy"].count == 1
    assert by_difficulty["Medium"].count == 1
    assert by_difficulty["Hard"].count == 1
    assert by_difficulty["Easy"].percent == pytest.approx(100 / 3)

    by_language = {lang.lang: lang.count for lang in stats.by_language}
    assert by_language == {"python3": 2, "java": 1}

    by_topic = {t.name: t.count for t in stats.by_topic}
    assert by_topic["Array"] == 2
    assert by_topic["Hash Table"] == 1
    assert by_topic["Linked List"] == 1

    # 3 consecutive days -> current == longest == 3
    assert stats.current_streak == 3
    assert stats.longest_streak == 3

    assert [r.frontend_id for r in stats.table] == [1, 2, 3]
    assert stats.recent[0].frontend_id == 3  # most recent submission first


def test_generate_readme_writes_file_with_expected_sections(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        session.add(p1)

    with session_scope(factory) as session:
        readme_path = generate_readme(session, repo_path)

    content = readme_path.read_text(encoding="utf-8")
    assert "# LeetCode Solutions" in content
    assert "1 problem solved" in content
    assert "two-sum" in content or "Two Sum" in content
    assert "`Array` (1)" in content
