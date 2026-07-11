# PLAN.md — decision log

Running log of small decisions made autonomously per the working protocol in `CLAUDE.md`.
One-way-door decisions get flagged and stopped on instead of logged here.

## Phase 0 — Scaffold

- **Layout**: `src/leetvault/` package, flat modules per concern (`cli`, `config`, `auth`,
  `client`, `models`, `db`, `sync`, `git_writer`, `readme`, `watch`), matching the responsibilities
  in CLAUDE.md's data model / stack sections. Templates will live at
  `src/leetvault/templates/` for Jinja2 `PackageLoader`.
- **CLI wiring**: `cli.py` defines the Typer app + option parsing only; each command lazily
  imports its implementation module and calls a `run_*` function. Keeps `--help` fast and makes
  each phase's module independently testable.
- **Extra deps beyond CLAUDE.md's "exact stack"**: added `pyjwt` (to decode the `LEETCODE_SESSION`
  JWT `exp` claim per the Auth section) and dev-only `pytest-mock` + `respx` (mocking httpx calls
  for Phase 3 sync tests). No new *runtime-behavior* dependencies (e.g. no `platformdirs`) —
  config/data dir resolution is hand-rolled in `config.py` per-OS (`APPDATA`/`LOCALAPPDATA` on
  Windows, `XDG_CONFIG_HOME`/`XDG_DATA_HOME` with `~/.config`/`~/.local/share` fallback elsewhere)
  to avoid scope creep on the dependency list.
- **Config store**: plain JSON file under the OS config dir (`config.json`), holding only
  non-secret settings (site, dedup window, repo path/URL, DB path, watch interval). All secrets
  (LeetCode cookies, GitHub PAT) go through `auth.py` into `keyring` exclusively — never touch this
  file.
- **Python floor**: `requires-python = ">=3.11"` to match the CI matrix (3.11-3.13) in CLAUDE.md.
- **License**: MIT (project says "Free/OSS only"; MIT is the friendliest default for a CLI tool
  with no stated preference).

## Phase 1 — Data layer

- **Models**: literal translation of CLAUDE.md's schema into SQLAlchemy 2.0 declarative style
  (`DeclarativeBase`/`Mapped`/`mapped_column`). `problem_topics` is both the M2M association table
  (referenced via `secondary="problem_topics"` string) and its own mapped class, since it carries
  no extra columns beyond the two FKs — kept as a full model (not `Table(...)`) so it participates
  in `Base.metadata.create_all` uniformly with everything else.
- **`sync_state`**: one row per `site` (`com`/`cn`), enforced via a unique index on `site` rather
  than a fixed single-row table — simpler than a singleton pattern and matches the `--site`
  option's per-site resumability requirement.
- **Engine construction**: `sqlalchemy.URL.create("sqlite", database=str(path))` instead of
  hand-building a `sqlite:///` string — avoids Windows path-escaping edge cases (backslashes,
  spaces in usernames, which this dev machine has).
- **Session pattern**: a `session_scope` context manager (commit on success, rollback on
  exception, always close) is the only way `sync.py`/`watch.py` will touch the DB — keeps
  transaction boundaries explicit and matches "resumable" requirement (partial progress commits
  per page, not per full import).

## Phase 2 — Auth + client

- **Credential storage**: LeetCode session/csrftoken are stored per-site
  (`leetcode_session:com`/`leetcode_session:cn`, etc.) in `keyring` under service `leetvault`, so a
  user could in principle hold both `.com` and `.cn` sessions at once without collision. GitHub PAT
  is a single global entry (`github_pat`) — added in `auth.py` now (storage/load/clear helpers)
  since it's the same keyring mechanism, but nothing calls `store_github_pat` until Phase 4's `git`
  push flow prompts for it.
- **JWT expiry**: decoded with `pyjwt`, `verify_signature=False` — leetvault never has LeetCode's
  signing key, it only needs the `exp` claim to warn the user, not to authenticate (the cookie
  itself is what authenticates, to LeetCode's servers).
- **`login` validates live**: rather than just storing whatever the user pastes, `run_login` opens
  a real `LeetCodeClient`, calls `userStatus` over GraphQL, and only persists credentials if
  `isSignedIn` is true — refuses to silently store dead cookies.
- **`logout` scope**: clears only the LeetCode session/csrftoken for the configured site, not the
  GitHub PAT — matches the command's name/description ("Remove stored credentials" in the context
  of the login/logout pair) and avoids surprising a user who re-runs `logout` after a Phase 4
  push setup expecting the PAT to survive. `# FUTURE:` a `--all` flag could also clear the PAT if
  requested.
- **Rate limiting**: `RateLimiter` is a plain sliding-window counter (deque of monotonic
  timestamps), not a token-bucket library — CLAUDE.md's stated shape ("stay under 20 req/10s") is
  exactly a sliding window, and a hand-rolled ~30-line class avoids a new dependency for something
  this small. `.cn` gets a deliberately much stricter `(1, 10.0)` limit since CLAUDE.md flags its
  behavior as undocumented.
