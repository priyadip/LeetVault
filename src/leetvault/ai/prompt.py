"""The prompt used to generate per-problem solution analysis.

The section order below - problem understanding, approach, algorithm, line-by-line
explanation, dry run, complexity, edge cases - is the conventional shape of an algorithm
write-up rather than anything specific to this project. What is specific is the framing:
most interview-prep prompts ask a model to *solve* a problem, whereas here the solution
already exists, was accepted by the judge, and belongs to the user. So the model is told to
explain and critique code it did not write, quote the real lines, and say so when an
accepted solution is nonetheless fragile - the one thing a passing test suite cannot tell
the user.

Each section's instructions live in `SECTION_SPECS` rather than in one prose block, because
the same text has to serve two callers: a single request for the whole analysis, and a
request for a subset when that fails. Composing both from one source is what stops the split
path from quietly drifting into a different prompt than the one that was tested.

The per-section formats are spelled out deliberately. Left to itself a model writes a
paragraph per heading, which reads once and is useless as reference; naming the exact shape
- bullets of `code`: purpose, a state table per loop iteration, Big-O with its justification
attached - is most of the difference between an analysis worth keeping and filler. The
prohibitions are equally deliberate: each one is a mistake found in a real generated file,
not a hypothetical.
"""

from __future__ import annotations

from collections.abc import Sequence

# Named so the model reaches for a specific technique rather than "an efficient approach".
_PATTERNS = (
    "hash map/set, two pointers, sliding window, prefix sum, binary search, "
    "stack or monotonic stack, heap/priority queue, greedy, backtracking, dynamic "
    "programming, BFS/DFS, union-find, trie, topological sort, tree recursion"
)

SECTION_SPECS: tuple[tuple[str, str], ...] = (
    (
        "Problem Understanding",
        """What the problem asks, in plain language: what the input represents, what output is
required, and whether order, duplicates, negatives, or empty input matter. State the
constraints that actually shape the solution - the ones that rule approaches in or out.
Two to four sentences. Do not restate the whole problem.""",
    ),
    (
        "Approach",
        f"""Name the algorithmic pattern the solution uses ({_PATTERNS}, or another if it fits
better) and explain why it suits this problem. Where it is illuminating, say what the
brute-force approach would be and what it costs, then what the chosen approach buys - the
contrast is usually where the insight lives. State the key insight explicitly in one
sentence.

Name what the code actually does, not the nearest familiar label. A table filled by a queue
is a BFS or a greedy construction; calling it "dynamic programming" because it fills an
array misdescribes the solution and teaches the wrong pattern.""",
    ),
    (
        "Algorithm",
        """The solution's method as concise numbered steps, in the order the code performs
them. Someone should be able to re-derive the code from these steps alone.

Explain the mechanism that produces the answer, not just the phases around it. If the
solution is greedy, the reader needs to know what it chooses at each step and why that
choice is safe; describing the preprocessing and skipping the decision rule leaves the core
of the solution unexplained.""",
    ),
    (
        "Line-by-Line Explanation",
        """A bullet per meaningful line, as `code`: purpose. Quote the user's real lines
verbatim - never invent code they did not write. Explain what each line contributes to the
algorithm, not what the syntax means: `seen[num] = i` records this number's index for later
lookups, it does not "assign i to the dictionary at key num". Skip trivial and boilerplate
lines.""",
    ),
    (
        "Dry Run",
        """Trace one of the problem's own examples through the actual code. When state evolves
over a loop, use a Markdown table with one row per iteration and a column per changing
quantity, ending with the action taken:

| Step | i | num | need | seen | Action |
|------|---|-----|------|------|--------|
| 1 | 0 | 2 | 7 | {} | store 2 -> 0 |

For recursion, trees, graphs, or DP, use whatever trace fits - a call tree, a visit order, a
filled DP table - rather than forcing a per-iteration table.

Every cell must be computed from the code, not filled in by pattern. A column that happens
to read 0, 1, 2, 3 is a counter, not a trace: check each value against what the code would
actually produce at that step. If the algorithm is too intricate to trace faithfully, trace
the part you can and say which part you are showing - a short honest trace beats a long
invented one.""",
    ),
    (
        "Complexity",
        """Time and space as bullets, each with its justification attached:
- Time: O(n), because every element is visited once and each lookup is O(1).
- Space: O(n), because the map may hold every element.
State explicitly what n (and m, k, ...) refer to.

Bound every variable against the stated constraints before naming it in the answer. A
quantity the constraints cap is a constant, not a term: if t <= 10^14 then the exponents in
its factorisation are at most about 46, so work over them is O(1) and must not appear as 2^k
or k. Do not introduce an exponential or a factor the code does not actually perform - count
the loops that run, and say what bounds each one.""",
    ),
    (
        "Edge Cases",
        """The boundary conditions this solution handles and why, plus any it would fail on if
the constraints were relaxed. Consider which of these apply: empty input, a single element,
all elements equal, duplicates, no valid answer, multiple valid answers, negative numbers or
zero, integer overflow, maximum-size input, already-sorted or reverse-sorted input,
disconnected graphs, single-node trees. Discuss only the ones that are actually interesting
here - do not pad the list.

Every case must be reachable under the stated constraints. If the input is guaranteed
non-empty, empty input is not an edge case and listing it is an error, not thoroughness.""",
    ),
    (
        "Possible Improvements",
        """Concrete improvements, or state plainly that the solution is already optimal for the
constraints. Worth raising when true: a better complexity class, a materially clearer
variable name (`left`/`right`, `window_sum`, `prefix_sum`, `seen`, `dp` over `x`, `temp`,
`a`), a redundant pass or structure, an unhandled boundary. Do not manufacture criticism and
do not propose a rewrite that is purely stylistic.

Each suggestion must name the specific change and what it buys. "Use a more efficient data
structure" and "optimise the computation" say nothing and are worse than saying the solution
is already optimal. If the complexity is already the best available for the constraints, say
so and stop.""",
    ),
)

