from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response
from rich.console import Console
from sqlalchemy.orm import Session, sessionmaker

from leetvault.ai import build_user_prompt, get_provider, provider_names
from leetvault.ai.providers import (
    AnthropicProvider,
    ClaudeCliProvider,
    GeminiProvider,
    GroqProvider,
    NvidiaProvider,
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
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ClaudeCliProvider, "_executable", classmethod(lambda cls: None))


def test_provider_registry_exposes_all_backends() -> None:
    assert set(provider_names()) == {
        "ollama",
        "claude-cli",
        "gemini",
        "groq",
        "nvidia",
        "anthropic",
    }


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


def test_write_analysis_md_renders_body_and_provider(tmp_path: Path) -> None:
    path = write_analysis_md(tmp_path, PROBLEM, "## Approach\nHash map.", "ollama", "qwen2.5")
    content = path.read_text(encoding="utf-8")
    assert path.name == "analysis.md"
    assert content.startswith("# 1. Two Sum - Solution Analysis")
    assert "Hash map." in content
    assert "ollama" in content and "qwen2.5" in content


def test_generated_files_name_only_the_model_that_wrote_them(tmp_path: Path) -> None:
    """The footer is provenance for the analysis, not a credit line - it says which model
    produced the text and nothing else."""
    content = write_analysis_md(
        tmp_path, PROBLEM, "## Approach\nHash map.", "ollama", "qwen2.5"
    ).read_text(encoding="utf-8")
    footer = content.rsplit("---", 1)[-1].strip()
    assert footer == "_Generated by leetvault using ollama (qwen2.5)_"


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
        run_ai_setup(console, disable=False, set_key=None, show=False)
    output = console.export_text()
    assert "No AI backend detected" in output
    # and it tells the user how to get each one
    assert "ollama.com" in output
    assert "claude-code" in output


def test_ai_setup_disable_writes_config() -> None:
    ConfigStore().set("ai_notes_enabled", True)
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=True, set_key=None, show=False)
    assert ConfigStore().get("ai_notes_enabled") is False
    assert "disabled" in console.export_text()


def test_ai_setup_show_prints_settings() -> None:
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=False, set_key=None, show=True)
    output = console.export_text()
    assert "Enabled" in output
    assert "Provider" in output


def test_ai_setup_set_key_stores_in_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    from leetvault import ai_setup, auth

    monkeypatch.setattr(ai_setup.typer, "prompt", lambda *a, **k: "sk-ant-test")
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=False, set_key="anthropic", show=False)
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


def _seeded_factory(tmp_path: Path, count: int) -> sessionmaker[Session]:
    from leetvault.db import make_engine, make_session_factory, session_scope
    from leetvault.models import Problem

    factory = make_session_factory(make_engine(tmp_path / "db.sqlite"))
    with session_scope(factory) as session:
        for i in range(1, count + 1):
            session.add(
                Problem(
                    question_id=i,
                    frontend_id=i,
                    title=f"Problem {i}",
                    title_slug=f"problem-{i}",
                    difficulty="Easy",
                    paid_only=False,
                    url=f"https://leetcode.com/problems/problem-{i}/",
                )
            )
    return factory


def test_analysis_backfill_says_it_is_a_backfill(tmp_path: Path) -> None:
    """A sync reporting "1 new submission" then "50 problem(s)" reads like a bug. The
    count covers everything still missing an analysis, so the message must say so."""
    from leetvault.sync import _generate_ai_analysis

    store = ConfigStore()
    store.set("ai_notes_enabled", True)
    store.set("ai_provider", "gemini")
    factory = _seeded_factory(tmp_path, 50)
    console = Console(record=True, width=200)
    with respx.mock:
        respx.post(url__regex=r".*generativelanguage.*").mock(return_value=Response(500, json={}))
        _generate_ai_analysis(console, factory, tmp_path)
    output = console.export_text()
    assert "all 50 problem(s) in your history" in output
    assert "one-time catch-up" in output


