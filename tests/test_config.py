from pathlib import Path

from leetvault.config import DEFAULTS, ConfigStore


def test_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    store = ConfigStore(path=tmp_path / "config.json")
    assert store.load() == DEFAULTS


def test_set_then_get_roundtrips(tmp_path: Path) -> None:
    store = ConfigStore(path=tmp_path / "config.json")
    store.set("repo_url", "https://github.com/example/leetcode.git")
    assert store.get("repo_url") == "https://github.com/example/leetcode.git"
    # unrelated defaults survive a partial write
    assert store.get("dedup_window_seconds") == DEFAULTS["dedup_window_seconds"]


def test_resolved_db_path_falls_back_to_data_dir(tmp_path: Path) -> None:
    store = ConfigStore(path=tmp_path / "config.json")
    resolved = store.resolved_db_path()
    assert resolved.name == "leetvault.db"
