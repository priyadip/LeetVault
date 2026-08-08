# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.12.0] - 2026-08-08

### Changed

- Analysis is now composed over as many model calls as it takes. One request for everything
  is still tried first and kept when it works; if the reply is truncated or incomplete the
  sections are re-requested in halves, then pairs, then one at a time, pausing between calls
  so a free tier's per-minute budget is not exhausted in one shot. Groq allows 8000
  tokens/minute, which a single Hard-problem analysis can spend on its own.
- Generation now runs at temperature 0.2 with an explicit output limit on every backend.
  Groq's default cap is 3072 tokens, which silently truncated a Hard problem mid-section,
  and sampling variety buys nothing when the task is tracing real code.
- The prompt now forbids the specific mistakes found in generated files: dry-run tables
  filled in by pattern rather than computed, complexity terms the constraints rule out
  (a bounded quantity is a constant, not a `2^k`), edge cases impossible under the stated
  constraints, and vague improvements like "use a better data structure". It also asks the
  model to name what the code does rather than the nearest familiar label, and to explain
  the decision rule of a greedy solution rather than only its preprocessing.

### Fixed

- A truncated response is no longer accepted as complete. The previous check counted
  headings, and a reply cut off at the output cap still had four - so it passed, was
  written, and would never have been retried because the file's existence is what makes
  later runs skip a problem. Completeness now requires every section, compared with dashes
  and capitalisation normalised so a model writing `Line-by-Line` with a typographic hyphen
  is not judged to have omitted it.

## [0.11.1] - 2026-08-08

### Fixed

- An expired LeetCode session now prints what happened and how to fix it, instead of a
  traceback ending in `raise_for_status`. Sessions lapse after about two weeks, so this is
  the most common way a working install stops working, and a bare `401 Unauthorized` gave
  no hint that `leetvault login --leetcode` was the one-command fix. `sync`, `import` and
  `watch` also check the cookie's own expiry before the first request, so the failure
  arrives when you type the command rather than partway through a progress bar.

## [0.11.0] - 2026-08-06

### Added

- `leetvault commands` - every command in one place with what it does, and `--full` for
  every argument and option. Built by introspecting the Typer app rather than from a
  hand-written list, so a new command cannot be left out: tests assert that every
  registered command and parameter appears in the output, including the global flags and
  `--help`, which click supplies implicitly.

## [0.10.0] - 2026-08-06

### Added

- `leetvault analyze` - regenerate an existing `analysis.md` with a different backend.
  `sync` deliberately skips problems that already have one, which is what makes a backfill
  resumable but also meant an analysis you disliked was permanent. Select by slug, number or
  title, by the provider that wrote it (`--from groq`), or `--all`; `--list` shows which
  model wrote what. Overwrites are confirmed first, and a failed regeneration keeps the
  existing file rather than losing it.

## [0.9.0] - 2026-08-06

### Added

- **NVIDIA NIM** as an AI backend (`leetvault ai --set-key nvidia`), defaulting to
  `nvidia/nemotron-3-ultra-550b-a55b`. Its free-tier quota is separate from Gemini's and
  Groq's, so a backfill stopped by one provider's daily limit can be finished on another.
  Thinking is enabled; the model returns its reasoning in a separate field, so the chain of
  thought never reaches the generated file.

### Changed

- The analysis prompt now specifies the shape of each section rather than only its title:
  contrast with the brute-force approach, a bullet per meaningful line quoted verbatim, a
  per-iteration state table for the dry run, Big-O with its justification attached and its
  variables defined, and a named algorithmic pattern. Left to itself a model writes a
  paragraph per heading, which reads once and is useless as reference.
- Responses without at least four `##` sections are rejected instead of written. A stub or
  truncated reply would otherwise be saved permanently, since the file's existence is what
  makes later runs skip that problem.

## [0.8.2] - 2026-08-05

### Added

- An **Analysis** column in the README tables, linking each problem to its `analysis.md`.
  The files were being written and pushed correctly but nothing in the dashboard pointed at
  them, which from the reader's side is the same as their not being there. The column
  appears only once at least one analysis exists, and marks problems without one.

### Changed

- The AI analysis line now says what its count covers. It reports every problem still
  missing an analysis, so a sync finding one new submission could announce 50 problems and
  look broken; it now names the backfill as one.

### Fixed