- **Backoff sequence**: `httpx-retries`' built-in `Retry.backoff_strategy` is base-2
  (`factor * 2**attempts`); CLAUDE.md specifies a base-3 sequence (1->3->9->27s), so
  `LeetCodeRetry` subclasses `Retry` and overrides just that method. Retries trigger on
  403/429 and honor `Retry-After` via `respect_retry_after_header=True` (built into the library).
- **GraphQL query shapes**: `userStatus`, `submissionDetails`, `recentAcSubmissionList` field
  names (`isSignedIn`, `runtimePercentile`, `titleSlug`, etc.) are reconstructed from well-known
  reverse-engineered LeetCode GraphQL shapes since CLAUDE.md only names the query surface, not
  exact fields. **Unverified against the live API as of this commit** — `run_login`'s live
  `validate_session()` call is the first real check; any field-shape mismatch will surface there
  and get corrected + logged here once real credentials are available. REST `/api/submissions/`
  fields, by contrast, are taken verbatim from CLAUDE.md's explicit list (including the
  `submissions_dump` wrapper key), so no divergence risk there.
- **Test isolation**: added `tests/conftest.py` with two autouse fixtures — a fake in-memory
  keyring (monkeypatches `keyring.set_password`/`get_password`/`delete_password`) and env-var
  redirection of `APPDATA`/`LOCALAPPDATA`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME` into `tmp_path`. No
  test in this suite touches the real OS keyring or the real `%APPDATA%\leetvault` config dir.

## Phase 3 — Sync engine

- **Problem metadata source**: REST `/api/submissions/` gives no `difficulty`/`paid_only`/
  `frontend_id`. Added `client.get_all_problems()` hitting the real (live-verified)
  `/api/problems/all/` endpoint once per run/import to build a `question_id -> ProblemMeta`
  catalog (`stat_status_pairs[].{stat.question_id, stat.frontend_question_id,
  stat.question__title, stat.question__title_slug}`, `difficulty.level` (1/2/3 ->
  Easy/Medium/Hard), `paid_only`) - a single cheap call rather than one GraphQL
  `questionData` lookup per problem.
- **Dedup semantics**: "same problem within same day" is implemented as - process submissions
  newest-first (REST's natural order, confirmed live); the first submission seen for a
  `question_id` in a run is always kept and becomes that problem's "latest"; a later
  (older) submission for the same problem is dropped if `prior_kept_timestamp - this_timestamp
  < dedup_window_seconds`. The per-problem "last kept timestamp" dict is seeded from
  `MAX(timestamp) GROUP BY question_id` over the existing DB at the start of the run, so dedup
  is correct across run boundaries too, not just within one page. `--keep-all` skips the check
  entirely but still only writes `latest.<ext>`/`metadata.json`/`notes.md` for the first
  (newest) submission per problem per run - older kept submissions still get a `history/`
  entry, just don't become "latest".
- **Percentile enrichment**: `submission_details()` (GraphQL) is called for every *kept*
  (post-dedup) accepted submission, not just when REST's `code` is missing - CLAUDE.md's schema
  wants `runtime_percentile`/`memory_percentile` stored, and dedup already collapses the volume
  down to roughly "problems solved" rather than "total accepted attempts", so the extra
  API call per kept submission is acceptable under the existing rate limiter. Failures there are
  logged and swallowed (best-effort enrichment, never fatal - REST's `code`/`runtime`/`memory`
  are always sufficient on their own).
- **`import` is a one-time full-history operation per site**: gated on
  `sync_state.last_full_import_completed_at`. A second `import` call is a pure no-op (zero HTTP
  calls) once that's set - re-running does no redundant work, per the Phase 3 acceptance
  criterion. Interrupted imports resume from `sync_state.last_offset`, persisted after every
  page (not just at the end), satisfying "Import MUST be resumable."
- **`sync` is separate from `import`'s resumability**: it always starts at REST offset 0 and
  walks forward only until it hits a submission whose id/timestamp is already known
  (`sync_state.last_submission_id`/`last_synced_timestamp`), then stops. It refuses to run at
  all (exits 1) if no prior `import` has ever completed, since it has nothing to anchor "new"
  against.
- **Bug found via live smoke run** (not caught by mocked tests): a `run_import` that resumes
  onto an already-fully-paged offset (i.e. `page.submissions` comes back empty) never touches
  `newest_submission_id` in that run, so the old code left `last_submission_id`/
  `last_synced_timestamp` as `None` even after marking `last_full_import_completed_at` -
  silently breaking every future `sync` (which requires a non-null `last_submission_id`).
  Reproduced for real: an earlier `import` run against the live account committed all data
  correctly per-page but crashed afterward on an unrelated Windows console bug (see below)
  before reaching its finalization block; the next `import` invocation resumed straight to the
  empty tail page and would have finalized with `last_submission_id = None` were it not for
  the fix. Fixed by falling back to `SELECT submission_id, timestamp ORDER BY timestamp DESC
  LIMIT 1` from the DB when `newest_submission_id` is `None` and no prior value exists.
  Regression-tested in `tests/test_sync.py::test_run_import_backfills_sync_state_when_resumed_page_is_empty`.
- **Windows console bug found via the same live smoke run**: `rich`'s `Progress`/spinner
  writes Unicode glyphs (braille spinner, block-drawing bar) through its legacy Win32 console
  API path on Windows consoles that report a non-UTF-8 codepage (cp1252 here), crashing with
  `UnicodeEncodeError` on every `import`/`sync`/`watch` invocation that shows a progress bar.
  Fixed in `cli.py`: reconfigure `sys.stdout`/`sys.stderr` to UTF-8 and construct the shared
  `Console` with `legacy_windows=False` so rich always takes the ANSI-escape render path
  instead of the raw Win32 console API. Confirmed fixed by re-running the same live import.
- **Live smoke test**: ran `leetvault import` then `leetvault sync` against the real account
  (`priyadipsau`, site `com`). Correctly pulled 25 total submissions, kept 10 accepted+deduped
  ones (e.g. `target-sum` had two same-day accepted submissions and correctly kept only the
  newer as `latest.py`, with only the newer submission's `history/` entry), wrote the full
  `Problems/<slug>/{latest.py, history/, metadata.json, notes.md}` layout, and a follow-up
  `sync` correctly found zero new submissions.

## Phase 4 — Git

- **PAT collection folded into `login`**, not a new command: v1's command list is fixed
  (`login, import, sync, watch, status, logout, config`), and `login`'s own docstring already
  said "store LEETCODE_SESSION + csrftoken (and optionally a GitHub PAT)" back in Phase 0. After
  a successful LeetCode login, `run_login` asks (`typer.confirm`, default No) whether to also
  store a GitHub PAT, validates it live against `GET https://api.github.com/user`, and only
  stores it in `keyring` (key `github_pat`) if that succeeds. Declining, or running
  non-interactively (tests, piped stdin), is caught (`typer.Abort`/`EOFError`/`OSError` from
  Click's prompt machinery) and just skips silently - login itself is unaffected either way.
  Target repo is set via the existing generic `leetvault config repo_url <url>` - no new command
  needed there either.
- **Transient-PAT push, literally**: `git_writer.push()` never calls `git remote add` (which
  would persist the URL, PAT included, into `.git/config`). It builds an authenticated URL
  (`https://x-access-token:<pat>@host/path`) purely as the destination argument to
  `repo.git.push(url, "HEAD:refs/heads/<branch>")` - GitPython shells out to `git push <url>
  <refspec>` and nothing about that URL is ever written to disk. `GitCommandError` messages
  (which otherwise echo the full failed command, PAT included) are scrubbed
  (`text.replace(pat, "***")`) before being wrapped in `GitWriterError` and re-raised - the
  original exception is never re-surfaced (`from None`), so nothing upstream can print the raw
  PAT even accidentally.
- **One commit per run, not per submission**: `sync_to_github()` is called exactly once at the
  end of `run_import`/`run_sync`, after every file for that run has already been written to
  disk - `git add -A` + one commit + one push covers the whole batch, per CLAUDE.md's "never one
  push per submission." It's a true no-op (`git status --porcelain` empty after staging) when a
  run stored zero new submissions, satisfying "no dupes on re-run" without needing to track
  anything beyond git's own working-tree state.
- **GitHub is fully optional or a no-op**: if `repo_url` isn't configured or no PAT is stored,
  `import`/`sync` still do everything else (DB + disk files) and just print a note explaining
  how to enable it - the tool is useful standalone before Phase 4's GitHub piece is even set up.
- **Live push bug found and fixed**: the first live push attempt failed with a real GitHub 403
  (the fine-grained PAT initially had `Contents: Read` only, not `Read and write` - a user-side
  permission issue, not a code bug, and confirmed our error path handled it correctly: clean
  scrubbed message, exit 1, no PAT leaked anywhere in `git`'s own command echo or our error
  text). But that failed run had already *committed* successfully before the push failed -
  and the original `sync_to_github` only ever called `push()` inside the `if committed:` branch,
  so the next run (nothing new to stage) printed "Nothing new to commit" and returned **without
  even attempting a push**, permanently stranding that commit locally. Fixed: `sync_to_github`
  now always attempts a push whenever `repo.head.is_valid()` (i.e. at least one commit exists),
  regardless of whether *this* run created a new one. Regression-tested in
  `test_sync_to_github_still_pushes_unpushed_commit_when_nothing_new_to_commit`.
- **Live end-to-end verification**: after fixing the PAT's GitHub permissions, `leetvault sync`
  against the real `priyadip/DSA-LeetCode-` repo committed and pushed successfully - confirmed
  by comparing local `HEAD` against `origin/main` via a fresh `git fetch` (exact match) and by
  listing `Problems/` via the GitHub Contents API (all 10 problem directories present).

## Phase 5 — README

_(filled in when started)_

## Phase 6 — Watch

_(filled in when started)_

## Phase 7 — Packaging/CI/docs

_(filled in when started)_
