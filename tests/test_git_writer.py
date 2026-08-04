from pathlib import Path

import pytest
import respx
from git import GitCommandError
from httpx import Response

from leetvault.client import ProblemMeta, QuestionDetail, SimilarQuestion
from leetvault.git_writer import (
    GitWriterError,
    _authenticated_url,
    _scrub,
    ensure_notes,
    ensure_repo,
    file_extension,
    push,
    question_md_path,
    stage_and_commit,
    sync_to_github,
    validate_github_pat,
    write_history,
    write_latest_and_metadata,
    write_question_md,
)

PROBLEM = ProblemMeta(
    question_id=1,
    frontend_id=1,
    title="Two Sum",
    title_slug="two-sum",
    difficulty="Easy",
    paid_only=False,
    url="https://leetcode.com/problems/two-sum/",
)


def test_file_extension_known_and_unknown() -> None:
    assert file_extension("python3") == "py"
    assert file_extension("rust") == "rs"
    assert file_extension("some-made-up-lang") == "txt"


def test_write_history_only_writes_once(tmp_path: Path) -> None:
    first = write_history(tmp_path, "two-sum", 1, "python3", "print(1)")
    assert first.is_new is True
    assert first.path.read_text(encoding="utf-8") == "print(1)"

    second = write_history(tmp_path, "two-sum", 1, "python3", "print(2)")
    assert second.is_new is False
    # existing history entries are immutable
    assert second.path.read_text(encoding="utf-8") == "print(1)"


def test_write_latest_and_metadata(tmp_path: Path) -> None:
    latest_path, metadata_path = write_latest_and_metadata(
        tmp_path, PROBLEM, 1, "python3", "print(1)", 1000, "10 ms", "5 MB", 88.5, 42.1
    )
    assert latest_path.read_text(encoding="utf-8") == "print(1)"
    assert metadata_path.exists()

    latest_path2, _ = write_latest_and_metadata(
        tmp_path, PROBLEM, 2, "python3", "print(2)", 2000, "9 ms", "5 MB", 90.0, 43.0
    )
    assert latest_path2.read_text(encoding="utf-8") == "print(2)"


def test_ensure_notes_is_idempotent(tmp_path: Path) -> None:
    path = ensure_notes(tmp_path, PROBLEM)
    path.write_text("my custom notes", encoding="utf-8")
    path_again = ensure_notes(tmp_path, PROBLEM)
    assert path_again.read_text(encoding="utf-8") == "my custom notes"


def test_ensure_repo_inits_then_reopens(tmp_path: Path) -> None:
    repo1 = ensure_repo(tmp_path)
    assert (tmp_path / ".git").exists()
    repo2 = ensure_repo(tmp_path)
    assert repo1.working_tree_dir == repo2.working_tree_dir


def test_stage_and_commit_noop_then_commits(tmp_path: Path) -> None:
    repo = ensure_repo(tmp_path)
    assert stage_and_commit(repo, "empty") is False

    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    assert stage_and_commit(repo, "add file") is True
    assert repo.head.commit.message == "add file"

    # nothing changed since the last commit
    assert stage_and_commit(repo, "should be no-op") is False


def test_authenticated_url_injects_token_without_leaking_in_repr() -> None:
    url = _authenticated_url("https://github.com/owner/repo.git", "ghp_secret123")
    assert url == "https://x-access-token:ghp_secret123@github.com/owner/repo.git"


def test_scrub_removes_pat_from_text() -> None:
    assert _scrub("ghp_secret123", "remote: error ghp_secret123 rejected") == (
        "remote: error *** rejected"
    )


def test_push_wraps_git_command_error_and_scrubs_pat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = ensure_repo(tmp_path)
    pat = "ghp_supersecret"

    class _FailingGit:
        def push(self, url: str, refspec: str) -> None:
            raise GitCommandError(["git", "push", url, refspec], 1, stderr=f"denied for {pat}")

    monkeypatch.setattr(repo, "git", _FailingGit())

    with pytest.raises(GitWriterError) as exc_info:
        push(repo, "https://github.com/owner/repo.git", pat)
    assert pat not in str(exc_info.value)
    assert "***" in str(exc_info.value)


@respx.mock
def test_validate_github_pat_success() -> None:
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "octocat"})
    )
    assert validate_github_pat("ghp_x") == "octocat"


@respx.mock
def test_validate_github_pat_failure() -> None:
    respx.get("https://api.github.com/user").mock(return_value=Response(401, json={}))
    assert validate_github_pat("bad-token") is None


