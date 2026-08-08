"""Pluggable backends for generating solution analysis.

Deliberately provider-agnostic: leetvault is installed by people with very different setups -
some already pay for a Claude subscription, some will run a model locally, most have nothing
configured at all. Forcing one backend would make the feature unusable for most of them, so
each backend is optional and the feature stays off until one is both available and chosen.

Every provider is best-effort by contract: `generate` returns None rather than raising, so a
failing model never breaks a sync. It must still say *why* it failed - a silent None gives
the user a completed progress bar and no files, which is indistinguishable from the feature
not working at all. Failures are recorded on `last_error` for the caller to surface.
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
# This is analysis, not prose: the model is tracing real code and justifying complexity
# claims, where sampling variety buys nothing and invented detail costs everything.
_TEMPERATURE = 0.2
# A full analysis of a Hard problem runs past Groq's 3072-token default, which truncated
# mid-section and produced a file that looked complete enough to keep. Providers override
# this where their tier is tighter - `max_tokens` is *reserved* budget on metered APIs, so
# asking for more than the tier allows is rejected outright rather than merely capped.
_MAX_TOKENS = 16384
# Rough characters per token. Only used to keep a request inside a per-minute budget, where
# being approximately right and slightly conservative is what matters.
_CHARS_PER_TOKEN = 3.5


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
    # Output ceiling for one call. Overridden where a tier meters input+output together.
    max_output_tokens: int = _MAX_TOKENS
    # Total tokens (input + output) one request may reserve, or None when unmetered.
    tokens_per_request: int | None = None

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.default_model
        self.last_error: str | None = None

    @classmethod
    @abstractmethod
    def detect(cls) -> ProviderInfo | None:
        """Return info if this backend is usable on this machine, else None."""

    @abstractmethod
    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        """Return the analysis, or None if generation failed (see `last_error`).

        `system_prompt` lets a caller ask for part of the analysis instead of all of it,
        which is how the retry path narrows the request after a full one fails.
        """

    def _output_budget(self, prompt_chars: int, requested: int | None) -> int:
        """How many output tokens to reserve, kept inside the provider's own limit.

        On a metered API `max_tokens` is reserved up front and counted against the budget
        alongside the input, so an over-large ask is refused with a 413 rather than
        truncated - the request never runs at all.
        """
        budget = requested or self.max_output_tokens
        budget = min(budget, self.max_output_tokens)
        if self.tokens_per_request is not None:
            estimated_input = int(prompt_chars / _CHARS_PER_TOKEN)
            # Leave headroom: the estimate is approximate and the limit is hard.
            allowed = self.tokens_per_request - estimated_input - 512
            budget = min(budget, max(allowed, 512))
        return max(budget, 512)

    def _fail(self, exc: Exception) -> None:
        """Record why generation failed, preferring the API's own message.

        Providers return an error body that explains the real problem - a quota of zero, a
        retired model - while the raised exception says only "400" or "429". Digging the
        message out is the difference between a fixable report and a shrug.
        """
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                payload = exc.response.json()
            except Exception:  # noqa: BLE001 - error bodies are not always JSON
                payload = None
            message = ""
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    message = str(err.get("message") or "")
                elif isinstance(err, str):
                    message = err
            detail = f"HTTP {exc.response.status_code}"
            if message:
                detail += f": {message.strip().splitlines()[0]}"
        self.last_error = detail


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

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        budget = self._output_budget(len(system) + len(user_prompt), max_output_tokens)
        try:
            response = httpx.post(
                f"{_OLLAMA_HOST}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {"temperature": _TEMPERATURE, "num_predict": budget},
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
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

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        executable = self._executable()
        if executable is None:
            return None
        command = [executable, "-p", f"{system}\n\n---\n\n{user_prompt}"]
        if self.model:
            command += ["--model", self.model]
        try:
            result = subprocess.run(  # noqa: S603 - executable resolved via shutil.which
                command, capture_output=True, text=True, timeout=_TIMEOUT, check=False
            )
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
            return None
        if result.returncode != 0:
            stderr = (result.stderr or "").strip().splitlines()
            self.last_error = f"claude exited {result.returncode}" + (
                f": {stderr[-1]}" if stderr else ""
            )
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

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        budget = self._output_budget(len(system) + len(user_prompt), max_output_tokens)
        try:
            import anthropic

            from leetvault.auth import load_anthropic_key

            stored = load_anthropic_key()
            client = anthropic.Anthropic(api_key=stored) if stored else anthropic.Anthropic()
            message = client.messages.create(
                model=self.model,
                max_tokens=budget,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
            return None
        return "".join(b.text for b in message.content if b.type == "text").strip() or None


class GeminiProvider(AIProvider):
    """Google Gemini's free tier - cloud inference, no local hardware, free API key.

    The practical answer for users with neither the RAM for a local model nor a Claude
    subscription.
    """

    name = "gemini"
    default_model = "gemini-flash-latest"
    key_env = "GEMINI_API_KEY"

    @classmethod
    def _key(cls) -> str | None:
        from leetvault.auth import load_provider_key

        return os.environ.get(cls.key_env) or load_provider_key(cls.name)

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        if not cls._key():
            return None
        return ProviderInfo(
            name=cls.name,
            display="Google Gemini",
            detail="API key found",
            cost="free tier (no local hardware needed)",
        )

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        budget = self._output_budget(len(system) + len(user_prompt), max_output_tokens)
        key = self._key()
        if not key:
            return None
        try:
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent",
                params={"key": key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": _TEMPERATURE,
                        "maxOutputTokens": budget,
                    },
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            candidates = response.json().get("candidates") or []
            parts = candidates[0]["content"]["parts"] if candidates else []
            text = "".join(p.get("text", "") for p in parts)
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
            return None
        return text.strip() or None


class GroqProvider(AIProvider):
    """Groq's free tier - OpenAI-compatible, very fast, free API key, no local hardware."""

    name = "groq"
    default_model = "llama-3.3-70b-versatile"
    key_env = "GROQ_API_KEY"
    # The free tier meters input and output together at 8000 tokens/minute, and rejects a
    # request whose reserved total exceeds it - a 16384-token ask was refused outright with
    # "Requested 19255".
    tokens_per_request = 8000
    max_output_tokens = 6000

    @classmethod
    def _key(cls) -> str | None:
        from leetvault.auth import load_provider_key

        return os.environ.get(cls.key_env) or load_provider_key(cls.name)

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        if not cls._key():
            return None
        return ProviderInfo(
            name=cls.name,
            display="Groq",
            detail="API key found",
            cost="free tier (no local hardware needed)",
        )

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        budget = self._output_budget(len(system) + len(user_prompt), max_output_tokens)
        key = self._key()
        if not key:
            return None
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": _TEMPERATURE,
                    "max_tokens": budget,
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            choices = response.json().get("choices") or []
            content = choices[0]["message"]["content"] if choices else None
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
            return None
        return content.strip() if content else None


