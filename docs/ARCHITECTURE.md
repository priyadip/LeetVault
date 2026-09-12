# Architecture

## Overview

```
leetvault CLI (Typer)
   |
   +-- auth.py     -- keyring-backed credential storage, JWT exp decode, session validation
   +-- client.py   -- httpx client: LeetCode REST + GraphQL, rate limiter, retry/backoff
   +-- config.py   -- non-secret persistent config (JSON under OS config dir)
   +-- models.py   -- SQLAlchemy 2.0 declarative models
   +-- db.py       -- engine/session factory, create_all, SyncState helpers
   +-- sync.py     -- import (full history, resumable) + sync (incremental) engines
   +-- git_writer.py -- disk layout writer, commit rendering, transient-PAT push
   +-- readme.py   -- Jinja2 dashboard README generation from DB stats
   +-- watch.py    -- polling loop: sync -> write -> README -> commit -> push
   +-- htmlmd.py   -- LeetCode's question.content (HTML) -> Markdown, at sync time
   +-- ai_setup.py -- `leetvault ai`: detect AI backends, choose one, or turn it off
   +-- analyze.py  -- `leetvault analyze`: redo one analysis with a different model
   +-- ask.py      -- `leetvault ask`: a question about one problem, answered and logged
   +-- bot.py      -- `leetvault bot`: a GitHub Actions workflow that answers issues
   +-- site.py     -- `leetvault site`: a browsable GitHub Pages site for the repo
   +-- commands.py -- `leetvault commands`: every command, generated from the CLI itself
```

Every LeetCode network access is isolated behind `client.py` — no other module talks HTTP
directly. This keeps the reverse-engineered API surface (REST submissions list, GraphQL
`submissionList`/`submissionDetails`, `recentAcSubmissions`) in one place so future breakage is
easy to localize.

## Data flow

1. `login` writes `LEETCODE_SESSION` + `csrftoken` (+ optional GitHub PAT) to the OS keyring via
   `keyring`, service name `leetvault`. Nothing secret touches disk in plaintext.
2. `import`/`sync` drive `client.py` to pull submissions, persist them through `db.py`
   (`problems`, `submissions`, `submission_code`, `topics`/`problem_topics`, `sync_state`), and
   write per-problem files to disk (`Problems/<slug>/...`).
3. `git_writer.py` batches those file changes into commits and pushes using a PAT injected only at
   push time (never written into `.git/config` or the remote URL).
4. `readme.py` re-aggregates stats from the DB and regenerates the dashboard README after every
   sync.
5. `watch.py` repeats step 2-4 on an interval, reconciling `sync_state` each loop.

## Data model

`models.py` is the literal source of truth for the schema:

- `problems` (`question_id` PK, `frontend_id`, `title`, `title_slug`, `difficulty`, `paid_only`,
  `url`)
- `submissions` (`submission_id` PK, `question_id` FK, `lang`, `status`, `runtime`, `memory`,
  `runtime_percentile`, `memory_percentile`, `timestamp`, `code_hash`, `is_accepted`)
- `submission_code` (`submission_id` PK/FK, `code`)
- `topics` + `problem_topics` (M2M)
- `sync_state` (`id`, `site`, `last_offset`, `last_submission_id`, `last_synced_timestamp`,
  `last_full_import_completed_at`)

## The problem statement: one file, two renderers

A LeetCode problem statement arrives as HTML and is read in two places, and keeping those two
places agreeing is a design constraint rather than a detail. Every problem page on the site
links to the same file on GitHub, so if the two render it differently, a reader moving between
them concludes one of them is broken.

```
LeetCode question.content (HTML)
   |
   +-- htmlmd.py ............ HTML -> Markdown, at sync time, on the machine running leetvault
   |      |
   |      v
   |   Problems/<slug>/question.md   (committed; also analysis.md, notes.md)
   |      |
   |      +--> GitHub renders it .................... github.com/<you>/<repo>
   |      |
   |      +--> templates/site/assets/app.js renders it .... <you>.github.io/<repo>/
```

