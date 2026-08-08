from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
import typer
from httpx import Response
from rich.console import Console

from leetvault.ask import find_problem_dir, load_context, run_ask
from leetvault.bot import TEMPLATE_PATH, WORKFLOW, WORKFLOW_PATH, run_bot
from leetvault.client import ProblemMeta
from leetvault.config import ConfigStore
from leetvault.git_writer import append_qa, qa_md_path

PROBLEM = ProblemMeta(
    question_id=1,
    frontend_id=1,
    title="Two Sum",
    title_slug="two-sum",
    difficulty="Easy",
    paid_only=False,
    url="https://leetcode.com/problems/two-sum/",
)


def _repo(tmp_path: Path, slug: str = "two-sum", frontend_id: int = 1) -> Path:
    """A repo laid out the way sync writes one - no database, as on a CI runner."""
    d = tmp_path / "Problems" / slug
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(
        json.dumps(
            {
                "question_id": frontend_id,
                "frontend_id": frontend_id,
                "title": slug.replace("-", " ").title(),
                "title_slug": slug,
                "difficulty": "Easy",
                "paid_only": False,
                "url": f"https://leetcode.com/problems/{slug}/",
                "lang": "python3",
            }
        ),
        encoding="utf-8",
    )
    (d / "latest.py").write_text("class Solution:\n    def twoSum(self): ...", encoding="utf-8")
    (d / "question.md").write_text("# 1. Two Sum\n\nFind two numbers.", encoding="utf-8")
    return tmp_path


def test_find_problem_by_slug_number_and_partial_title(tmp_path: Path) -> None:
    """Reached from a GitHub issue title as often as from a shell, so "3348" and
    "smallest divisible" both have to work."""
    _repo(tmp_path, "two-sum", 1)
    _repo(tmp_path, "smallest-divisible-digit-product-ii", 3348)
    assert find_problem_dir(tmp_path, "two-sum") is not None
    assert find_problem_dir(tmp_path, "3348").name == "smallest-divisible-digit-product-ii"
    assert find_problem_dir(tmp_path, "smallest divisible").name.startswith("smallest-")
    assert find_problem_dir(tmp_path, "nonexistent") is None


def test_ambiguous_partial_match_is_refused(tmp_path: Path) -> None:
    """Answering the wrong problem is worse than saying which ones matched."""
    _repo(tmp_path, "two-sum", 1)
    _repo(tmp_path, "two-sum-ii", 167)
    assert find_problem_dir(tmp_path, "two-sum") is not None  # exact wins
    assert find_problem_dir(tmp_path, "two-su") is None  # ambiguous


def test_context_comes_from_the_repo_not_a_database(tmp_path: Path) -> None:
    """This is what lets the bot run on a CI runner with no DB, keyring or session."""
    _repo(tmp_path)
    ctx = load_context(tmp_path, tmp_path / "Problems" / "two-sum")
    assert ctx is not None
    assert ctx.meta.title == "Two Sum"
    assert "twoSum" in ctx.code
    assert "Find two numbers" in ctx.statement


def test_context_is_none_without_a_solution(tmp_path: Path) -> None:
    d = tmp_path / "Problems" / "empty"
    d.mkdir(parents=True)
    assert load_context(tmp_path, d) is None


def test_qa_log_appends_rather_than_replaces(tmp_path: Path) -> None:
    """A Q&A log is a conversation - the point is re-reading what you asked months ago."""
    append_qa(tmp_path, PROBLEM, "first?", "answer one", "groq", "m", "2026-01-01 00:00 UTC")
    append_qa(tmp_path, PROBLEM, "second?", "answer two", "groq", "m", "2026-01-02 00:00 UTC")
    text = qa_md_path(tmp_path, "two-sum").read_text(encoding="utf-8")
    assert text.count("# 1. Two Sum - Q&A") == 1  # header written once
    assert "first?" in text and "second?" in text
    assert text.index("first?") < text.index("second?")  # chronological


@respx.mock
def test_ask_saves_the_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "Because lookups are O(1)."}}]}
        )
    )
    console = Console(record=True, width=200)
    run_ask(
        console,
        problem="two-sum",
        question="why a hash map?",
        provider_name="groq",
        model=None,
        repo=tmp_path,
        save=True,
        push=False,
    )
    text = qa_md_path(tmp_path, "two-sum").read_text(encoding="utf-8")
    assert "why a hash map?" in text
    assert "Because lookups are O(1)." in text
    assert "groq" in text


@respx.mock
def test_ask_can_answer_without_saving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "An answer."}}]})
    )
    console = Console(record=True, width=200)
    run_ask(
        console,
        problem="two-sum",
        question="q?",
        provider_name="groq",
        model=None,
        repo=tmp_path,
        save=False,
        push=False,
    )
    assert "An answer." in console.export_text()
    assert not qa_md_path(tmp_path, "two-sum").exists()


def test_ask_reports_an_unknown_problem(tmp_path: Path) -> None:
    _repo(tmp_path)
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        run_ask(
            console,
            problem="does-not-exist",
            question="q?",
            provider_name="groq",
            model=None,
            repo=tmp_path,
            save=True,
            push=False,
        )
    assert "No problem matches" in console.export_text()


def test_bot_installs_a_valid_workflow(tmp_path: Path) -> None:
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False)
    workflow = tmp_path / WORKFLOW_PATH
    assert workflow.exists()
    assert (tmp_path / TEMPLATE_PATH).exists()

    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert "jobs" in parsed
    assert parsed["jobs"]["answer"]["runs-on"] == "ubuntu-latest"


def test_workflow_answers_only_the_repository_owner() -> None:
    """Anyone can open an issue on a public repo. Without this gate every stranger would be
    spending the owner's API quota, and the secret is available to the job either way."""
    assert "github.event.issue.user.login == github.repository_owner" in WORKFLOW
    assert "github.event.comment.user.login == github.repository_owner" in WORKFLOW


def test_workflow_reads_keys_from_secrets_never_from_the_repo() -> None:
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY"):
        assert f"secrets.{key}" in WORKFLOW
    # A literal key would be a catastrophic thing to commit into a public repo.
    for prefix in ("gsk_", "nvapi-", "sk-ant-", "AIza"):
        assert prefix not in WORKFLOW


def test_bot_show_does_not_write_anything(tmp_path: Path) -> None:
    console = Console(record=True, width=200)
    run_bot(console, install=False, repo=tmp_path, show=True)
    assert not (tmp_path / WORKFLOW_PATH).exists()
    output = console.export_text()
    assert "Secrets and variables" in output


def test_bot_names_the_secret_matching_the_configured_provider(tmp_path: Path) -> None:
    ConfigStore().set("ai_provider", "nvidia")
    console = Console(record=True, width=200)
    run_bot(console, install=False, repo=tmp_path, show=True)
    assert "NVIDIA_API_KEY" in console.export_text()
