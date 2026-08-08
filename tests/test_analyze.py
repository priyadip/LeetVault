from __future__ import annotations

from pathlib import Path

import pytest
import respx
import typer
from httpx import Response
from rich.console import Console

from leetvault.analyze import AnalysisRow, _select, existing_provider, run_analyze
from leetvault.client import ProblemMeta
from leetvault.config import ConfigStore
from leetvault.db import make_engine, make_session_factory, session_scope
from leetvault.git_writer import analysis_md_path, write_analysis_md
from leetvault.models import Problem, Submission, SubmissionCode

PROBLEM = ProblemMeta(
    question_id=1,
    frontend_id=1,
    title="Two Sum",
    title_slug="two-sum",
    difficulty="Easy",
    paid_only=False,
    url="https://leetcode.com/problems/two-sum/",
)


def _complete_analysis() -> str:
    """Every section the prompt requires - anything less is treated as a truncation."""
    from leetvault.ai.prompt import SECTION_NAMES

    return "\n\n".join(f"## {name}\nsomething about {name}." for name in SECTION_NAMES)


GOOD_ANALYSIS = _complete_analysis()


def _row(frontend_id: int, slug: str, provider: str | None) -> AnalysisRow:
    return AnalysisRow(
        frontend_id=frontend_id,
        title=slug.replace("-", " ").title(),
        title_slug=slug,
        difficulty="Easy",
        paid_only=False,
        url=f"https://leetcode.com/problems/{slug}/",
        topics=[],
        provider=provider,
        model=None,
    )


def _seed(tmp_path: Path, repo_path: Path) -> None:
    """A database and repo with one solved, already-analysed problem."""
    store = ConfigStore()
    store.set("db_path", str(tmp_path / "leetvault.db"))
    store.set("repo_path", str(repo_path))
    factory = make_session_factory(make_engine(store.resolved_db_path()))
    with session_scope(factory) as session:
        problem = Problem(
            question_id=1,
            frontend_id=1,
            title="Two Sum",
            title_slug="two-sum",
            difficulty="Easy",
            paid_only=False,
            url="https://leetcode.com/problems/two-sum/",
        )
        submission = Submission(
            submission_id=10,
            question_id=1,
            lang="python3",
            status="Accepted",
            runtime="1 ms",
            memory="1 MB",
            timestamp=1000,
            code_hash="deadbeef",
            is_accepted=True,
        )
        submission.code = SubmissionCode(submission_id=10, code="class Solution: pass")
        problem.submissions = [submission]
        session.add(problem)


def test_existing_provider_reads_the_footer(tmp_path: Path) -> None:
    path = write_analysis_md(tmp_path, PROBLEM, GOOD_ANALYSIS, "groq", "llama-3.3-70b")
    assert existing_provider(path) == ("groq", "llama-3.3-70b")


def test_existing_provider_handles_no_model(tmp_path: Path) -> None:
    path = write_analysis_md(tmp_path, PROBLEM, GOOD_ANALYSIS, "claude-cli", "")
    assert existing_provider(path) == ("claude-cli", None)


def test_existing_provider_none_when_absent(tmp_path: Path) -> None:
    assert existing_provider(tmp_path / "nope.md") == (None, None)


def test_select_by_slug_id_and_title() -> None:
    rows = [_row(1, "two-sum", "groq"), _row(2, "add-two-numbers", "gemini")]
    assert [r.title_slug for r in _select(rows, "two-sum", False, None)] == ["two-sum"]
    assert [r.title_slug for r in _select(rows, "2", False, None)] == ["add-two-numbers"]
    assert [r.title_slug for r in _select(rows, "add two", False, None)] == ["add-two-numbers"]


def test_select_by_slug_is_exact_not_substring() -> None:
    """ "two-sum" must not also drag in "two-sum-ii" when the slug matches exactly."""
    rows = [_row(1, "two-sum", "groq"), _row(167, "two-sum-ii", "groq")]
    assert [r.frontend_id for r in _select(rows, "two-sum", False, None)] == [1]


