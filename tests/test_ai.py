from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response
from rich.console import Console

from leetvault.ai import build_user_prompt, get_provider, provider_names
from leetvault.ai.providers import (
    AnthropicProvider,
    ClaudeCliProvider,
    OllamaProvider,
    available_providers,
)
from leetvault.ai_setup import run_ai_setup
from leetvault.client import ProblemMeta
from leetvault.config import ConfigStore
from leetvault.git_writer import analysis_md_path, write_analysis_md

PROBLEM = ProblemMeta(
    question_id=1,
    frontend_id=1,
    title="Two Sum",
    title_slug="two-sum",
    difficulty="Easy",
    paid_only=False,
    url="https://leetcode.com/problems/two-sum/",
)


@pytest.fixture(autouse=True)
def _no_ambient_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detection must not depend on what happens to be installed on the test machine."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ClaudeCliProvider, "_executable", classmethod(lambda cls: None))


def test_provider_registry_exposes_all_backends() -> None:
    assert set(provider_names()) == {"ollama", "claude-cli", "anthropic"}


def test_get_provider_unknown_returns_none() -> None:
    assert get_provider("does-not-exist") is None


def test_get_provider_uses_default_model_when_unset() -> None:
    provider = get_provider("ollama")
    assert provider is not None
    assert provider.model == OllamaProvider.default_model


def test_get_provider_honours_explicit_model() -> None:
    provider = get_provider("ollama", "codellama:13b")
    assert provider is not None
    assert provider.model == "codellama:13b"


@respx.mock
def test_ollama_detected_when_running() -> None:
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=Response(200, json={"models": [{"name": "qwen2.5-coder:7b"}]})
    )
    info = OllamaProvider.detect()
    assert info is not None
    assert info.name == "ollama"
    assert "free" in info.cost


@respx.mock
def test_ollama_not_detected_when_absent() -> None:
    respx.get("http://localhost:11434/api/tags").mock(side_effect=ConnectionError)
    assert OllamaProvider.detect() is None


@respx.mock
def test_ollama_generate_returns_body() -> None:
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "## Approach\nHash map.\n"}})
    )
    body = OllamaProvider().generate("analyse this")
    assert body == "## Approach\nHash map."


@respx.mock
def test_ollama_generate_returns_none_on_error() -> None:
    """A failing model must never break a sync - providers return None, not raise."""
    respx.post("http://localhost:11434/api/chat").mock(return_value=Response(500, json={}))
    assert OllamaProvider().generate("analyse this") is None


def test_claude_cli_not_detected_when_missing() -> None:
    assert ClaudeCliProvider.detect() is None


def test_claude_cli_detected_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ClaudeCliProvider, "_executable", classmethod(lambda cls: "/usr/bin/claude")
    )
    info = ClaudeCliProvider.detect()
    assert info is not None
    assert "subscription" in info.cost


def test_claude_cli_generate_uses_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(
        ClaudeCliProvider, "_executable", classmethod(lambda cls: "/usr/bin/claude")
    )
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="## Approach\nTwo pointers.", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body = ClaudeCliProvider().generate("analyse this")
    assert body == "## Approach\nTwo pointers."
    assert captured["cmd"][:2] == ["/usr/bin/claude", "-p"]  # type: ignore[index]


