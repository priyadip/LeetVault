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

_(filled in when started)_

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
