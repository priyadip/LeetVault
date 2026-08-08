from __future__ import annotations

from leetvault.ai.composer import _chunk, compose_analysis, delay_for, is_complete
from leetvault.ai.prompt import SECTION_NAMES, build_system_prompt
from leetvault.ai.providers import AIProvider, ProviderInfo


def _body(names: list[str] | tuple[str, ...]) -> str:
    return "\n\n".join(f"## {name}\nsomething about {name}." for name in names)


class FakeProvider(AIProvider):
    """Records what it was asked for and replies however the test dictates."""

    name = "fake"
    default_model = "fake-1"

    def __init__(self, responder) -> None:  # type: ignore[no-untyped-def]
        super().__init__(None)
        self.responder = responder
        self.calls: list[list[str]] = []
        self.budgets: list[int | None] = []

    @classmethod
    def detect(cls) -> ProviderInfo | None:
        return None

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str | None:
        self.calls.append(_wanted(system_prompt))
        self.budgets.append(max_output_tokens)
        return self.responder(len(self.calls), system_prompt)


def _wanted(system_prompt: str | None) -> list[str]:
    """Which sections a system prompt asks for - the composer always sends one explicitly."""
    if system_prompt is None:
        return list(SECTION_NAMES)
    return [name for name in SECTION_NAMES if f"## {name}\n" in system_prompt]


def _no_sleep(_seconds: float) -> None:
    return None


def test_chunk_keeps_order_and_covers_everything() -> None:
    for parts in (1, 2, 4, 8):
        groups = _chunk(SECTION_NAMES, parts)
        assert [n for g in groups for n in g] == list(SECTION_NAMES)
        assert all(groups)


def test_is_complete_requires_the_last_section() -> None:
    assert is_complete(_body(SECTION_NAMES))
    truncated = _body(SECTION_NAMES[:4])
    assert truncated.count("## ") == 4
    assert not is_complete(truncated)
    assert not is_complete("")


def test_single_call_when_the_first_response_is_good() -> None:
    """Splitting is slower and lets sections repeat each other. A model that answers in one
    call must not be asked again."""
    provider = FakeProvider(lambda _n, _s: _body(SECTION_NAMES))
    result = compose_analysis(provider, "prompt", sleep=_no_sleep)
    assert result.calls == 1
    assert result.split == 1
    assert provider.calls == [list(SECTION_NAMES)]
    assert is_complete(result.body or "")


def test_escalates_to_halves_when_one_call_is_truncated() -> None:
    """The exact failure seen in practice: a Hard problem cut off at the provider's output
    cap, with the early headings intact."""

    def responder(n: int, system: str | None) -> str:
        wanted = _wanted(system)
        if len(wanted) == len(SECTION_NAMES):
            return _body(SECTION_NAMES[:4])  # truncated at the provider's output cap
        return _body(wanted)

    provider = FakeProvider(responder)
    result = compose_analysis(provider, "prompt", sleep=_no_sleep)
    assert result.split == 2
    assert result.calls == 3  # one failed full call, then two halves
    assert is_complete(result.body or "")
    for name in SECTION_NAMES:
        assert f"## {name}" in (result.body or "")


def test_escalates_all_the_way_to_one_call_per_section() -> None:
    def responder(_n: int, system: str | None) -> str | None:
        wanted = _wanted(system)
        if len(wanted) > 1:
            return _body(wanted[:1])  # only ever finishes the first of a group
        return _body(wanted)

    provider = FakeProvider(responder)
    result = compose_analysis(provider, "prompt", sleep=_no_sleep)
    assert result.split == 8
    assert is_complete(result.body or "")
    assert (result.body or "").count("## ") == len(SECTION_NAMES)


def test_gives_up_and_reports_rather_than_returning_half_an_analysis() -> None:
    """A partial analysis must never reach disk: the file existing is what makes later runs
    skip the problem, so an incomplete one would be permanent."""
    provider = FakeProvider(lambda _n, _s: None)
    result = compose_analysis(provider, "prompt", sleep=_no_sleep)
    assert result.body is None
    assert result.error


def test_first_group_failure_abandons_the_split_immediately() -> None:
    """If the first group of a split fails, the split size is wrong. Trying the rest only
    spends a metered quota to learn the same thing."""
    provider = FakeProvider(lambda _n, _s: None)
    compose_analysis(provider, "prompt", sleep=_no_sleep)
    # 1 (full) + 1 (first half) + 1 (first quarter) + 1 (first section) = 4, not 1+2+4+8.
    assert len(provider.calls) == 4