def test_claude_cli_generate_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(
        ClaudeCliProvider, "_executable", classmethod(lambda cls: "/usr/bin/claude")
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
    assert ClaudeCliProvider().generate("analyse this") is None


def test_anthropic_not_detected_without_credentials() -> None:
    assert AnthropicProvider.detect() is None


def test_available_providers_empty_when_nothing_installed() -> None:
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(side_effect=ConnectionError)
        assert available_providers() == []


def test_build_user_prompt_includes_code_and_topics() -> None:
    prompt = build_user_prompt(
        "Two Sum", "Easy", ["Array", "Hash Table"], "Find two numbers.", "python3", "pass"
    )
    assert "Two Sum" in prompt
    assert "Array, Hash Table" in prompt
    assert "```python3" in prompt
    assert "pass" in prompt


def test_build_user_prompt_handles_missing_statement() -> None:
    prompt = build_user_prompt("Two Sum", "Easy", [], "", "python3", "pass")
    assert "statement unavailable" in prompt
    assert "unknown" in prompt  # topics


def test_write_analysis_md_keeps_attribution(tmp_path: Path) -> None:
    path = write_analysis_md(tmp_path, PROBLEM, "## Approach\nHash map.", "ollama", "qwen2.5")
    content = path.read_text(encoding="utf-8")
    assert path.name == "analysis.md"
    assert content.startswith("# 1. Two Sum - Solution Analysis")
    assert "Hash map." in content
    # MIT requires the notice be retained - it ships in every generated file.
    assert "leetcode-helper" in content
    assert "Aman Attar" in content
    assert "MIT" in content


def test_write_analysis_md_never_touches_notes(tmp_path: Path) -> None:
    from leetvault.git_writer import ensure_notes

    notes = ensure_notes(tmp_path, PROBLEM)
    notes.write_text("my own private notes", encoding="utf-8")
    write_analysis_md(tmp_path, PROBLEM, "## Approach\nHash map.", "ollama", "m")
    assert notes.read_text(encoding="utf-8") == "my own private notes"


def test_analysis_md_path_matches_writer(tmp_path: Path) -> None:
    expected = analysis_md_path(tmp_path, PROBLEM.title_slug)
    actual = write_analysis_md(tmp_path, PROBLEM, "body", "ollama", "m")
    assert actual == expected


def test_ai_disabled_by_default() -> None:
    store = ConfigStore()
    assert store.get("ai_notes_enabled") is False
    assert store.get("ai_provider") is None


def test_ai_setup_reports_no_backends() -> None:
    console = Console(record=True, width=200)
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(side_effect=ConnectionError)
        run_ai_setup(console, disable=False, set_key=False, show=False)
    output = console.export_text()
    assert "No AI backend detected" in output
    # and it tells the user how to get each one
    assert "ollama.com" in output
    assert "claude-code" in output


def test_ai_setup_disable_writes_config() -> None:
    ConfigStore().set("ai_notes_enabled", True)
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=True, set_key=False, show=False)
    assert ConfigStore().get("ai_notes_enabled") is False
    assert "disabled" in console.export_text()


def test_ai_setup_show_prints_settings() -> None:
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=False, set_key=False, show=True)
    output = console.export_text()
    assert "Enabled" in output
    assert "Provider" in output


def test_ai_setup_set_key_stores_in_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    from leetvault import ai_setup, auth

    monkeypatch.setattr(ai_setup.typer, "prompt", lambda *a, **k: "sk-ant-test")
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=False, set_key=True, show=False)
    assert auth.load_anthropic_key() == "sk-ant-test"


def test_sync_skips_analysis_when_disabled(tmp_path: Path) -> None:
    """The whole feature must be inert until explicitly enabled."""
    from leetvault.db import make_engine, make_session_factory
    from leetvault.sync import _generate_ai_analysis

    factory = make_session_factory(make_engine(tmp_path / "db.sqlite"))
    console = Console(record=True, width=200)
    # No network mock registered: any provider call would raise, proving none is made.
    assert _generate_ai_analysis(console, factory, tmp_path) == 0


def test_sync_skips_analysis_when_provider_unset(tmp_path: Path) -> None:
    from leetvault.db import make_engine, make_session_factory
    from leetvault.sync import _generate_ai_analysis

    ConfigStore().set("ai_notes_enabled", True)  # enabled but no provider chosen
    factory = make_session_factory(make_engine(tmp_path / "db.sqlite"))
    console = Console(record=True, width=200)
    assert _generate_ai_analysis(console, factory, tmp_path) == 0


def test_metadata_json_untouched_by_analysis(tmp_path: Path) -> None:
    """analysis.md is a separate artifact; it must not rewrite metadata."""
    from leetvault.git_writer import write_latest_and_metadata

    _, meta_path = write_latest_and_metadata(
        tmp_path, PROBLEM, 1, "python3", "pass", 1000, "1 ms", "1 MB", None, None
    )
    before = json.loads(meta_path.read_text(encoding="utf-8"))
    write_analysis_md(tmp_path, PROBLEM, "body", "ollama", "m")
    assert json.loads(meta_path.read_text(encoding="utf-8")) == before
