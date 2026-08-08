"""Build one analysis out of however many model calls it takes.

One request for the whole analysis is right when it works: it is the cheapest, and the model
sees every section at once so the parts agree with each other. It stops working for two
reasons, both observed rather than imagined. A long analysis of a Hard problem runs past a
provider's output cap and comes back truncated mid-sentence. And free tiers meter tokens per
minute - Groq allows 8000 - so a single large request can exhaust the budget in one shot.

So: ask once, and only if that fails ask again in halves, then in pairs, then section by
section. Each narrowing costs more calls but makes each one smaller, and a model writing one
section has its whole attention on that section. Splitting is a fallback rather than the
default because it is slower and because sections written separately can repeat each other -
there is no reason to pay either cost when a single call already produced a good analysis.

Between calls there is a pause. Free tiers are the normal case here, and hammering one is
how a backfill turns into a wall of 429s.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from leetvault.ai.prompt import SECTION_NAMES, build_system_prompt
from leetvault.ai.providers import AIProvider

# How the sections are grouped at each attempt: everything, then halves, then pairs, then
# one at a time. Escalation stops as soon as an attempt yields a complete analysis.
_SPLITS: tuple[int, ...] = (1, 2, 4, 8)

# Seconds to wait between calls, per provider. Cloud free tiers meter by the minute, so the
# pause is what keeps a multi-call analysis inside the budget rather than tripping a 429.
# A local model has no quota and no reason to wait.
_DELAYS: dict[str, float] = {
    "ollama": 0.0,
    "claude-cli": 2.0,
    "gemini": 4.0,
    "groq": 12.0,
    "nvidia": 3.0,
    "anthropic": 1.0,
}
_DEFAULT_DELAY = 5.0

# Ceiling on the time one problem may consume, across every attempt. Escalation multiplies
# calls, and a large reasoning model can spend ten minutes on a single Hard problem, so the
# worst case without a ceiling is hours on one file with no way to tell whether it is
# working or wedged. Stopping and saying so is more useful than either.
_PROBLEM_BUDGET_SECONDS = 900.0


def delay_for(provider_name: str) -> float:
    return _DELAYS.get(provider_name, _DEFAULT_DELAY)


def _chunk(names: Sequence[str], parts: int) -> list[list[str]]:
    """Split sections into `parts` contiguous groups, keeping their order."""
    if parts <= 1:
        return [list(names)]
    size = max(1, -(-len(names) // parts))  # ceil, so no group is empty
    return [list(names[i : i + size]) for i in range(0, len(names), size)]


# Dash characters models substitute for a plain hyphen. gpt-oss-120b returned
# "Line‑by‑Line Explanation" with U+2011 non-breaking hyphens, which an exact comparison
# rejects - and a heading judged missing costs a whole extra round of calls to "fix".
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})


def _normalise(heading: str) -> str:
    """Compare headings by what they say, not by which dash or capitals a model chose."""
    return " ".join(heading.translate(_DASHES).lower().replace("*", "").split()).strip(" :#")


def missing_sections(body: str, expected: Sequence[str] = SECTION_NAMES) -> list[str]:
    present = {_normalise(line[3:]) for line in body.splitlines() if line.startswith("## ")}
    return [name for name in expected if _normalise(name) not in present]


def is_complete(body: str, expected: Sequence[str] = SECTION_NAMES) -> bool:
    """Whether a response covers everything it was asked for.

    Presence of the final section carries the weight: a reply cut off by a token limit still
    has its early headings, so counting them passes a document that stops mid-sentence.
    """
    if not body.strip():
        return False
    return not missing_sections(body, expected)


@dataclass
class ComposeResult:
    body: str | None
    calls: int = 0
    split: int = 0
    error: str | None = None
    missing: list[str] = field(default_factory=list)


def compose_analysis(
    provider: AIProvider,
    user_prompt: str,
    *,
    delay: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_attempt: Callable[[int, int], None] | None = None,
    budget_seconds: float = _PROBLEM_BUDGET_SECONDS,
    now: Callable[[], float] = time.monotonic,
) -> ComposeResult:
    """Produce a full analysis, narrowing the request until it succeeds.

    Returns whatever was achieved; the caller decides whether a partial result is worth
    keeping. Nothing here writes to disk - a half-finished analysis must never become a
    file, because the file's existence is what makes later runs skip the problem.
    """
    pause = delay_for(provider.name) if delay is None else delay
    calls = 0
    last_error: str | None = None
    started = now()

    def out_of_time() -> bool:
        return budget_seconds > 0 and (now() - started) >= budget_seconds

    for split in _SPLITS:
        if out_of_time():
            last_error = (
                f"gave up after {budget_seconds:.0f}s and {calls} call(s) - the model is "
                "too slow for this problem; try a faster one"
            )
            break
        groups = _chunk(SECTION_NAMES, split)
        if on_attempt is not None:
            on_attempt(split, len(groups))

        collected: list[str] = []
        ok = True
        for index, group in enumerate(groups):
            if out_of_time():
                ok = False
                last_error = (
                    f"gave up after {budget_seconds:.0f}s and {calls} call(s) - the model is "
                    "too slow for this problem; try a faster one"
                )
                break
            if calls and pause:
                sleep(pause)
            system = build_system_prompt(group if split > 1 else None)
            calls += 1
            body = provider.generate(user_prompt, system)
            if not body or not is_complete(body, group):
                last_error = provider.last_error or (
                    f"incomplete response for {', '.join(group)}"
                    if body
                    else "no response from the model"
                )
                ok = False
                # A failure in the first group means the whole split is the wrong size;
                # trying the remaining groups only spends quota to learn the same thing.
                if index == 0:
                    break
                continue
            collected.append(body.strip())

        if ok and collected:
            joined = "\n\n".join(collected)
            if is_complete(joined):
                return ComposeResult(body=joined, calls=calls, split=split)

    return ComposeResult(
        body=None,
        calls=calls,
        split=_SPLITS[-1],
        error=last_error,
        missing=list(SECTION_NAMES),
    )