`htmlmd.py` handles exactly the tag vocabulary LeetCode's `question.content` actually uses,
measured across a real account rather than guessed. Most of it becomes real Markdown, so the
file stays readable in an editor and in `git diff`. `<table>` is the exception it passes
through as raw HTML, because Markdown has no syntax for a table that came from HTML and
flattening one loses data.

The renderer in `app.js` is hand-written for the same reason the syntax highlighter is: no
CDN and no build step, so a repository that still exists in five years still renders. That
choice puts the burden of correctness on this project, and the way that burden is discharged
is to treat **GitHub's own output as the specification** rather than a Markdown spec in the
abstract.

### What the renderer commits to

- **Tags are rebuilt, never passed through.** A tag is re-emitted from its name alone, so no
  attribute survives - which is what leaves no room for an `onerror=` in an `analysis.md` that
  a model wrote or a `notes.md` that anyone with push access can edit. Attributes are stripped
  rather than treated as disqualifying, because LeetCode's own tables carry
  `style="border: 1px solid black;"` and refusing those tags would put the raw markup back on
  screen.
- **`<a>` and `<img>` are the two exceptions**, because for them the attribute *is* the
  content. Each keeps exactly one - its `href` or `src` - and only the one `safeUrl` accepts:
  http, https, mailto, a fragment, or a relative path with no scheme at all. `javascript:`
  never reaches the document.
- **A tag GitHub does not permit is dropped, with its text kept** - which is what GitHub's own
  sanitizer does with it.
- **Emphasis uses CommonMark's delimiter-run algorithm**, not a chain of patterns. This is not
  gold-plating: LeetCode's statements contain overlapping runs such as
  `*the **lexicographically smallest* *subsequence** of*`, and a pattern chain closes those in
  the wrong order and emits tags that cross.

### How the claim is checked

GitHub's `/markdown` endpoint renders a file the same way github.com does, which makes it
usable as an oracle. Both sides are reduced to the sequence of tags and text a reader actually
perceives - attributes dropped, whitespace collapsed, `<pre>` treated as one blob, GitHub's
heading permalinks and `tbody` ignored (every parser inserts a `tbody`, so whether the string
carries one is not something a reader can perceive).

Against a real synced repository of 149 problems - all 446 `question.md`, `analysis.md` and
`notes.md` files - the two agree on every file.

That check needs the network, so it cannot run in CI. `tests/fixtures/github_markdown.json`
records GitHub's output for 35 constructs drawn from those same files, and a test in
`tests/test_site.py` holds the renderer to it with no network at all. Regenerate it with
`tests/fixtures/gen_github_markdown.py` when a construct is added; see `docs/DEVELOPER.md`.

### What that comparison taught, that a specification would not have

- **GitHub's sanitizer drops `<u>`.** It is not on GitHub's tag allowlist, so a subsequence
  LeetCode underlines is *not* underlined on github.com - it renders as plain text. `htmlmd.py`
  passes `<u>` through on the assumption GitHub renders it; GitHub does not, and the site
  matches GitHub rather than the assumption.
- **A GFM table does not end at its last row.** It ends at a blank line or the start of another
  block, so a trailing `Result: 5.` written under a table becomes one more row, padded out to
  the header's width. Several analyses are written exactly that way.
- **A list marker indented four spaces is not a list.** With a paragraph open it is a lazy
  continuation of it, which is how the nested steps in several analyses are written.
- **GitHub Pages serves assets with `max-age=600`.** Without a content hash in the URL a
  visitor keeps running the previous script for ten minutes after an update, which looks
  exactly like the update not working. `asset_version()` makes a changed script a changed URL.

## Notes from building against the live, undocumented LeetCode API

LeetCode has no official API, so every field shape below was confirmed by actually calling the
endpoint against a real account rather than assumed:

- **`LEETCODE_SESSION`'s JWT has no `exp` claim.** It instead carries `refreshed_at` (unix
  seconds) and `_session_expiry` (a relative TTL in seconds — observed as `1209600` = 14 days).
  `auth.decode_session_expiry` computes `refreshed_at + _session_expiry`, falling back to a
  literal `exp` claim if one is ever present.
