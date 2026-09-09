# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.19.0] - 2026-09-09

### Added

- The site highlights code, with the colour scheme chosen in a new **Settings** screen -
  GitHub Dark or Light, Dracula, Monokai, Solarized, or none - alongside the page theme and
  the pane layout. The highlighter is self-contained for the same reason as the Markdown
  renderer: no CDN, no build step. Its correctness rests on matching comments and strings
  before keywords, so a keyword inside a string is never coloured.
- **Five pane arrangements** - three columns, two left, two right, one top, three rows -
  each remembering its own sizes. Any arrangement is a different tree over the same three
  panes rather than duplicated markup, so all of them resize with the same drag handles.
- Hints render as collapsible sections, the way GitHub renders them. LeetCode writes them as
  `<details>`/`<summary>`, and escaping every tag showed raw markup on the 87 problems that
  have hints. Exactly those forms pass through; anything with attributes stays escaped.
- Notes moved from a band under the panes into a modal, leaving the problem view to the
  question, the code and the analysis alone.

### Fixed

- The page rendered nothing but its sidebar. Two causes, a week apart: a hidden view was
  still displayed because `section{display:flex}` outranked the `hidden` attribute, and the
  layout engine looked panes up by id after detaching them, where `getElementById` returns
  null. The test fixture that missed the second one has been replaced with a DOM stub strict
  enough to catch it - it boots the real page on every route and fails if no view appears.
- Asset URLs carry a content hash, and the catalogue is fetched with `no-cache`. GitHub
  Pages serves with `max-age=600`, so an update was invisible for ten minutes - which looks
  exactly like the update not working.
- The problem view reaches the window edges. The inset reserved for the floating sidebar
  button had been applied to the whole view, holding the panes off the left for a button
  that sits above them.

## [0.18.0] - 2026-09-09

### Added

- The site gains a **light/dark switch**, cycling system, light and dark. It follows your
  system until you choose, and a choice then wins in both directions - including light on a
  dark machine. The stylesheet keeps its `prefers-color-scheme` rule as a fallback, so the
  page still themes itself if the script never loads.
