# Developer guide

## Setup

```bash
git clone https://github.com/leetvault/leetvault.git
cd leetvault
pip install -e ".[dev]"
```

This installs leetvault in editable mode plus the dev toolchain (pytest, ruff, mypy, respx).

## Project layout

```
src/leetvault/
  cli.py       Typer app; each command lazily imports and calls a run_* function
  config.py    non-secret persistent config (JSON under the OS config dir)
  auth.py      keyring-backed credential storage, JWT expiry decode, login/status/logout
  client.py    the only module that talks HTTP to LeetCode (REST + GraphQL)
  models.py    SQLAlchemy 2.0 declarative models
  db.py        engine/session factory, SyncState helpers
  sync.py      import (full history) + sync (incremental) engines
  git_writer.py  disk layout writer + git commit/push (transient PAT)
  readme.py    stats aggregation + Jinja2 README rendering
  watch.py     polling loop around sync()
  templates/   Jinja2 templates (README.md.j2)
tests/         mirrors src/leetvault/ one test module per source module, plus conftest.py
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow and any place live API behavior
diverged from what was originally assumed.

## Running checks

```bash
pytest                    # unit tests, mocked HTTP (respx) - no live credentials needed
ruff check .               # lint
ruff format --check .      # formatting
mypy --strict               # type check (src/leetvault only, see pyproject.toml)
```

All four must be clean before a commit lands, per the project's working protocol in
`CLAUDE.md`.

## Test isolation

`tests/conftest.py` provides two autouse fixtures for every test in the suite:

- an in-memory fake `keyring` backend (nothing ever touches the real OS credential store)
- `APPDATA`/`LOCALAPPDATA`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME` redirected into `tmp_path`
  (nothing ever touches the real `%APPDATA%\leetvault` / `~/.config/leetvault`)

Never bypass these to test against real credentials or real config state - if you need to
verify something against the live LeetCode API or a real GitHub repo, do it manually outside
the test suite (see "Live smoke testing" below).

## Live smoke testing

Most of this project's genuinely tricky bugs were only found by actually running the tool
against a real LeetCode account and a real GitHub repo (see `PLAN.md` for the specifics - a
Windows console Unicode crash, a `sync_state` finalization gap, and a stranded-commit bug all
surfaced this way, none of them via the mocked test suite alone). If you're changing
`client.py`, `sync.py`, or `git_writer.py`, consider:

```bash
leetvault login     # stores real credentials in your OS keyring
leetvault import    # full history, real API calls
leetvault config repo_url https://github.com/you/your-repo.git
leetvault sync       # exercises the git commit/push path for real
```

## Adding a new LeetCode API field

1. Add the field to the relevant dataclass/query in `client.py` - this is the only module
   allowed to shape LeetCode's HTTP responses.
2. If it changes the DB schema, update `models.py` and add a round-trip test in
   `tests/test_models.py`.
3. Verify the exact field shape live (see above) before locking it in - LeetCode's API is
   entirely reverse-engineered; nothing here is officially documented, and past assumptions
   have been wrong in specific, non-obvious ways (see `docs/ARCHITECTURE.md`'s "Divergences
   from CLAUDE.md" section).
4. Record what you found - live-verified vs. assumed - in `docs/ARCHITECTURE.md`.
