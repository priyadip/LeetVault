# Developer guide

## Setup

```bash
git clone https://github.com/priyadip/LeetVault.git
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
  htmlmd.py    LeetCode's question.content (HTML) -> Markdown, at sync time
  ai_setup.py  `leetvault ai`: detect AI backends, choose one, or turn it off
  analyze.py   `leetvault analyze`: redo one analysis with a different model
  ask.py       `leetvault ask`: a question about one problem, answered and logged
  bot.py       `leetvault bot`: a GitHub Actions workflow that answers issues
  site.py      `leetvault site`: a browsable GitHub Pages site for the repo
  commands.py  `leetvault commands`: every command, generated from the CLI itself
  templates/   Jinja2 templates (README.md.j2) and the site's own
               HTML/CSS/JS under templates/site/
tests/         mirrors src/leetvault/ one test module per source module, plus conftest.py
  fixtures/    boot_page.mjs (DOM stub), github_markdown.json (GitHub's own rendering)
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

All four must be clean before a commit lands.

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
against a real LeetCode account and a real GitHub repo (see `docs/ARCHITECTURE.md` for the
specifics - a Windows console Unicode crash, a `sync_state` finalization gap, and a
stranded-commit bug all surfaced this way, none of them via the mocked test suite alone). If
you're changing `client.py`, `sync.py`, or `git_writer.py`, consider:

```bash
leetvault login     # stores real credentials in your OS keyring
leetvault import    # full history, real API calls
leetvault config repo_url https://github.com/you/your-repo.git
leetvault sync       # exercises the git commit/push path for real
```

## The page must render like GitHub

`templates/site/assets/app.js` contains a hand-written Markdown renderer and syntax
highlighter - no CDN, no build step. The specification it is written against is not a Markdown
standard in the abstract but **GitHub's own output for the same file**, because every problem
page on the site links to that file on GitHub and the two disagreeing reads as one of them
being broken.

Two tests enforce this, both requiring `node` on PATH and skipping without it:

- `test_markdown_matches_github_on_recorded_samples` renders 35 constructs with the real
  `app.js` and compares them against `tests/fixtures/github_markdown.json`, which holds
  GitHub's own output for each. No network.
- `tests/fixtures/boot_page.mjs` boots the real page against a DOM stub strict enough to catch
  a detached-element lookup, on every route.

### Regenerating the fixture

Needed when you add a construct, or to confirm GitHub has not changed. Requires `gh`
authenticated - it posts each sample to GitHub's `/markdown` endpoint:

```bash
python tests/fixtures/gen_github_markdown.py > tests/fixtures/github_markdown.json
python -m pytest tests/test_site.py -q
```

Add samples to `SAMPLES` in that script. Take them from real files rather than inventing them:
every entry currently there came out of a synced repository, overlapping emphasis runs and all,
which is why the fixture is evidence rather than a guess.

### Checking against a whole repository

The fixture is a sample. To check the renderer against every file in a real solutions repo,
render each one with `app.js` and compare it to GitHub's rendering of the same bytes, reducing
both to the tags and text a reader perceives - drop attributes, collapse whitespace, treat
`<pre>` as one blob, and ignore GitHub's heading permalinks and `tbody` (every parser inserts a
`tbody`, so its presence in the string is not something a reader can perceive). `_shape()` in
`tests/test_site.py` is that reduction, and the fixture test shows the shape of the comparison.

This needs the network and a populated repository, so it is a thing you run deliberately rather
than something CI can do. The renderer currently agrees with GitHub on all 446 `question.md`,
`analysis.md` and `notes.md` files of a 149-problem repository.

### If you change the renderer

- Keep the module-level constants inside the `/* ---------- Markdown` section: both node tests
  slice the file from that banner to `/* ---------- fetching`, so anything they need must live
  between the two.
- Rebuild every tag from its name. Never pass an attribute through except `href` on `<a>` and
  `src` on `<img>`, and only after `safeUrl` accepts it - `analysis.md` is model-generated and
  `notes.md` is free-form, so both are untrusted input for this purpose.
- The file is plain ASCII on purpose. The sentinel the inline pass uses is a NUL built with
  `String.fromCharCode(0)` rather than written as an escape, and regular expressions prefer
  `[0-9]` to a backslash class where it costs nothing.

## Adding a new LeetCode API field

1. Add the field to the relevant dataclass/query in `client.py` - this is the only module
   allowed to shape LeetCode's HTTP responses.
2. If it changes the DB schema, update `models.py` and add a round-trip test in
   `tests/test_models.py`.
3. Verify the exact field shape live (see above) before locking it in - LeetCode's API is
   entirely reverse-engineered; nothing here is officially documented, and past assumptions
   have been wrong in specific, non-obvious ways (see `docs/ARCHITECTURE.md`'s notes on
   building against the live API).
4. Record what you found - live-verified vs. assumed - in `docs/ARCHITECTURE.md`.