- The **sidebar folds away** for a full-window view, from the button in its corner or the
  `\` key, and stays folded across navigation.

### Fixed

- git no longer hangs on an interactive credential prompt. With no terminal to answer it,
  a push waited indefinitely instead of falling through to the other credential helper -
  seen for real once a stored PAT had been revoked, where the command simply never returned.
  It now fails fast with the actual error, which is something you can act on.
- The site had two scrollbars. The shell was allowed to grow past the viewport as well as
  the region that owns the content, so a single list produced a page scrollbar and a table
  scrollbar. The shell is now fixed to the viewport and only the inner region scrolls.

## [0.17.1] - 2026-09-09

### Fixed

- `leetvault site --publish` now commits the site it just wrote. The commit helper defaults
  to staging `.github` for the Q&A bot, and the site call did not name its own paths - so
  nothing was committed, the publish still reported OK, and GitHub Pages served the rendered
  `README.md` instead of the page. Two tests now pin which paths a publish stages, and that
  every file `write_site` writes is covered by them.

## [0.17.0] - 2026-09-09

### Added

- `leetvault site` builds a browsable web page for the solutions repo and, with `--publish`,
  pushes it and turns on GitHub Pages. An index you can search, filter and sort; a problem
  view with question, code and analysis in three panes you can drag, with the widths
  remembered; every earlier submission behind one button; the problem index as a slide-over
  drawer; and **My Course**, a `Course/` folder of Markdown nested however you like.
- Nothing is duplicated: the page reads `question.md`, `latest.*`, `analysis.md` and
  `history/*` at the paths sync already writes, so a file edited on GitHub changes the page
  immediately. Only the catalogue is generated, and `sync` refreshes it - for a repository
  that already has a site, never installing one that does not.
- Because GitHub Pages is static, Edit and Add open GitHub's own editor rather than writing
  from the browser, which keeps every note in git history and puts no access token in a
  public page. The page is plain HTML, CSS and JavaScript - no build step, no CDN.

## [0.16.4] - 2026-08-09

### Documentation

- The README gains a **Command reference**: every command with every argument and option,
  including the nine that had never been documented - `--site` on `import`/`sync`/`watch`,
  `--provider` and `--model` on `analyze`/`ask`, `--yes`, and `--save`. Two tests check the
  README against the live CLI, so a command or flag added without documenting it fails the
  suite rather than being noticed months later by someone reading the help text instead.

## [0.16.3] - 2026-08-09

### Fixed

- NVIDIA requests no longer fail with `thinking_token_budget is not yet supported by the V2
  model runner`. NVIDIA moved to a new serving stack and stopped accepting the
  `reasoning_budget` parameter that had worked for weeks; nothing in leetvault changed. The
  parameter is now optional - sent when accepted, dropped and retried once when a 400 names
  it as unsupported. Thinking itself still works and is unaffected. A 400 about anything
  else is not retried, since retrying a genuinely bad request only spends quota to fail
  twice.
- Groq's default model is now `openai/gpt-oss-120b`. Groq decommissioned
  `llama-3.3-70b-versatile` (and `llama-3.1-8b-instant`), and a retired model is a 404 rather
  than a warning, so the old default had already stopped working for everyone. The
  replacement is Groq's own recommendation and, unlike the retired one, reasons - it is the
  model that got a Hard problem's complexity right where the old default invented a `2^k`
  term. A test now fails if any default points at a model known to be withdrawn.

## [0.16.2] - 2026-08-09

### Security

- The Q&A workflow no longer interpolates an issue's text into its shell script. A question
  containing a double quote ended the string early and failed the job; one containing
  `$(...)` or backticks would have executed on the runner, which holds the API keys and a
  write token. The problem and question now reach the script through the environment, where
  a shell treats them as data. The `$GITHUB_OUTPUT` block also uses a random delimiter, so a
  question containing a line `EOF` cannot close it early and inject further step outputs.
  **Re-run `leetvault bot --install` to update the workflow in your repository.**

## [0.16.1] - 2026-08-09

### Fixed

- A follow-up comment no longer re-asks the question from the issue title. The title's
  question is answered when the issue is opened, so merging it into every later comment had
  the model answer it again alongside the new one. On a comment the body is the question;
  the title only names the problem.

## [0.16.0] - 2026-08-09

### Fixed

- Pushing no longer fails when the remote has moved on. The Q&A bot commits answers from a
  CI runner, so the repository now has a second writer and the local clone is routinely
  behind - git refuses a non-fast-forward push, which surfaced as "Note about
  fast-forwards". `sync`, `import`, `watch` and `bot --install` now rebase onto the remote
  first. A rebase that genuinely conflicts is aborted and reported rather than leaving the
  repository mid-rebase.
- The Q&A workflow serialises its runs and rebases before pushing, retrying briefly. Two
  questions asked close together raced to commit `qa.md`, and nothing coordinated the job
  with a `leetvault sync` pushing from a laptop while it worked.
- An error raised when no PAT is set is readable again. Scrubbing an empty PAT replaced the
  gap between every character, turning the message into a wall of asterisks.

## [0.15.3] - 2026-08-09

### Fixed

- A question asked in the issue title is no longer discarded. GitHub issue forms write
  `_No response_` into a field left blank, which is not empty, so the workflow preferred it
  over the title - and the bot replied by asking what you wanted to know. Title and body are
  now both used, and when both carry something neither is dropped.
- Issue parsing moved out of the workflow YAML and into `leetvault.bot.parse_issue`, where
  tests can reach it. Logic inlined in YAML is why the above shipped unnoticed. Slugs
  containing hyphens are also handled properly now - `two-sum` stays whole while
  `3348 - explain` splits.

## [0.15.2] - 2026-08-09

### Fixed

- `bot --install` uploaded every API key as the literal string `-` rather than the key. gh
  reads a secret from standard input only when `--body` is absent; `--body -` is not a stdin
  convention and stores a one-character secret. The failure surfaced much later, as an
  "Invalid API Key" 401 from the workflow. **Anyone who ran `bot --install` before this must
  re-run it** to replace the broken secrets.

## [0.15.1] - 2026-08-09

### Fixed

- `ask` names the model it is using, not just the provider, and says what a 401 or 404
  usually means. Provider and model are configured separately, so pairing a model with the
  wrong backend is easy to do; a bot comment reading only "No answer: HTTP 401" sent the
  reader looking at their API key when the cause was a Groq model name asked of NVIDIA.

## [0.15.0] - 2026-08-08

### Added

- The Q&A workflow honours a `LEETVAULT_AI_MODEL` repository variable, so the bot's model can
  be changed without reinstalling. Previously only the provider was configurable and each
  provider's default applied - for Groq that is `llama-3.3-70b-versatile`, which is not a
  reasoning model. The flag is passed only when the variable is set, so an unset one leaves
  each provider on its own default. `bot --install` uploads a locally pinned `ai_model`
  alongside the provider.

## [0.14.1] - 2026-08-08

### Fixed

- `leetvault bot --install` pushes the workflow it commits. It ran a bare `git push`, which
  needs the branch to have an upstream; a repository leetvault created and only ever pushed
  to by URL has none, so it failed with git's `push.autoSetupRemote` advice after every other
  step had succeeded. The push now names its refspec, as the rest of the package already did.
- A run that committed but failed to push now retries the push. It previously reported
  "already up to date" because there was nothing new to commit, leaving the workflow on disk
  and never reaching GitHub.
- Failure reporting names only the steps that failed. It reprinted the entire manual
  checklist after five of six steps had succeeded, and attributed a git error to missing gh
  scopes - sending you to the wrong settings page. Scope advice now appears only for an
  actual permission error, and a failed push prints the exact `git push` command.

## [0.14.0] - 2026-08-08

### Added

- `leetvault bot --install` now performs the whole setup instead of printing instructions for
  it. Using the GitHub CLI it uploads every stored API key as an encrypted repository secret,
  sets the provider variable, grants the workflow permission to commit, and pushes the
  workflow - a push a fine-grained PAT cannot make, since GitHub refuses one touching
  `.github/workflows/` without the Workflows permission. Each step is reported individually,
  the files are still written if GitHub cannot be reached, and `--manual` skips the GitHub
  calls entirely.

## [0.13.0] - 2026-08-08

### Added

- `leetvault ask <problem> "<question>"` - ask a question about one of your solutions and
  keep the answer. The exchange appends to that problem's `qa.md`, and earlier questions in
  the thread are carried into later ones. Context is read from the repository rather than
  the database, so the same command runs anywhere a checkout exists.
- `leetvault bot --install` - installs a GitHub Actions workflow and issue template so
  questions can be asked from GitHub itself. Open an issue titled `[two-sum]: why a hash
  map?` and the bot answers as a comment and commits the exchange to `qa.md`. The API key
  lives in GitHub's encrypted secrets, and the workflow answers only issues opened by the
  repository owner - on a public repo anyone can file one, and every stranger would
  otherwise be spending the owner's quota.

## [0.12.2] - 2026-08-08

### Fixed

- Requests no longer exceed a provider's per-minute token budget. `max_tokens` is *reserved*
  on a metered API and counted alongside the input, so the 16384 introduced in 0.12.0 made
  Groq refuse outright - "Requested 19255" against a limit of 8000 - where the earlier
  truncation at least returned something. Each backend now declares its own ceiling and
  clamps the reservation to fit the tier.
- Splitting now shrinks the request. Narrowing to fewer sections while still reserving a
  whole analysis's worth of output is the same size request, so escalation could run all the
  way to eight parts and be refused identically at every step.
- Groq's pause between calls is now 60s. Its free tier meters 8000 tokens per *minute* and
  one analysis call reserves most of that, so a shorter gap simply moved the refusal to the
  next call. A problem answered in a single call never waits.

## [0.12.1] - 2026-08-08

### Fixed

- One problem can no longer consume unbounded time. Escalating across splits multiplies
  calls, and a large reasoning model can spend ten minutes on a single Hard problem, so the
  worst case was hours on one file with no way to tell working from wedged. There is now a
  15-minute ceiling per problem, after which it stops and says the model is too slow.
- The progress bar names the attempt it is on - "whole analysis", then "2 parts", "4 parts",
  "8 parts" - so a slow run is legible rather than looking like a hang.
- NVIDIA's reasoning budget drops from 16384 to 6144 tokens (and its output cap from 32768
  to 16384). At the old setting `nemotron-3-ultra-550b` ran past the ten-minute per-call
  timeout on a Hard problem; an analysis that never arrives is worth less than a slightly
  shallower one that does.

### Fixed

- The README documents `analyze`, `commands`, the NVIDIA NIM backend, and how an analysis is
  assembled - all of which had shipped without reaching it. It also no longer claims analysis
  is "written once per problem, never regenerated", which `analyze` made untrue. Tests now
  check every registered command and every AI backend against the README, so the docs cannot
  drift behind the CLI unnoticed.

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

[Unreleased]: https://github.com/priyadip/LeetVault/compare/v0.19.0...HEAD
[0.19.0]: https://github.com/priyadip/LeetVault/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/priyadip/LeetVault/compare/v0.17.1...v0.18.0
[0.17.1]: https://github.com/priyadip/LeetVault/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/priyadip/LeetVault/compare/v0.16.4...v0.17.0
[0.16.4]: https://github.com/priyadip/LeetVault/compare/v0.16.3...v0.16.4
[0.16.3]: https://github.com/priyadip/LeetVault/compare/v0.16.2...v0.16.3
[0.16.2]: https://github.com/priyadip/LeetVault/compare/v0.16.1...v0.16.2
[0.16.1]: https://github.com/priyadip/LeetVault/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/priyadip/LeetVault/compare/v0.15.3...v0.16.0
[0.15.3]: https://github.com/priyadip/LeetVault/compare/v0.15.2...v0.15.3
[0.15.2]: https://github.com/priyadip/LeetVault/compare/v0.15.1...v0.15.2
[0.15.1]: https://github.com/priyadip/LeetVault/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/priyadip/LeetVault/compare/v0.14.1...v0.15.0
[0.14.1]: https://github.com/priyadip/LeetVault/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/priyadip/LeetVault/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/priyadip/LeetVault/compare/v0.12.2...v0.13.0
[0.12.2]: https://github.com/priyadip/LeetVault/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/priyadip/LeetVault/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/priyadip/LeetVault/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/priyadip/LeetVault/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/priyadip/LeetVault/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/priyadip/LeetVault/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/priyadip/LeetVault/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/priyadip/LeetVault/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/priyadip/LeetVault/compare/v0.8.0...v0.8.1
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
