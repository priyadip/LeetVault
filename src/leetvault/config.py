"""Cross-platform persistent config: JSON file under the OS config dir.

No secrets live here (those go through :mod:`leetvault.auth` into the OS keyring) —
just non-sensitive settings like the target repo path/URL, DB location, and defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

APP_NAME = "leetvault"


def _windows_dir(env_var: str, fallback: str) -> Path:
    base = os.environ.get(env_var)
    return Path(base) if base else Path.home() / fallback


def config_dir() -> Path:
    if os.name == "nt":
        return _windows_dir("APPDATA", "AppData/Roaming") / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_NAME


def data_dir() -> Path:
    if os.name == "nt":
        return _windows_dir("LOCALAPPDATA", "AppData/Local") / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


DEFAULTS: dict[str, Any] = {
    "site": "com",
    "dedup_window_seconds": 86400,
    "db_path": None,  # resolved lazily to data_dir()/leetvault.db
    "repo_path": None,  # local working copy the CLI writes/commits to
    "repo_url": None,  # remote GitHub URL to push to
    "watch_interval_seconds": 90,
}


@dataclass
class ConfigStore:
    path: Path = field(default_factory=config_file)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULTS)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str) -> Any:
        return self.load().get(key)

    def set(self, key: str, value: Any) -> None:
        data = self.load()
        data[key] = value
        self.save(data)

    def resolved_db_path(self) -> Path:
        raw = self.get("db_path")
        if raw:
            return Path(raw)
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / "leetvault.db"

    def resolved_repo_path(self) -> Path:
        raw = self.get("repo_path")
        if raw:
            return Path(raw)
        return data_dir() / "repo"


def run_config(console: Console, key: str | None, value: str | None) -> None:
    store = ConfigStore()
    if key is None:
        data = store.load()
        for k, v in sorted(data.items()):
            console.print(f"[bold]{k}[/bold] = {v}")
        return
    if value is None:
        console.print(store.get(key))
        return
    parsed: Any = value
    if value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    elif value.isdigit():
        parsed = int(value)
    store.set(key, parsed)
    console.print(f"[green]Set[/green] {key} = {parsed}")