- `mypy --strict` no longer fails in CI on the optional `anthropic` import. The check passed
  on machines that happened to have the package installed and failed on those that did not,
  which is the wrong way round for an optional backend.
- `pytest` now runs against `src/` rather than whatever `leetvault` is installed. A
  non-editable install shadowed the working tree, so the suite could pass locally while
  testing the released wheel instead of the change under test.

## [0.8.1] - 2026-08-05

### Fixed

- AI analysis failures are now reported instead of passing silently. A sync could announce
  "Generating AI analysis for 50 problem(s)", complete its progress bar, and write nothing
  at all with no explanation, which looked exactly like the feature not working. Providers
  record why a generation failed and `sync` prints it, giving up after three consecutive
  failures rather than issuing dozens of doomed requests.
- The default Gemini model is now `gemini-flash-latest`. The previous pinned
  `gemini-2.0-flash` returns HTTP 429 with a free-tier quota of zero, and other pinned names
  are retired for new users; the alias tracks whatever the free tier actually serves.

## [0.8.0] - 2026-08-05

### Added

- `leetvault ai` — optional AI-generated `analysis.md` per problem, explaining the approach,
  walking through your actual code, and covering complexity and edge cases. **Off by
  default**; nothing is downloaded, enabled, or billed unless you choose it.
- Pluggable backends so the feature works whatever a user already has: **Gemini** and
  **Groq** free tiers (a free API key, no local hardware - the answer for users with neither
  spare RAM nor a Claude subscription), **Ollama** (free, local, unlimited, offline), the
  **Claude Code CLI** (free with an existing Claude subscription), or the **Anthropic API**
  (paid). `leetvault ai` detects which are usable and lets you pick.
- `leetvault ai --set-key <provider>` stores a per-provider API key in the OS keyring; keys
  are isolated per provider, and an Anthropic key stored before this release keeps working.
- Analysis is written to its own `analysis.md`; `notes.md` remains the user's scratch space
  and is never touched.

### Notes

- The analysis prompt is leetvault's own. Its footer records only the provider and
  model that generated the file.
- Generation is best-effort: a provider returns `None` rather than raising, so a slow or
  failing model can never break a sync.

## [0.7.1] - 2026-08-04

### Added

- A **Question** column in the README's All Solutions and per-topic tables, linking to each
  problem's `question.md` alongside the existing solution link.

## [0.7.0] - 2026-08-04

### Added

- Recover the judge test case that broke each *failed* attempt. A failed submission is the
  only place LeetCode reveals an actual hidden test case - input, expected output and all -
  and those are exactly the edge cases worth keeping.
- `run.py` re-checks them after the examples with a real PASS/FAIL verdict. This is possible
  here precisely because these cases carry LeetCode's expected output, which the statement
  examples do not.
- A one-time backward scan collects failures that predate this feature, gated on a
  sync_state flag so later syncs don't re-walk the whole history.

### Notes

- Failed attempts are stored in their own `failed_testcases` table, not in `submissions`.
  Everything downstream (dedup, "problems solved", latest-per-problem, README stats) assumes
  `submissions` holds accepted work only.

## [0.6.0] - 2026-08-04

### Added

- Record how many of LeetCode's hidden judge test cases each submission ran against
  (`total_correct`/`total_testcases`) in the DB, in `metadata.json`, and in `run.py`'s header.
  LeetCode exposes these counts but never the cases themselves - one real problem here was
  judged against 11,511 of them.
- Existing databases are migrated additively on open (SQLite `ALTER TABLE ADD COLUMN`), and
  counts for already-stored submissions are backfilled on the next sync.
- A `.gitignore` is written to the solutions repo so running a solution doesn't commit
  `__pycache__`.

## [0.5.0] - 2026-08-04

### Added

- Every problem folder now gets a `run.py` that executes your stored solution against that
  problem's own example inputs and prints the results. It deliberately does not assert
  pass/fail: LeetCode's API exposes example *inputs* but not expected outputs, so a verdict
  would be guesswork - compare against the `Output:` lines in `question.md`.
- A `.devcontainer/` so the repo opens in GitHub Codespaces with Python ready, letting you
  edit and run any solution from the browser.
- A shared `leetvault_runner.py` at the repo root, which each `run.py` delegates to.

### Notes