def test_pauses_between_calls_but_not_before_the_first() -> None:
    """Free tiers meter per minute, so the pause is what keeps a split analysis inside the
    budget - but waiting before a single call would only slow every sync down."""
    slept: list[float] = []

    def responder(_n: int, system: str | None) -> str:
        wanted = _wanted(system)
        if len(wanted) == len(SECTION_NAMES):
            return _body(SECTION_NAMES[:2])
        return _body(wanted)

    provider = FakeProvider(responder)
    compose_analysis(provider, "prompt", delay=7.0, sleep=slept.append)
    assert slept and all(s == 7.0 for s in slept)
    assert len(slept) == 2  # three calls, two gaps


def test_no_pause_at_all_on_a_single_successful_call() -> None:
    slept: list[float] = []
    provider = FakeProvider(lambda _n, _s: _body(SECTION_NAMES))
    compose_analysis(provider, "prompt", delay=9.0, sleep=slept.append)
    assert slept == []


def test_subset_prompt_asks_for_only_its_sections() -> None:
    system = build_system_prompt(["Complexity", "Edge Cases"])
    assert "Produce ONLY" in system
    assert "## Complexity" in system
    assert "## Dry Run" not in system
    # Same prohibitions as the full prompt, so a section written on a retry reads the same.
    assert "Never fabricate" in system


def test_delay_is_longest_for_the_tightest_free_tier() -> None:
    """Groq's free tier meters 8000 tokens/minute - the one that actually 429'd in testing.
    A local model has no quota and should never wait."""
    assert delay_for("ollama") == 0.0
    assert delay_for("groq") > delay_for("nvidia")
    assert delay_for("unknown-provider") > 0


def test_gives_up_when_the_time_budget_runs_out() -> None:
    """Escalation multiplies calls, and a large reasoning model can spend ten minutes on one
    Hard problem. Without a ceiling the worst case is hours on a single file."""
    clock = iter([0.0, 0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0])
    provider = FakeProvider(lambda _n, _s: None)
    result = compose_analysis(
        provider,
        "prompt",
        sleep=_no_sleep,
        budget_seconds=250.0,
        now=lambda: next(clock),
    )
    assert result.body is None
    assert "gave up after" in (result.error or "")
    # Stopped early rather than working through every split.
    assert len(provider.calls) < 4


def test_budget_does_not_interrupt_a_run_that_succeeds() -> None:
    provider = FakeProvider(lambda _n, _s: _body(SECTION_NAMES))
    result = compose_analysis(
        provider, "prompt", sleep=_no_sleep, budget_seconds=1.0, now=lambda: 0.0
    )
    assert result.body is not None
    assert result.calls == 1


def test_attempts_are_announced_so_a_slow_run_is_legible() -> None:
    """An 11-minute progress bar with no detail is indistinguishable from a hang."""
    seen: list[tuple[int, int]] = []

    def responder(_n: int, system: str | None) -> str:
        wanted = _wanted(system)
        if len(wanted) == len(SECTION_NAMES):
            return _body(SECTION_NAMES[:3])
        return _body(wanted)

    compose_analysis(
        FakeProvider(responder),
        "prompt",
        sleep=_no_sleep,
        on_attempt=lambda split, groups: seen.append((split, groups)),
    )
    assert seen[0] == (1, 1)
    assert (2, 2) in seen


def test_the_ask_shrinks_as_the_split_narrows() -> None:
    """Splitting only helps a metered API if the request shrinks with it. Asking for one
    section while still reserving a whole analysis's worth of output is the same size
    request, and Groq refused exactly that with "Requested 19255" against an 8000 limit."""

    def responder(_n: int, system: str | None) -> str | None:
        wanted = _wanted(system)
        return _body(wanted) if len(wanted) == 1 else None

    provider = FakeProvider(responder)
    compose_analysis(provider, "prompt", sleep=_no_sleep)
    budgets = [b for b in provider.budgets if b is not None]
    assert budgets[0] > budgets[-1]
    assert budgets[-1] < budgets[0] / 4  # one section asks for a fraction of the whole


def test_provider_clamps_an_over_large_ask_to_its_tier() -> None:
    """max_tokens is reserved budget on a metered API, so an over-large ask is refused
    outright rather than truncated - the request never runs."""
    from leetvault.ai.providers import GroqProvider

    groq = GroqProvider()
    prompt_chars = 14_000  # a Hard problem: statement + code + instructions
    budget = groq._output_budget(prompt_chars, 16384)
    assert budget + int(prompt_chars / 3.5) <= 8000
