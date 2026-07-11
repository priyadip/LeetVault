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

See CLAUDE.md's "Data model (SQLite)" section for the authoritative schema; `models.py` is the
literal source of truth once Phase 1 lands.

## Divergences from CLAUDE.md

Live-verified against the real account (`priyadipsau`) during Phase 2:

- **`LEETCODE_SESSION` has no `exp` claim.** CLAUDE.md says "Decode the JWT `exp`"; the real
  payload instead carries `refreshed_at` (unix seconds) and `_session_expiry` (a relative TTL in
  seconds — observed as `1209600` = 14 days). `auth.decode_session_expiry` computes
  `refreshed_at + _session_expiry`, falling back to a literal `exp` claim if one is ever present.
- **`submissionDetails.runtime`/`.memory` are unformatted numbers, not display strings.**
  REST `/api/submissions/` gives pre-formatted strings (`"2956 ms"`, `"711.2 MB"`); GraphQL
  `submissionDetails` gives raw numbers (`runtime: 2956` = milliseconds, `memory: 711172000` =
  bytes). `SubmissionDetail.runtime`/`.memory` are typed `int | None` accordingly. This doesn't
  affect the DB schema — `submissions.runtime`/`.memory` are sourced from REST's formatted
  strings per CLAUDE.md, and `submissionDetails` is only consulted for the percentile fields
  (`runtimePercentile`/`memoryPercentile`, both floats, confirmed) plus `code`/`lang.name` as a
  fallback when REST's `code` is absent.
- **Everything else matches assumptions**: `userStatus.{username,isSignedIn}`,
  `recentAcSubmissionList` items (`id`, `title`, `titleSlug`, `timestamp`), and every REST
  `submissions_dump` field (`id`, `question_id`, `title`, `title_slug`, `status_display`, `lang`,
  `runtime`, `memory`, `timestamp`, `url`, `code`, top-level `has_next`/`last_key`) came back
  exactly as coded in `client.py` on the first live call — no further changes needed there.
- **`/api/problems/all/` (not named in CLAUDE.md) supplies the fields REST's submissions dump
  lacks.** `stat_status_pairs[].{stat.question_id, stat.frontend_question_id,
  stat.question__title, stat.question__title_slug, difficulty.level, paid_only}` — confirmed
  live, ~4000 problems in one response. `client.get_all_problems()` maps `difficulty.level`
  1/2/3 to `Easy`/`Medium`/`Hard`.
- **A live `import` + `sync` smoke run against the real account surfaced two real bugs** (both
  fixed, both regression-tested where the fix is unit-testable — see PLAN.md Phase 3 for
  detail): (1) `rich`'s progress bar crashed on this Windows console's cp1252 codepage via
  rich's legacy Win32 console render path; (2) `run_import` could finalize `sync_state` with a
  completed-import flag but a null `last_submission_id` if the run resumed onto an
  already-fully-paged (empty) page, permanently breaking `sync`. Neither was caught by the
  mocked test suite alone — both only surfaced by actually running the tool.
- **Topic tags require a query CLAUDE.md never named**: `GraphQL question(titleSlug) {
  topicTags { name } }` — live-verified, works, returns `[{name, slug}]` (slug unused). Wired
  into `sync.py` as a once-per-newly-seen-problem enrichment call, same failure-tolerance
  pattern as `submissionDetails`.
- **A live GitHub push surfaced a real bug in the git layer** (see PLAN.md Phase 4): an initial
  push failed with a genuine 403 (PAT permissions, user-side, not a code issue — confirmed our
  error handling was correct: clean scrubbed message, no leak), but the commit it made *before*
  failing was left stranded, since the old `sync_to_github` only pushed inside the
  "just committed" branch. Fixed to always attempt a push whenever any local commit exists.