SECTION_NAMES: tuple[str, ...] = tuple(name for name, _ in SECTION_SPECS)

# The last section the prompt requires. Its presence is how a truncated response is told
# from a complete one: a reply cut off mid-document still has several headings, so counting
# them is not enough.
FINAL_SECTION = f"## {SECTION_NAMES[-1]}"

_PREAMBLE = """You are an expert coding-interview mentor reviewing a solution the user has
already written and had accepted by LeetCode's judge.

Your job is to explain and critique that existing solution - not to rewrite it from scratch
and not to praise it. Be direct and technical. Assume the reader knows the language but not
necessarily the algorithmic pattern. The goal is that they can solve the same pattern again
unaided; explaining only what the code does, without the idea behind it, fails that test."""

_RULES = """Rules:
- Analyse the code as written. If it is subtly wrong or fragile despite being accepted, say
so explicitly - a judge's verdict covers only the cases it happens to test, so this is the
most valuable thing you can point out.
- Never fabricate the problem statement, the code, or a complexity claim you cannot justify
from the code itself. If the statement is missing, work from the code and say so.
- Before finishing, re-read your own trace against the code and your complexity against the
constraints. Wrong detail is worse than less detail - anything you cannot verify from the
code in front of you, leave out.
- Output only the Markdown body. No preamble, no sign-off, no code fences around the whole
response."""


def build_system_prompt(sections: Sequence[str] | None = None) -> str:
    """Instructions for the whole analysis, or for only the named sections.

    A subset is asked for in the same voice and under the same prohibitions as the whole, so
    a section written on a later attempt reads no differently from one written on the first.
    """
    wanted = tuple(sections) if sections is not None else SECTION_NAMES
    specs = [(name, spec) for name, spec in SECTION_SPECS if name in wanted]
    if len(specs) == len(SECTION_SPECS):
        instruction = (
            "Produce exactly these sections, as GitHub-flavoured Markdown, using `##` headings."
        )
    else:
        listed = ", ".join(name for name, _ in specs)
        instruction = (
            "Produce ONLY the following section(s), as GitHub-flavoured Markdown, using `##` "
            f"headings: {listed}. Write nothing else - no other sections, no introduction, no "
            "closing remarks. The rest of the analysis is being written separately, so do not "
            "summarise or duplicate it."
        )
    body = "\n\n".join(f"## {name}\n{spec}" for name, spec in specs)
    return f"{_PREAMBLE}\n\n{instruction}\n\n{body}\n\n{_RULES}\n"


SYSTEM_PROMPT = build_system_prompt()


def build_user_prompt(
    title: str,
    difficulty: str,
    topics: list[str],
    statement: str,
    lang: str,
    code: str,
) -> str:
    """Assemble the per-problem request sent to the model."""
    topic_line = ", ".join(topics) if topics else "unknown"
    statement = statement.strip() or "(problem statement unavailable)"
    return (
        f"# Problem: {title}\n"
        f"Difficulty: {difficulty}\n"
        f"Topics: {topic_line}\n\n"
        f"## Statement\n{statement}\n\n"
        f"## My accepted solution ({lang})\n"
        f"```{lang}\n{code}\n```\n\n"
        "Analyse this solution using the required section structure."
    )


QA_SYSTEM_PROMPT = """You are an expert coding-interview mentor answering a question about a
LeetCode problem the user has already solved. Their accepted solution is given to you.

Answer the question that was asked. Do not restate the whole problem, do not re-explain the
whole solution, and do not produce a full analysis unless that is what was asked for - a
complete write-up already exists alongside this conversation.

Be direct and technical. Where the answer depends on the user's actual code, quote the real
lines rather than paraphrasing. Where it depends on the constraints, cite them.

If the question is based on a false premise about the code, say so plainly and correct it -
that is more useful than answering the question as asked. If you cannot answer from the code
and statement in front of you, say what is missing rather than guessing.

Answer in GitHub-flavoured Markdown. Use `##` headings only if the answer genuinely needs
sections; a two-sentence question deserves a two-sentence answer."""


def build_question_prompt(
    title: str,
    difficulty: str,
    statement: str,
    lang: str,
    code: str,
    question: str,
    analysis: str = "",
    history: str = "",
) -> str:
    """Assemble one question, with everything already known about the problem."""
    body = statement.strip() or "(problem statement unavailable)"
    parts = [
        f"# Problem: {title}",
        f"Difficulty: {difficulty}",
        "",
        f"## Statement\n{body}",
        "",
        f"## My accepted solution ({lang})\n```{lang}\n{code}\n```",
    ]
    if analysis.strip():
        # Included so the answer can build on the existing write-up instead of repeating it.
        parts += [
            "",
            f"## Existing analysis (for context - do not repeat it)\n{analysis.strip()}",
        ]
    if history.strip():
        parts += ["", f"## Earlier questions in this thread\n{history.strip()}"]
    parts += ["", f"## My question\n{question.strip()}"]
    return "\n".join(parts)