def test_analysis_message_distinguishes_partial_backfill(tmp_path: Path) -> None:
    from leetvault.git_writer import write_analysis_md
    from leetvault.sync import _generate_ai_analysis

    store = ConfigStore()
    store.set("ai_notes_enabled", True)
    store.set("ai_provider", "gemini")
    factory = _seeded_factory(tmp_path, 50)
    for i in range(1, 48):  # 47 already done, 3 outstanding
        meta = ProblemMeta(i, i, f"Problem {i}", f"problem-{i}", "Easy", False, "u")
        write_analysis_md(tmp_path, meta, "body", "gemini", "m")
    console = Console(record=True, width=200)
    with respx.mock:
        respx.post(url__regex=r".*generativelanguage.*").mock(return_value=Response(500, json={}))
        _generate_ai_analysis(console, factory, tmp_path)
    output = console.export_text()
    assert "3 of 50 problem(s)" in output
    assert "one-time catch-up" not in output


def test_metadata_json_untouched_by_analysis(tmp_path: Path) -> None:
    """analysis.md is a separate artifact; it must not rewrite metadata."""
    from leetvault.git_writer import write_latest_and_metadata

    _, meta_path = write_latest_and_metadata(
        tmp_path, PROBLEM, 1, "python3", "pass", 1000, "1 ms", "1 MB", None, None
    )
    before = json.loads(meta_path.read_text(encoding="utf-8"))
    write_analysis_md(tmp_path, PROBLEM, "body", "ollama", "m")
    assert json.loads(meta_path.read_text(encoding="utf-8")) == before


# --- Gemini and Groq: the "no RAM, no Claude subscription" path -------------------


def test_gemini_not_detected_without_key() -> None:
    assert GeminiProvider.detect() is None


def test_gemini_detected_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "free-key")
    info = GeminiProvider.detect()
    assert info is not None
    assert "free" in info.cost
    assert "no local hardware" in info.cost


def test_gemini_detected_from_keyring() -> None:
    from leetvault.auth import store_provider_key

    store_provider_key("gemini", "stored-key")
    assert GeminiProvider.detect() is not None


@respx.mock
def test_gemini_generate_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "free-key")
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(
        return_value=Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "## Approach Hash map."}]}}]},
        )
    )
    assert GeminiProvider().generate("analyse") == "## Approach Hash map."


@respx.mock
def test_gemini_generate_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "free-key")
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(return_value=Response(429, json={}))
    assert GeminiProvider().generate("analyse") is None


def test_gemini_generate_without_key_returns_none() -> None:
    assert GeminiProvider().generate("analyse") is None


def test_groq_not_detected_without_key() -> None:
    assert GroqProvider.detect() is None


def test_groq_detected_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "free-key")
    info = GroqProvider.detect()
    assert info is not None
    assert "free" in info.cost


@respx.mock
def test_groq_generate_parses_openai_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "free-key")
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "## Approach Two pointers."}}]}
        )
    )
    assert GroqProvider().generate("analyse") == "## Approach Two pointers."


@respx.mock
def test_groq_sends_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "free-key")
    route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    GroqProvider().generate("analyse")
    assert route.calls.last.request.headers["Authorization"] == "Bearer free-key"


def test_provider_keys_are_isolated_per_provider() -> None:
    """A Gemini key must never be handed to Groq (or vice versa)."""
    from leetvault.auth import load_provider_key, store_provider_key

    store_provider_key("gemini", "gemini-key")
    store_provider_key("groq", "groq-key")
    assert load_provider_key("gemini") == "gemini-key"
    assert load_provider_key("groq") == "groq-key"
    assert load_provider_key("anthropic") is None


def test_anthropic_key_slot_is_backwards_compatible() -> None:
    """An Anthropic key stored before multi-provider support must still load."""
    from leetvault.auth import load_provider_key, store_anthropic_key

    store_anthropic_key("legacy-key")
    assert load_provider_key("anthropic") == "legacy-key"


def test_set_key_rejects_a_provider_that_takes_no_key() -> None:
    import typer

    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit):
        run_ai_setup(console, disable=False, set_key="ollama", show=False)
    assert "does not take an API key" in console.export_text()


def test_set_key_stores_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from leetvault import ai_setup
    from leetvault.auth import load_provider_key

    monkeypatch.setattr(ai_setup.typer, "prompt", lambda *a, **k: "gk-123")
    console = Console(record=True, width=200)
    run_ai_setup(console, disable=False, set_key="gemini", show=False)
    assert load_provider_key("gemini") == "gk-123"


