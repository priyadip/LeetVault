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

_(filled in when started)_

## Phase 4 — Git

_(filled in when started)_

## Phase 5 — README

_(filled in when started)_

## Phase 6 — Watch

_(filled in when started)_

## Phase 7 — Packaging/CI/docs

_(filled in when started)_