- **`submissionDetails.runtime`/`.memory` (GraphQL) are unformatted numbers, not display
  strings.** REST `/api/submissions/` gives pre-formatted strings (`"2956 ms"`, `"711.2 MB"`);
  GraphQL `submissionDetails` gives raw numbers (`runtime: 2956` = milliseconds,
  `memory: 711172000` = bytes). `SubmissionDetail.runtime`/`.memory` are typed `int | None`
  accordingly. This doesn't affect the DB schema — `submissions.runtime`/`.memory` are sourced
  from REST's formatted strings, and `submissionDetails` is only consulted for the percentile
  fields (`runtimePercentile`/`memoryPercentile`, both floats) plus `code`/`lang.name` as a
  fallback when REST's `code` is absent.
- **Everything else in the REST/GraphQL surface matched on the first live call**:
  `userStatus.{username,isSignedIn}`, `recentAcSubmissionList` items (`id`, `title`,
  `titleSlug`, `timestamp`), and every REST `submissions_dump` field (`id`, `question_id`,
  `title`, `title_slug`, `status_display`, `lang`, `runtime`, `memory`, `timestamp`, `url`,
  `code`, top-level `has_next`/`last_key`).
- **`/api/problems/all/` supplies the fields REST's submissions dump lacks**
  (`difficulty`/`paid_only`/`frontend_id`). `stat_status_pairs[].{stat.question_id,
  stat.frontend_question_id, stat.question__title, stat.question__title_slug, difficulty.level,
  paid_only}` — confirmed live, ~4000 problems in one response. `client.get_all_problems()` maps
  `difficulty.level` 1/2/3 to `Easy`/`Medium`/`Hard`.
- **Topic tags come from `GraphQL question(titleSlug) { topicTags { name } }`** — not part of
  either endpoint above. Wired into `sync.py` as a once-per-newly-seen-problem enrichment call,
  same failure-tolerance pattern as `submissionDetails`.
- **A live `import` + `sync` smoke run against a real account surfaced two real bugs**, neither
  caught by the mocked test suite alone: (1) `rich`'s progress bar crashed on a Windows
  console's cp1252 codepage via rich's legacy Win32 console render path (fixed by forcing UTF-8
  + `legacy_windows=False` in `cli.py`); (2) `run_import` could finalize `sync_state` with a
  completed-import flag but a null `last_submission_id` if the run resumed onto an
  already-fully-paged (empty) page, permanently breaking `sync` (fixed by falling back to the
  DB's true newest submission when the run itself saw none).
- **A live GitHub push surfaced a real bug in the git layer**: an initial push attempt failed
  with a genuine 403 (a PAT permissions issue, not a code issue — confirmed the error handling
  itself was correct: a clean scrubbed message, no PAT leaked), but the commit it made *before*
  failing was left stranded, since `sync_to_github` originally only pushed inside the
  "just committed" branch. Fixed to always attempt a push whenever any local commit exists.
- **Real-world usage surfaced a dedup bug**: resolving an already-synced problem again later
  (even the same day) was silently dropped forever, and `latest.py` never updated past the
  first submission `sync` ever saw for that problem. Root cause: the dedup window check
  compared `known_latest_timestamp - sub.timestamp < dedup_window_seconds` — correct only
  when processing strictly newest-first *within a single run*, where the previously-kept
  timestamp is always >= the one being compared. But `known_latest_timestamp` is seeded from
  the DB at the start of every run, and a genuinely newer submission arriving in a *later* run
  makes that subtraction go negative — and a negative number is always less than the window,
  so it always looked deduplicable, forever, regardless of how much time had actually passed.
  Separately, "should this become `latest.py`" was gated on "have I never seen this
  question_id in `last_kept` before," which — once seeded from the DB — is permanently false,
  so `latest.py` could never be updated again even after fixing the timestamp math. Fixed both:
  dedup now compares `abs(known_latest_timestamp - sub.timestamp)`, and "is this the latest"
  is now a genuine `sub.timestamp > known_latest_timestamp` comparison that updates as new
  submissions are processed, so the truly newest solve always wins regardless of which run
  (import or a later sync) first encounters the problem.
