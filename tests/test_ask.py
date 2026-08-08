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

    import yaml

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


def test_repo_slug_from_every_remote_shape() -> None:
    from leetvault.bot import repo_slug

    assert repo_slug("https://github.com/priyadip/DSA-LeetCode-.git") == "priyadip/DSA-LeetCode-"
    assert repo_slug("git@github.com:priyadip/DSA-LeetCode-.git") == "priyadip/DSA-LeetCode-"
    assert repo_slug("https://github.com/a/b") == "a/b"
    assert repo_slug("nonsense") is None
    assert repo_slug("") is None


def test_secrets_are_passed_on_stdin_not_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key in argv is visible in a process listing and in shell history. gh reads it from
    stdin instead, so it never appears in either."""
    import leetvault.bot as bot

    calls: list[tuple[list[str], str | None]] = []

    def fake_run(args: list[str], stdin: str | None = None) -> tuple[bool, str]:
        calls.append((args, stdin))
        return True, ""

    monkeypatch.setattr(bot, "_run_gh", fake_run)
    monkeypatch.setattr(bot, "load_provider_key", lambda p: "SECRET-VALUE", raising=False)
    from leetvault import auth

    monkeypatch.setattr(auth, "load_provider_key", lambda p: "SECRET-VALUE")

    steps = bot._upload_secrets("owner/repo")
    assert steps and all(s.ok for s in steps)
    for args, stdin in calls:
        assert "SECRET-VALUE" not in " ".join(args), "key leaked into argv"
        assert stdin == "SECRET-VALUE"
        assert args[:2] == ["secret", "set"]


def test_every_stored_key_is_uploaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whichever backends you have configured should all work from the bot, not just the
    one currently selected - switching providers should not mean redoing setup."""
    import leetvault.bot as bot
    from leetvault import auth

    monkeypatch.setattr(bot, "_run_gh", lambda args, stdin=None: (True, ""))
    monkeypatch.setattr(
        auth, "load_provider_key", lambda p: "k" if p in {"gemini", "groq", "nvidia"} else None
    )
    names = [s.name for s in bot._upload_secrets("owner/repo")]
    assert names == ["secret GEMINI_API_KEY", "secret GROQ_API_KEY", "secret NVIDIA_API_KEY"]


def test_install_reports_each_step_and_survives_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-finished setup must say which half, not just fail."""
    import leetvault.bot as bot
    from leetvault import auth

    ConfigStore().set("repo_url", "https://github.com/owner/repo.git")
    ConfigStore().set("ai_provider", "groq")
    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(auth, "load_provider_key", lambda p: "k" if p == "groq" else None)

    def fake_run(args: list[str], stdin: str | None = None) -> tuple[bool, str]:
        if args[0] == "auth":
            return True, "logged in"
        if args[0] == "variable":
            return False, "HTTP 403: Resource not accessible"
        return True, ""

    monkeypatch.setattr(bot, "_run_gh", fake_run)
    monkeypatch.setattr(bot, "_commit_and_push", lambda p: bot.Step("commit and push", True))

    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    output = console.export_text()
    assert "OK" in output and "FAIL" in output
    assert "403" in output
    assert "gh auth refresh -s repo,workflow" in output
    assert (tmp_path / WORKFLOW_PATH).exists()  # files still written


def test_manual_mode_touches_nothing_on_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import leetvault.bot as bot

    def explode(*args: object, **kwargs: object) -> tuple[bool, str]:
        raise AssertionError("--manual must not call gh")

    monkeypatch.setattr(bot, "_run_gh", explode)
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=True)
    assert (tmp_path / WORKFLOW_PATH).exists()
    assert "Manual setup" in console.export_text()


def test_install_falls_back_when_gh_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without gh the files are still written and the manual steps printed - the feature
    degrades rather than disappearing."""
    import leetvault.bot as bot

    monkeypatch.setattr(bot, "_gh", lambda: None)
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    output = console.export_text()
    assert (tmp_path / WORKFLOW_PATH).exists()
    assert "not installed" in output
    assert "Manual setup" in output


def test_push_names_its_refspec_rather_than_relying_on_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo leetvault created and only ever pushed to by URL has no upstream, so a bare
    `git push` fails with git's push.autoSetupRemote advice - which reads like a permissions
    problem and is not one."""
    import leetvault.bot as bot

    calls: list[list[str]] = []

    def fake_git(repo_path, args, *, credential_helper=None):  # type: ignore[no-untyped-def]
        calls.append(args)
        if args[:2] == ["diff", "--staged"]:
            return 1, ""  # something staged
        return 0, ""

    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(bot, "_git", fake_git)
    step = bot._commit_and_push(tmp_path)
    assert step.ok
    push = next(a for a in calls if a and a[0] == "push")
    assert push == ["push", "origin", "HEAD:main"]


def test_push_is_retried_when_a_previous_run_committed_but_failed_to_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reporting "already up to date" because there is nothing new to commit would leave
    the workflow on disk forever, never reaching GitHub."""
    import leetvault.bot as bot

    calls: list[list[str]] = []

    def fake_git(repo_path, args, *, credential_helper=None):  # type: ignore[no-untyped-def]
        calls.append(args)
        return 0, ""  # diff --staged returns 0 => nothing staged, already committed

    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(bot, "_git", fake_git)
    step = bot._commit_and_push(tmp_path)
    assert step.ok
    assert any(a and a[0] == "push" for a in calls), "must still push when nothing to commit"
    assert not any(a and a[0] == "commit" for a in calls), "nothing to commit"