def test_select_by_provider_and_all() -> None:
    rows = [_row(1, "a", "groq"), _row(2, "b", "gemini"), _row(3, "c", None)]
    assert [r.frontend_id for r in _select(rows, None, False, "groq")] == [1]
    assert [r.frontend_id for r in _select(rows, None, False, "GEMINI")] == [2]
    assert len(_select(rows, None, True, None)) == 3


def test_analyze_requires_a_selection(tmp_path: Path) -> None:
    _seed(tmp_path, tmp_path / "repo")
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        run_analyze(
            console,
            target=None,
            provider_name=None,
            model=None,
            all_=False,
            from_=None,
            show_list=False,
            assume_yes=False,
        )
    assert "Nothing selected" in console.export_text()


def test_analyze_lists_without_generating(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _seed(tmp_path, repo_path)
    write_analysis_md(repo_path, PROBLEM, GOOD_ANALYSIS, "groq", "llama-3.3-70b")
    console = Console(record=True, width=200)
    # No network mock: any provider call would fail the test by raising.
    run_analyze(
        console,
        target=None,
        provider_name=None,
        model=None,
        all_=False,
        from_=None,
        show_list=True,
        assume_yes=False,
    )
    output = console.export_text()
    assert "Two Sum" in output
    assert "groq" in output


@respx.mock
def test_analyze_replaces_with_the_new_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    _seed(tmp_path, repo_path)
    write_analysis_md(repo_path, PROBLEM, "## Old\nprevious text", "groq", "llama-3.3-70b")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GOOD_ANALYSIS}}]})
    )

    console = Console(record=True, width=200)
    run_analyze(
        console,
        target="two-sum",
        provider_name="nvidia",
        model=None,
        all_=False,
        from_=None,
        show_list=False,
        assume_yes=True,
    )

    content = analysis_md_path(repo_path, "two-sum").read_text(encoding="utf-8")
    assert "previous text" not in content
    assert "## Approach" in content
    assert existing_provider(analysis_md_path(repo_path, "two-sum"))[0] == "nvidia"


@respx.mock
def test_failed_regeneration_keeps_the_existing_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old file is the user's only copy outside git history. A provider that is down
    must never turn "replace this" into "lose this"."""
    repo_path = tmp_path / "repo"
    _seed(tmp_path, repo_path)
    write_analysis_md(repo_path, PROBLEM, "## Old\nprevious text", "groq", "llama-3.3-70b")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(429, json={"error": {"message": "quota exceeded"}})
    )

    console = Console(record=True, width=200)
    run_analyze(
        console,
        target="two-sum",
        provider_name="nvidia",
        model=None,
        all_=False,
        from_=None,
        show_list=False,
        assume_yes=True,
    )

    content = analysis_md_path(repo_path, "two-sum").read_text(encoding="utf-8")
    assert "previous text" in content
    assert existing_provider(analysis_md_path(repo_path, "two-sum"))[0] == "groq"
    output = console.export_text()
    assert "kept the old one" in output
    assert "quota exceeded" in output


@respx.mock
def test_stub_response_does_not_replace_a_real_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    _seed(tmp_path, repo_path)
    write_analysis_md(repo_path, PROBLEM, "## Old\nprevious text", "groq", "llama-3.3-70b")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "I cannot help with that."}}]}
        )
    )

    console = Console(record=True, width=200)
    run_analyze(
        console,
        target="two-sum",
        provider_name="nvidia",
        model=None,
        all_=False,
        from_=None,
        show_list=False,
        assume_yes=True,
    )

    assert "previous text" in analysis_md_path(repo_path, "two-sum").read_text(encoding="utf-8")


def test_analyze_reports_when_nothing_matches(tmp_path: Path) -> None:
    _seed(tmp_path, tmp_path / "repo")
    console = Console(record=True, width=200)
    run_analyze(
        console,
        target="does-not-exist",
        provider_name=None,
        model=None,
        all_=False,
        from_=None,
        show_list=False,
        assume_yes=True,
    )
    assert "No problem matches" in console.export_text()
