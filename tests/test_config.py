from pathlib import Path

from rich.console import Console

from leetvault.config import DEFAULTS, ConfigStore, run_config


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


def test_run_config_shows_resolved_default_for_db_path() -> None:
    console = Console(record=True, width=200)
    run_config(console, key="db_path", value=None)
    output = console.export_text()
    assert "leetvault.db" in output
    assert "(default)" in output


def test_run_config_shows_explicit_value_without_default_marker() -> None:
    store = ConfigStore()
    store.set("db_path", "/custom/path/leetvault.db")
    console = Console(record=True, width=200)
    run_config(console, key="db_path", value=None)
    output = console.export_text()
    assert "/custom/path/leetvault.db" in output
    assert "(default)" not in output


def test_run_config_list_all_shows_resolved_defaults() -> None:
    console = Console(record=True, width=200)
    run_config(console, key=None, value=None)
    output = console.export_text()
    assert "db_path" in output
    assert "leetvault.db" in output
    assert "(default)" in output
