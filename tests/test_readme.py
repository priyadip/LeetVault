from __future__ import annotations

from pathlib import Path

import pytest

from leetvault.db import make_engine, make_session_factory, session_scope
from leetvault.models import Problem, Submission, SubmissionCode, Topic
from leetvault.readme import (
    _anchor,
    _bar,
    _compute_streaks,
    aggregate_stats,
    generate_readme,
)


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
    assert "[Array (1)](#array)" in content


def test_anchor_matches_github_heading_rules() -> None:
    # Must match GitHub's own heading-anchor algorithm or the topic links silently 404.
    assert _anchor("Array") == "array"
    assert _anchor("Hash Table") == "hash-table"
    assert _anchor("Heap (Priority Queue)") == "heap-priority-queue"
    assert _anchor("Depth-First Search") == "depth-first-search"
    assert _anchor("Union-Find") == "union-find"
    assert _anchor("Divide and Conquer") == "divide-and-conquer"


def test_topic_stats_carry_anchor_and_their_problems(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        array_topic = Topic(name="Array")
        heap_topic = Topic(name="Heap (Priority Queue)")

        p1 = _make_problem(1, 1, "two-sum", "Easy")
        p1.topics.append(array_topic)
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]

        p2 = _make_problem(2, 23, "merge-k-sorted-lists", "Hard")
        p2.topics.extend([array_topic, heap_topic])
        p2.submissions = [_make_submission(200, 2, "python3", 2000)]

        session.add_all([p1, p2])

    with session_scope(factory) as session:
        stats = aggregate_stats(session)

    by_name = {t.name: t for t in stats.by_topic}
    assert by_name["Array"].count == 2
    assert by_name["Array"].anchor == "array"
    assert [p.frontend_id for p in by_name["Array"].problems] == [1, 23]

    assert by_name["Heap (Priority Queue)"].anchor == "heap-priority-queue"
    assert [p.frontend_id for p in by_name["Heap (Priority Queue)"].problems] == [23]


def test_generate_readme_renders_clickable_topics_and_per_topic_sections(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        session.add(p1)

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    # the tag in the Topics summary links to the per-topic section...
    assert "[Array (1)](#array)" in content
    # ...and that section exists, with the problem listed under it
    assert "## Problems by Topic" in content
    assert "### Array" in content
    assert "[back to topics](#topics)" in content
    assert content.count("Two Sum") >= 2  # once in All Solutions, once under its topic


def test_readme_links_question_md_alongside_solution(tmp_path: Path) -> None:
    """Each row should offer both the problem statement and the solution."""
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        session.add(p1)

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    assert "[question](Problems/two-sum/question.md)" in content
    assert "[latest.py](Problems/two-sum/latest.py)" in content
    # both the All Solutions table and the per-topic table carry the column
    assert content.count("[question](Problems/two-sum/question.md)") == 2
    assert "| # | Problem | Difficulty | Language | Date | Question | Solution |" in content
    assert "| # | Problem | Difficulty | Question | Solution |" in content


def test_readme_table_separator_matches_column_count(tmp_path: Path) -> None:
    """A mismatched separator row silently breaks Markdown table rendering on GitHub."""
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        session.add(p1)

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("|") or set(line.replace("|", "").strip()) != {"-", " "}:
            continue
        header_cols = len(lines[i - 1].split("|"))
        sep_cols = len(line.split("|"))
        assert sep_cols == header_cols, f"line {i}: separator has {sep_cols}, header {header_cols}"


def test_readme_omits_analysis_column_when_feature_unused(tmp_path: Path) -> None:
    """AI analysis is opt-in. Users who never enable it must not get a column of dashes."""
    factory = make_session_factory(make_engine(tmp_path / "leetvault.db"))
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        session.add(p1)

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    assert "Analysis |" not in content
    assert "analysis.md" not in content


def test_readme_links_analysis_when_present(tmp_path: Path) -> None:
    """The files were on GitHub but unreachable from the dashboard, which is the same as
    missing. Link the ones that exist and mark the ones that do not."""
    factory = make_session_factory(make_engine(tmp_path / "leetvault.db"))
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        p1 = _make_problem(1, 1, "two-sum", "Easy", topics=["Array"])
        p1.submissions = [_make_submission(100, 1, "python3", 1000)]
        p2 = _make_problem(2, 2, "add-two-numbers", "Medium", topics=["Math"])
        p2.submissions = [_make_submission(200, 2, "python3", 2000)]
        session.add_all([p1, p2])

    analysed = repo_path / "Problems" / "two-sum"
    analysed.mkdir(parents=True)
    (analysed / "analysis.md").write_text("# analysis", encoding="utf-8")

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    assert "| Analysis |" in content
    assert "[analysis](Problems/two-sum/analysis.md)" in content
    # present in both the All Solutions table and the per-topic table
    assert content.count("[analysis](Problems/two-sum/analysis.md)") == 2
    assert "analysis](Problems/add-two-numbers" not in content


def test_readme_separator_matches_when_analysis_column_present(tmp_path: Path) -> None:
    """A partial backfill is the normal state on a free tier, so the mixed table must still
    render - a short separator row silently breaks the whole table on GitHub."""
    factory = make_session_factory(make_engine(tmp_path / "leetvault.db"))
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with session_scope(factory) as session:
        for i in (1, 2):
            p = _make_problem(i, i, f"problem-{i}", "Easy", topics=[f"Topic {i}"])
            p.submissions = [_make_submission(100 + i, i, "python3", 1000 * i)]
            session.add(p)

    solved = repo_path / "Problems" / "problem-1"
    solved.mkdir(parents=True)
    (solved / "analysis.md").write_text("# analysis", encoding="utf-8")

    with session_scope(factory) as session:
        content = generate_readme(session, repo_path).read_text(encoding="utf-8")

    # Every row must match the header of *its own* table; the All Solutions and per-topic
    # tables have different widths, so comparing across them proves nothing.
    lines = content.splitlines()
    width: int | None = None
    checked = 0
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            width = None
            continue
        if set(line.replace("|", "").strip()) == {"-", " "}:
            width = len(lines[i - 1].split("|"))
            assert len(line.split("|")) == width, f"separator mismatch at line {i}"
            continue
        if width is not None:
            assert len(line.split("|")) == width, f"row width mismatch at line {i}: {line}"
            checked += 1
    assert checked >= 4  # both tables, both the analysed and un-analysed problem
