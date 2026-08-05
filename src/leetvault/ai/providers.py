"""Pluggable backends for generating solution analysis.

Deliberately provider-agnostic: leetvault is installed by people with very different setups -
some already pay for a Claude subscription, some will run a model locally, most have nothing
configured at all. Forcing one backend would make the feature unusable for most of them, so
each backend is optional and the feature stays off until one is both available and chosen.

Every provider is best-effort by contract: `generate` returns None rather than raising, so a
failing model never breaks a sync.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from leetvault.ai.prompt import SYSTEM_PROMPT

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_TIMEOUT = 600.0  # local CPU inference on a 7B model is slow but finite


@dataclass
class ProviderInfo:
    name: str
    display: str
    detail: str
    cost: str


class AIProvider(ABC):
    """One way of turning a prompt into an analysis."""

    name: str
    default_model: str

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.default_model

    @classmethod
    @abstractmethod
    def detect(cls) -> ProviderInfo | None:
        """Return info if this backend is usable on this machine, else None."""

    @abstractmethod
    def generate(self, user_prompt: str) -> str | None:
        """Return the analysis, or None if generation failed."""


class OllamaProvider(AIProvider):
    """A model running locally via Ollama - free, unlimited, offline, no account."""

    name = "ollama"
    default_model = "qwen2.5-coder:7b"

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        try:
            response = httpx.get(f"{_OLLAMA_HOST}/api/tags", timeout=2.0)
            response.raise_for_status()
            models = [m["name"] for m in response.json().get("models", [])]
        except Exception:  # noqa: BLE001 - detection must never raise
            return None
        return ProviderInfo(
            name=cls.name,
            display="Ollama (local)",
            detail=f"{len(models)} model(s) installed" if models else "no models pulled yet",
            cost="free, unlimited",
        )

    def generate(self, user_prompt: str) -> str | None:
        try:
            response = httpx.post(
                f"{_OLLAMA_HOST}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
        except Exception:  # noqa: BLE001 - best-effort
            return None
        return content.strip() if content else None


class ClaudeCliProvider(AIProvider):
    """The Claude Code CLI in non-interactive mode.

    Uses whatever credentials the CLI already holds, so a user with a Claude subscription
    pays nothing extra. Subject to that subscription's own rate limits.
    """

    name = "claude-cli"
    default_model = ""  # let the CLI pick; leetvault does not override the user's default

    @classmethod
    def _executable(cls) -> str | None:
        return shutil.which("claude")

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        executable = cls._executable()
        if executable is None:
            return None
        return ProviderInfo(
            name=cls.name,
            display="Claude Code CLI",
            detail=f"found at {executable}",
            cost="free with an existing Claude subscription",
        )

    def generate(self, user_prompt: str) -> str | None:
        executable = self._executable()
        if executable is None:
            return None
        command = [executable, "-p", f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"]
        if self.model:
            command += ["--model", self.model]
        try:
            result = subprocess.run(  # noqa: S603 - executable resolved via shutil.which
                command, capture_output=True, text=True, timeout=_TIMEOUT, check=False
            )
        except Exception:  # noqa: BLE001 - best-effort
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None


class AnthropicProvider(AIProvider):
    """Anthropic's API directly. Highest quality, but billed per token."""

    name = "anthropic"
    default_model = "claude-opus-5"

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            from leetvault.auth import load_anthropic_key

            if load_anthropic_key() is None:
                return None
        return ProviderInfo(
            name=cls.name,
            display="Anthropic API",
            detail="credentials found",
            cost="paid, billed per token",
        )

    def generate(self, user_prompt: str) -> str | None:
        try:
            import anthropic

            from leetvault.auth import load_anthropic_key

            stored = load_anthropic_key()
            client = anthropic.Anthropic(api_key=stored) if stored else anthropic.Anthropic()
            message = client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception:  # noqa: BLE001 - best-effort
            return None
        return "".join(b.text for b in message.content if b.type == "text").strip() or None


_PROVIDERS: dict[str, type[AIProvider]] = {
    OllamaProvider.name: OllamaProvider,
    ClaudeCliProvider.name: ClaudeCliProvider,
    AnthropicProvider.name: AnthropicProvider,
}


def available_providers() -> list[ProviderInfo]:
    """Every backend usable on this machine right now."""
    found = []
    for cls in _PROVIDERS.values():
        info = cls.detect()
        if info is not None:
            found.append(info)
    return found


def get_provider(name: str, model: str | None = None) -> AIProvider | None:
    cls = _PROVIDERS.get(name)
    return cls(model) if cls else None


def provider_names() -> list[str]:
    return list(_PROVIDERS)


def parse_json_safe(raw: str) -> dict[str, object]:
    """Small helper kept here so providers don't each re-import json."""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
