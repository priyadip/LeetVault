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

None yet. Any place where live API reality (Phase 2) diverges from CLAUDE.md's assumed field
shapes will be recorded here with the actual behavior and the adaptation made.
