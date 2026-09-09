"""Pushing when someone else has written to the remote.

The Q&A bot commits answers from a CI runner, so the local clone is behind after every
question answered. These use real git repositories rather than mocks: the bug was in git's
own behaviour, and a mock would have agreed with whatever the code did.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from git import Repo

from leetvault.git_writer import GitWriterError, _rebase_onto_remote, push


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=True)


def _remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], capture_output=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(remote), str(work)], capture_output=True)
    _run(work, "config", "user.email", "t@example.com")
    _run(work, "config", "user.name", "Test")
    (work / "seed.txt").write_text("seed", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-m", "seed")
    _run(work, "push", "origin", "HEAD:main")
    return remote, work


def _other_writer_commits(tmp_path: Path, remote: Path, name: str) -> None:
    """Someone else - in practice the bot on a CI runner - pushes to the same branch."""
    other = tmp_path / name
    subprocess.run(["git", "clone", str(remote), str(other)], capture_output=True)
    _run(other, "config", "user.email", "bot@example.com")
    _run(other, "config", "user.name", "Bot")
    (other / f"{name}.md").write_text("answer", encoding="utf-8")
    _run(other, "add", "-A")
    _run(other, "commit", "-m", "leetvault: answer issue #8")
    _run(other, "push", "origin", "HEAD:main")


def test_push_succeeds_when_the_remote_moved_ahead(tmp_path: Path) -> None:
    """The exact failure seen: "Note about fast-forwards" after the bot committed qa.md."""
    remote, work = _remote_and_clone(tmp_path)
    _other_writer_commits(tmp_path, remote, "bot")

    (work / "local.txt").write_text("local work", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-m", "leetvault: install Q&A bot")

    _rebase_onto_remote(Repo(work), str(remote), "main")
    _run(work, "push", "origin", "HEAD:main")

    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert "install Q&A bot" in log
    assert "answer issue #8" in log, "the other writer's commit must survive"


def test_push_still_works_when_nothing_else_changed(tmp_path: Path) -> None:
    remote, work = _remote_and_clone(tmp_path)
    (work / "local.txt").write_text("local", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-m", "local only")
    _rebase_onto_remote(Repo(work), str(remote), "main")
    _run(work, "push", "origin", "HEAD:main")
    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert "local only" in log


def test_a_real_conflict_leaves_the_repo_usable(tmp_path: Path) -> None:
    """A rebase that cannot proceed must not strand the working tree mid-rebase."""
    remote, work = _remote_and_clone(tmp_path)

    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], capture_output=True)
    _run(other, "config", "user.email", "b@example.com")
    _run(other, "config", "user.name", "Bot")
    (other / "shared.txt").write_text("theirs", encoding="utf-8")
    _run(other, "add", "-A")
    _run(other, "commit", "-m", "theirs")
    _run(other, "push", "origin", "HEAD:main")

    (work / "shared.txt").write_text("ours", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-m", "ours")

    with pytest.raises(GitWriterError) as exc:
        _rebase_onto_remote(Repo(work), str(remote), "main")
    assert "diverged" in str(exc.value)

    state = subprocess.run(
        ["git", "-C", str(work), "status"], capture_output=True, text=True
    ).stdout
    assert "rebase in progress" not in state.lower(), "must abort a failed rebase"


def test_push_rebases_before_pushing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The order matters: pushing first is exactly the failure this fixes."""
    import leetvault.git_writer as gw

    calls: list[str] = []
    monkeypatch.setattr(gw, "_rebase_onto_remote", lambda *a, **k: calls.append("rebase"))

    class FakeGit:
        def update_environment(self, **kwargs: str) -> None:
            # push disables the interactive credential prompt before doing anything else.
            calls.append("env")

        def push(self, *args: str) -> None:
            calls.append("push")

    class FakeRepo:
        git = FakeGit()

    gw.push(FakeRepo(), "https://github.com/o/r.git", "tok", "main")  # type: ignore[arg-type]
    assert calls == ["env", "rebase", "push"]


def test_scrub_leaves_a_message_alone_when_there_is_no_pat() -> None:
    """An empty PAT matches between every character, which would replace an error message
    with a wall of asterisks and hide the real failure."""
    from leetvault.git_writer import _scrub

    assert _scrub("", "fatal: some real error") == "fatal: some real error"
    assert _scrub("secret", "used secret here") == "used *** here"


def test_push_never_waits_on_a_credential_prompt() -> None:
    """With no terminal to answer it, git blocks forever and the command simply never
    returns. Observed for real: after a stored PAT was revoked, a push hung instead of
    falling through to the other credential helper. A refusal is actionable; a hang is not.
    """
    captured: dict[str, str] = {}

    class FakeGit:
        def update_environment(self, **kwargs: str) -> None:
            captured.update(kwargs)

        def fetch(self, *args: str) -> None:
            return None

        def rebase(self, *args: str) -> None:
            return None

        def push(self, *args: str) -> None:
            return None

    class FakeRepo:
        git = FakeGit()

    push(FakeRepo(), "https://github.com/o/r.git", "tok", "main")  # type: ignore[arg-type]
    assert captured.get("GIT_TERMINAL_PROMPT") == "0"


def test_the_bot_helper_disables_the_prompt_too(monkeypatch: pytest.MonkeyPatch) -> None:
    import leetvault.bot as bot

    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["env"] = kwargs.get("env") or {}
        return Result()

    monkeypatch.setattr(bot.subprocess, "run", fake_run)
    bot._git(Path("."), ["status"])
    assert captured["env"].get("GIT_TERMINAL_PROMPT") == "0"  # type: ignore[union-attr]