- The runner rebuilds the namespace LeetCode's judge preloads (`List`, `gcd`, `bisect`,
  `Counter`, `inf`, `ListNode`/`TreeNode`, ...), because stored solutions routinely use those
  names with no import and would otherwise raise `NameError`.
- Problems whose inputs aren't plain JSON (linked lists, trees) or that have no single entry
  point (design problems) are refused with an explanation rather than run incorrectly.
  Verified against a real 48-problem repo: 47 run, 1 refuses cleanly, 0 errors.

## [0.4.0] - 2026-08-04

### Added

- Each problem folder now gets a `question.md` containing the LeetCode problem statement:
  description, examples, constraints, collapsed hints (so opening the file doesn't spoil the
  problem), and similar-question links. Fetched once per problem and never re-fetched.
- Existing problems are backfilled automatically on the next `sync` - no re-import needed.
- `leetvault config write_question_md false` disables the feature entirely.

### Changed

- Topics and the problem statement now come from a single `question(titleSlug)` call instead
  of a separate topics-only query, so enabling statements costs no extra API calls for a new
  problem.

## [0.3.0] - 2026-08-04

### Added

- `login` now live-checks each credential and **only prompts for what's actually missing or
  expired**. LeetCode cookies (which roll over every ~14 days) and the GitHub PAT fail
  independently, so refreshing one no longer means re-entering the other. If both are still
  valid, `login` prompts for nothing.
- `login --leetcode` / `login --github` to target one credential explicitly, and `login
  --force` to re-prompt for everything regardless of validity.

### Changed

- `status` now live-validates the stored GitHub PAT (reporting the account it belongs to, or
  that it was revoked) instead of only reporting whether one is present.

## [0.2.0] - 2026-08-04

### Added

- Topic tags in the generated README dashboard are now clickable. Each tag links to a new
  "Problems by Topic" section listing every problem carrying that topic (with difficulty and a
  link to the stored solution), and each section links back up to the topic list. Anchors follow
  GitHub's own heading-slug rules, so names like `Heap (Priority Queue)` and `Depth-First
  Search` resolve correctly.

## [0.1.2] - 2026-07-11

### Fixed

- `leetvault config dedup_window_seconds 0` (intended as a persistent alternative to typing
  `--keep-all` every run) silently did nothing - the fallback `raw or 86400` treated an
  explicit `0` the same as "unset". Fixed to check for `None` explicitly.

### Docs

- Clarified that `--keep-all` only affects future processing and cannot retroactively recover
  a submission an earlier run already deduped; added recovery guidance to
  docs/TROUBLESHOOTING.md and docs/FAQ.md.

## [0.1.1] - 2026-07-11

### Fixed

- Resolving an already-synced problem again later (even the same day) was silently dropped
  forever, and `latest.py` never updated past the first submission `sync` ever saw for that
  problem. The dedup window check used raw subtraction, which goes negative - and therefore
  always looks "within the window" - for any submission newer than the previously-kept one
  seen in an earlier run. Separately, "should this update `latest.py`" was gated on a
  once-ever check that could never re-trigger after the first sync of a problem. Both fixed:
  dedup now compares the absolute time difference, and "is this the latest" is a genuine
  newest-timestamp comparison that updates as submissions are processed.

## [0.1.0] - 2026-07-11

Initial release.

- `login`/`logout`/`status`: keyring-backed LeetCode session storage, live session validation,
  JWT expiry decoding, optional GitHub PAT storage.
- `import`/`sync`: resumable full-history import and incremental sync of accepted submissions,
  same-day dedup (`--keep-all` to disable), REST + GraphQL enrichment.
- Git layer: batched commit + transient-PAT push per run, never persisted to `.git/config`.
- Auto-generated README dashboard: progress, difficulty/language/topic breakdowns, streaks,
  recent solves, full searchable solutions table.
- `watch`: polling loop with graceful shutdown and session-expiry warnings.
- `config`: get/set persistent settings.

[Unreleased]: https://github.com/priyadip/LeetVault/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/priyadip/LeetVault/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/priyadip/LeetVault/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/priyadip/LeetVault/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/priyadip/LeetVault/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/priyadip/LeetVault/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/priyadip/LeetVault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/priyadip/LeetVault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/priyadip/LeetVault/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/priyadip/LeetVault/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/priyadip/LeetVault/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/priyadip/LeetVault/releases/tag/v0.1.0