def test_push_uses_gh_credentials_for_the_workflow_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import leetvault.bot as bot

    helpers: list[str | None] = []

    def fake_git(repo_path, args, *, credential_helper=None):  # type: ignore[no-untyped-def]
        if args and args[0] == "push":
            helpers.append(credential_helper)
        return (1, "") if args[:2] == ["diff", "--staged"] else (0, "")

    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(bot, "_git", fake_git)
    bot._commit_and_push(tmp_path)
    assert helpers == ["/usr/bin/gh"]


def test_a_git_failure_is_not_blamed_on_gh_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Five of six steps succeeded and the report still said gh needed scopes and reprinted
    the whole manual checklist - which reads as though nothing worked."""
    import leetvault.bot as bot
    from leetvault import auth

    ConfigStore().set("repo_url", "https://github.com/owner/repo.git")
    ConfigStore().set("ai_provider", "groq")
    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(auth, "load_provider_key", lambda p: "k" if p == "groq" else None)
    monkeypatch.setattr(bot, "_run_gh", lambda args, stdin=None: (True, ""))
    monkeypatch.setattr(
        bot,
        "_commit_and_push",
        lambda p, branch="main": bot.Step("commit and push", False, "no upstream configured"),
    )

    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    output = console.export_text()
    assert "1 step(s) need doing by hand" in output
    assert "gh auth refresh" not in output, "a git error must not be blamed on gh scopes"
    assert "push origin HEAD:main" in output, "must give the command that actually fixes it"
    assert "New repository secret" not in output, "secrets succeeded; do not reprint them"


def test_permission_failures_still_recommend_refreshing_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import leetvault.bot as bot
    from leetvault import auth

    ConfigStore().set("repo_url", "https://github.com/owner/repo.git")
    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(auth, "load_provider_key", lambda p: "k" if p == "groq" else None)

    def fake_run(args: list[str], stdin: str | None = None) -> tuple[bool, str]:
        if args[0] == "auth":
            return True, ""
        return False, "HTTP 403: Resource not accessible by integration"

    monkeypatch.setattr(bot, "_run_gh", fake_run)
    monkeypatch.setattr(
        bot, "_commit_and_push", lambda p, branch="main": bot.Step("commit and push", True)
    )
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    assert "gh auth refresh -s repo,workflow" in console.export_text()


def test_workflow_passes_a_model_when_one_is_configured() -> None:
    """Without this the provider's own default is used - for Groq that is
    llama-3.3-70b-versatile, the model that produced a wrong analysis."""
    from leetvault.bot import WORKFLOW

    assert "vars.LEETVAULT_AI_MODEL" in WORKFLOW
    assert "--model" in WORKFLOW


def test_workflow_omits_the_model_flag_when_unset() -> None:
    """An empty --model would override each provider's default with nothing."""
    import re

    import yaml

    from leetvault.bot import WORKFLOW

    run = next(
        s["run"]
        for s in yaml.safe_load(WORKFLOW)["jobs"]["answer"]["steps"]
        if s.get("name") == "Answer"
    )
    assert re.search(r'if \[ -n "\$MODEL" \]', run), "must guard on the variable being set"


def test_model_variable_is_set_only_when_pinned_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An install that never chose a model should leave each provider on its own default."""
    import leetvault.bot as bot
    from leetvault import auth

    store = ConfigStore()
    store.set("repo_url", "https://github.com/owner/repo.git")
    store.set("ai_provider", "groq")
    monkeypatch.setattr(bot, "_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(auth, "load_provider_key", lambda p: "k" if p == "groq" else None)
    monkeypatch.setattr(bot, "_run_gh", lambda args, stdin=None: (True, ""))
    monkeypatch.setattr(
        bot, "_commit_and_push", lambda p, branch="main": bot.Step("commit and push", True)
    )

    store.set("ai_model", None)
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    assert "LEETVAULT_AI_MODEL" not in console.export_text()

    store.set("ai_model", "openai/gpt-oss-120b")
    console = Console(record=True, width=200)
    run_bot(console, install=True, repo=tmp_path, show=False, manual=False)
    assert "variable LEETVAULT_AI_MODEL" in console.export_text()