def test_setup_lists_free_cloud_options_when_nothing_installed() -> None:
    """A user with no RAM and no Claude subscription must still be told what to do."""
    console = Console(record=True, width=200)
    with respx.mock:
        respx.get("http://localhost:11434/api/tags").mock(side_effect=ConnectionError)
        run_ai_setup(console, disable=False, set_key=None, show=False)
    output = console.export_text()
    assert "aistudio.google.com" in output
    assert "console.groq.com" in output


def test_provider_records_api_error_message() -> None:
    """A silent None gave the user a full progress bar and no files. The API's own message
    explains the real cause - a zero free-tier quota, a retired model - so keep it."""
    provider = GeminiProvider()
    response = httpx.Response(
        429,
        json={"error": {"message": "Quota exceeded for metric: ...\nlimit: 0"}},
        request=httpx.Request("POST", "https://example.invalid"),
    )
    provider._fail(httpx.HTTPStatusError("429", request=response.request, response=response))
    assert provider.last_error is not None
    assert provider.last_error.startswith("HTTP 429: Quota exceeded")


def test_provider_fail_survives_non_json_body() -> None:
    provider = GeminiProvider()
    response = httpx.Response(
        502, text="<html>bad gateway</html>", request=httpx.Request("POST", "https://x.invalid")
    )
    provider._fail(httpx.HTTPStatusError("502", request=response.request, response=response))
    assert provider.last_error == "HTTP 502"


def test_gemini_default_model_is_an_alias() -> None:
    """Pinned Gemini names get retired or dropped to a zero free-tier quota; the alias
    tracks whatever Google actually serves."""
    assert GeminiProvider.default_model == "gemini-flash-latest"


def test_nvidia_not_detected_without_key() -> None:
    assert NvidiaProvider.detect() is None


def test_nvidia_detected_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    info = NvidiaProvider.detect()
    assert info is not None
    assert info.name == "nvidia"
    assert "free tier" in info.cost


@respx.mock
def test_nvidia_generate_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    route = respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "## Approach\nHash map.\n"}}]}
        )
    )
    assert NvidiaProvider().generate("analyse this") == "## Approach\nHash map."
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert sent["chat_template_kwargs"] == {"enable_thinking": True}
    assert sent["reasoning_budget"] > 0
    assert route.calls[0].request.headers["authorization"] == "Bearer nvapi-test"


@respx.mock
def test_nvidia_never_writes_the_chain_of_thought(monkeypatch: pytest.MonkeyPatch) -> None:
    """`reasoning_content` is a sibling of `content`, not part of it. Only the answer is
    the analysis - the thinking must not reach the user's repo."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "## Approach\nHash map.",
                            "reasoning_content": "Let me think about this step by step...",
                        }
                    }
                ]
            },
        )
    )
    body = NvidiaProvider().generate("analyse this")
    assert body == "## Approach\nHash map."
    assert "step by step" not in (body or "")


@respx.mock
def test_nvidia_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(401, json={"error": {"message": "invalid key"}})
    )
    provider = NvidiaProvider()
    assert provider.generate("analyse this") is None
    assert provider.last_error == "HTTP 401: invalid key"


def test_stub_responses_are_rejected_not_written() -> None:
    """A short or truncated reply must not be written: analysis.md existing is what makes
    later runs skip the problem, so junk would be permanent."""
    from leetvault.sync import _looks_like_analysis

    assert not _looks_like_analysis("I cannot help with that.")
    assert not _looks_like_analysis("## Problem Understanding\nIt asks for two numbers.")
    assert _looks_like_analysis(
        "## Problem Understanding\nx\n## Approach\ny\n## Algorithm\nz\n## Complexity\nw"
    )


def test_prompt_asks_for_the_formats_that_make_analysis_useful() -> None:
    """Naming the exact shape per section is most of the difference between a useful
    analysis and filler, so the instructions must survive future prompt edits."""
    from leetvault.ai.prompt import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "brute-force" in lowered  # contrast is where the insight lives
    assert "verbatim" in lowered  # quote the user's real lines
    assert "sliding window" in lowered and "union-find" in lowered  # pattern vocabulary
    assert "| step |" in lowered  # dry-run table shape
    assert "what n" in lowered  # complexity must define its variables
    for section in (
        "## Problem Understanding",
        "## Approach",
        "## Algorithm",
        "## Line-by-Line Explanation",
        "## Dry Run",
        "## Complexity",
        "## Edge Cases",
        "## Possible Improvements",
    ):
        assert section in SYSTEM_PROMPT
