from pathlib import Path

from leetvault.client import ProblemMeta
from leetvault.git_writer import (
    ensure_notes,
    file_extension,
    write_history,
    write_latest_and_metadata,
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