def test_sync_to_github_noop_when_nothing_changed(tmp_path: Path) -> None:
    from rich.console import Console

    ensure_repo(tmp_path)  # pre-existing empty repo, nothing to stage
    console = Console(record=True, width=200)
    sync_to_github(console, tmp_path, "https://github.com/owner/repo.git", "pat", "msg")
    assert "Nothing new to commit" in console.export_text()


def test_sync_to_github_commits_and_pushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rich.console import Console

    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "leetvault.git_writer.push",
        lambda repo, repo_url, pat, branch="main": pushed.append((repo_url, pat)),
    )

    (tmp_path / "Problems").mkdir()
    (tmp_path / "Problems" / "note.txt").write_text("x", encoding="utf-8")

    console = Console(record=True, width=200)
    sync_to_github(console, tmp_path, "https://github.com/owner/repo.git", "pat-value", "msg")
    assert pushed == [("https://github.com/owner/repo.git", "pat-value")]
    assert "Committed and pushed" in console.export_text()


def test_sync_to_github_still_pushes_unpushed_commit_when_nothing_new_to_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: a prior run may have committed successfully but failed to push
    (e.g. a bad PAT) - this happened for real during Phase 4's live smoke test. The next
    run must still push that stranded commit even with no new files to stage."""
    from rich.console import Console

    repo = ensure_repo(tmp_path)
    (tmp_path / "already-committed.txt").write_text("x", encoding="utf-8")
    assert stage_and_commit(repo, "prior commit") is True

    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "leetvault.git_writer.push",
        lambda repo, repo_url, pat, branch="main": pushed.append((repo_url, pat)),
    )

    console = Console(record=True, width=200)
    sync_to_github(console, tmp_path, "https://github.com/owner/repo.git", "pat-value", "msg")
    assert pushed == [("https://github.com/owner/repo.git", "pat-value")]
    output = console.export_text()
    assert "Nothing new to commit" in output
    assert "Pushed" in output


def _detail(
    content: str | None = "<p>Do the thing.</p>",
    hints: list[str] | None = None,
    is_paid_only: bool = False,
    similar: list[SimilarQuestion] | None = None,
) -> QuestionDetail:
    return QuestionDetail(
        topics=["Array"],
        content=content,
        hints=hints or [],
        is_paid_only=is_paid_only,
        similar_questions=similar or [],
    )


def test_write_question_md_renders_header_and_description(tmp_path: Path) -> None:
    path = write_question_md(tmp_path, PROBLEM, _detail(), ["Array", "Hash Table"])
    content = path.read_text(encoding="utf-8")

    assert path.name == "question.md"
    assert content.startswith("# 1. Two Sum")
    assert "**Difficulty:** Easy" in content
    assert "**Topics:** Array, Hash Table" in content
    assert "[View on LeetCode](https://leetcode.com/problems/two-sum/)" in content
    assert "## Description" in content
    assert "Do the thing." in content
    assert "<p>" not in content  # HTML was converted, not dumped


def test_write_question_md_collapses_hints(tmp_path: Path) -> None:
    path = write_question_md(
        tmp_path, PROBLEM, _detail(hints=["<p>Use a <code>map</code>.</p>"]), ["Array"]
    )
    content = path.read_text(encoding="utf-8")
    # Hints must be collapsed so opening the file doesn't spoil the problem.
    assert "<details>" in content
    assert "<summary>Hint 1</summary>" in content
    assert "Use a `map`." in content


def test_write_question_md_handles_paid_only(tmp_path: Path) -> None:
    path = write_question_md(tmp_path, PROBLEM, _detail(content=None, is_paid_only=True), ["Array"])
    content = path.read_text(encoding="utf-8")
    assert "Premium" in content


def test_write_question_md_lists_similar_questions(tmp_path: Path) -> None:
    similar = [SimilarQuestion(title="3Sum", title_slug="3sum", difficulty="Medium")]
    path = write_question_md(tmp_path, PROBLEM, _detail(similar=similar), ["Array"])
    content = path.read_text(encoding="utf-8")
    assert "## Similar Questions" in content
    assert "[3Sum](https://leetcode.com/problems/3sum/) - Medium" in content


def test_write_question_md_overwrites_on_rerun(tmp_path: Path) -> None:
    write_question_md(tmp_path, PROBLEM, _detail(content="<p>old</p>"), ["Array"])
    path = write_question_md(tmp_path, PROBLEM, _detail(content="<p>new</p>"), ["Array"])
    content = path.read_text(encoding="utf-8")
    assert "new" in content
    assert "old" not in content


def test_question_md_path_matches_written_location(tmp_path: Path) -> None:
    expected = question_md_path(tmp_path, PROBLEM.title_slug)
    actual = write_question_md(tmp_path, PROBLEM, _detail(), ["Array"])
    assert actual == expected
    assert expected.parent.name == "two-sum"