class NvidiaProvider(AIProvider):
    """NVIDIA NIM's free tier - OpenAI-compatible, hosts very large open models.

    Worth having alongside Gemini and Groq because the daily quotas are separate, so a
    user who exhausts one can finish a backfill on another.
    """

    name = "nvidia"
    default_model = "nvidia/nemotron-3-ultra-550b-a55b"
    key_env = "NVIDIA_API_KEY"
    # Reasoning models spend tokens thinking before they answer, and a full analysis is
    # long, so the ceiling has to cover both or the response is truncated mid-section. But
    # tokens are wall-clock here: at 16384 this 550B model ran past a ten-minute per-call
    # timeout on a Hard problem, and an analysis that never arrives is worth less than a
    # slightly shallower one that does.
    _REASONING_BUDGET = 6144
    max_output_tokens = 16384

    @classmethod
    def _key(cls) -> str | None:
        from leetvault.auth import load_provider_key

        return os.environ.get(cls.key_env) or load_provider_key(cls.name)

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        if not cls._key():
            return None
        return ProviderInfo(
            name=cls.name,
            display="NVIDIA NIM",
            detail="API key found",
            cost="free tier (no local hardware needed)",
        )

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        system = system_prompt or SYSTEM_PROMPT
        budget = self._output_budget(len(system) + len(user_prompt), max_output_tokens)
        key = self._key()
        if not key:
            return None
        try:
            response = httpx.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": _TEMPERATURE,
                    "top_p": 0.95,
                    "max_tokens": budget,
                    # Thinking is worth its cost here: the analysis has to trace real code
                    # and justify complexity claims, not recall a familiar answer.
                    "chat_template_kwargs": {"enable_thinking": True},
                    "reasoning_budget": self._REASONING_BUDGET,
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            choices = response.json().get("choices") or []
            # Non-streaming keeps this consistent with the other providers - there is no
            # partial output to display anyway. `reasoning_content` is returned as its own
            # field rather than inline, so the chain of thought never reaches the file.
            content = choices[0]["message"].get("content") if choices else None
        except Exception as exc:  # noqa: BLE001 - best-effort, but recorded
            self._fail(exc)
            return None
        return content.strip() if content else None


_PROVIDERS: dict[str, type[AIProvider]] = {
    OllamaProvider.name: OllamaProvider,
    ClaudeCliProvider.name: ClaudeCliProvider,
    GeminiProvider.name: GeminiProvider,
    GroqProvider.name: GroqProvider,
    NvidiaProvider.name: NvidiaProvider,
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
