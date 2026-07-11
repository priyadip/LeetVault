# CLAUDE.md — leetvault

Project memory for Claude Code (auto-loaded each session). This file is authoritative. Keep the **Phase checklist** at the bottom updated as work completes.

## What this is
`leetvault` — a cross-platform (Windows/Linux/macOS) Python CLI that mirrors *my* LeetCode account (accepted submissions + source code + metadata) into a normalized SQLite DB and a GitHub repo with an auto-generated README dashboard. Sync is **account-based** via my authenticated session — never browser-dependent. My LeetCode account is the single source of truth. Free/OSS only; the only external services are LeetCode and GitHub.

## v1 scope
Commands: `login`, `import` (full history), `sync` (incremental), `watch` (polling), `status`, `logout`, `config`. Plus SQLite persistence, GitHub commit/push, auto-generated README, PyPI packaging + CI.
**NOT in v1** (leave `# FUTURE:` notes only, build nothing): browser extension, AI/weak-topic dashboard, standalone binaries, deep contest analytics.

## Ground-truth API facts — do NOT re-derive; verify exact field shapes live in Phase 2
LeetCode has no official API — every endpoint is reverse-engineered. Isolate all LeetCode access behind one client module.

**Auth**
- Cookies `LEETCODE_SESSION` (a JWT) + `csrftoken`; I paste them at `login`. No password flow.
- Every authed request sends: both cookies + header `x-csrftoken: <csrftoken>` + `Referer: https://leetcode.com`.
- Decode the JWT `exp` for `status` + expiry warnings; don't hardcode a lifetime (varies ~1 wk to several wks).
- Store secrets (both cookies + GitHub PAT) via **`keyring`**, service name `leetvault`. Never in `.env`, `.git/config`, logs, or commits.

**Fetching**
- Full history → REST `https://leetcode.com/api/submissions/?offset=0&limit=20` (20/page; includes `code`, `id`, `question_id`, `title`, `title_slug`, `status_display`, `lang`, `runtime`, `memory`, `timestamp`, `url`; top-level `has_next`/`last_key`). Prefer for bulk — code + metadata in one pass.
- Enrichment/fallback → GraphQL `https://leetcode.com/graphql`: `submissionList(offset,limit,questionSlug)` + `submissionDetails(submissionId)` (code, runtimePercentile, memoryPercentile). One extra call per submission — use only when REST `code` is missing or percentiles are needed.
- Incremental/watch → `recentAcSubmissions` / `recentSubmissionList` (capped at 20; detection only, useless for history).

**Rate limits (empirical, not published — design defensively)**
- ~480 sequential requests → HTTP 403. Stay under 20 req / 10 s.
- Bulk import: 300–500 ms between pages; exponential backoff 1→3→9→27 s on 403/429; honor `Retry-After`.
- **Import MUST be resumable** — persist last offset / submission id after every page.
- GitHub write API has a **separate** quota — batch/space commits; never one push per submission.
- `--site com|cn` (default `com`); for `cn` swap base URL + stricter limiter (~1 req/10 s).

**Honest limits (state in docs, never fake)**
- `watch` = polling (60–120 s), not real-time (no LeetCode webhook/streaming exists).
- Cloudflare may challenge HTTP clients — fail gracefully; `# FUTURE:` optional Playwright real-browser fetcher.
- Stored-cookie automation may breach LeetCode ToS — neutral README disclaimer.

## Stack (exact)
Typer (+`rich`) · `httpx` + **`httpx-retries`** (NOT `httpx-retry`) + custom rate limiter · SQLAlchemy 2.0 declarative (`DeclarativeBase`/`Mapped`/`mapped_column`/`select`) on SQLite · Jinja2 (`PackageLoader`) · GitPython (PAT injected transiently at push time, never in remote URL / `.git/config`; fine-grained PAT scoped to one repo, Contents: write) · `keyring` · `pytest`+cov / `ruff` / `mypy --strict` · **hatchling** + `src/` layout + entry point `leetvault = "leetvault.cli:app"` · **PyPI Trusted Publishing (OIDC)**. All config in `pyproject.toml`.

## Data model (SQLite)
`problems`(question_id PK, frontend_id, title, title_slug, difficulty, paid_only, url) · `submissions`(submission_id PK, question_id FK, lang, status, runtime, memory, runtime_percentile, memory_percentile, timestamp, code_hash, is_accepted) · `submission_code`(submission_id PK/FK, code) · `topics` + `problem_topics` (M2M) · `sync_state`(id, site, last_offset, last_submission_id, last_synced_timestamp, last_full_import_completed_at).
History: store every accepted submission. Disk layout per problem: `Problems/<slug>/{latest.<ext>, history/submission_<id>.<ext>, notes.md, metadata.json}`. Default dedup = same problem within same day (86400 s); `--keep-all` opts out.

## Working protocol
- **Run continuously.** Execute Phases 0 → 7 end-to-end without pausing for my approval between phases. Never ask "should I proceed / continue / go ahead?" — just proceed. Don't stop per-file.
- Per phase, loop: state what/why in 1–2 lines → build (full type hints, DI, SOLID, clean architecture) → tests green → `ruff check` + `ruff format --check` + `mypy --strict` clean → Conventional Commit → one-line progress note → immediately start the next phase.
- **Only stop to ask me when you need something ONLY I can provide.** In v1 that is exactly two moments: (1) **Phase 2** — my `LEETCODE_SESSION` + `csrftoken` (I paste them into the `login` flow); (2) **Phase 4** — a fine-grained GitHub PAT + target repo URL (for push). Ask once at each, then continue autonomously. Also stop before any irreversible action *outside this repo* (force-push, history rewrite, deleting files you didn't create).
- **Decide, don't ask, for everything else.** For small choices (naming, layout, library minutiae, config defaults) pick the sensible option, record it in `PLAN.md`, and keep moving. Surface a decision only if it's a true one-way door.
- **Verify, don't assume:** confirm real REST + `submissionDetails` fields live in Phase 2 before locking schema; adapt to reality; note any divergence in `PLAN.md`.
- **Never fake functionality** — no stubbed "pretend it worked," no fabricated data, no swallowed errors. If genuinely blocked, say so and propose a real fallback rather than faking or silently skipping.
- Commit after every phase so all work is recoverable via git. Never print or commit secrets. Keep `PLAN.md` + `docs/ARCHITECTURE.md` current as you go.

## Phase checklist (update as completed)
- [x] **0 Scaffold** — `src/` layout, `pyproject.toml` (hatchling + deps + entry + ruff/mypy/pytest), command stubs, CI skeleton, `PLAN.md`, `docs/`. ✔ `pip install -e .` + `leetvault --help` lists all commands.
- [x] **1 Data layer** — models, engine/session factory, `create_all`, `SyncState` helpers, unit tests + temp-DB round-trip.
- [x] **2 Auth + client** — keyring store, httpx client (headers/timeouts/retries/limiter), JWT `exp`, session validation; `login`/`logout`/`status`. Verify live API. ✔ real-account `status` reports validity/expiry.
- [x] **3 Sync engine** — `import` (resumable, throttled, backoff) + `sync` (incremental, stop at last-known id); dedup; DB + `submission_code` + disk files; progress bars; mocked tests + opt-in live smoke. ✔ full import correct + re-run does no redundant work.
- [x] **4 Git** — layout writer, commit-template rendering, transient-PAT batched push. ✔ real push with correct messages, no dupes on re-run.
- [x] **5 README** — Jinja2 templates + stats aggregation (progress, difficulty, topics, langs, streaks, recent, searchable table w/ links, % bars), regenerate-after-sync, aggregation-math tests.
- [x] **6 Watch** — polling loop (`--interval`, 60–120 s), reconcile `SyncState`, run sync→write→README→commit→push on new AC, graceful shutdown, expiry warning. ✔ picks up a fresh solve within one interval.
- [x] **7 Packaging/CI/docs** — finalize `pyproject.toml`; Actions (pytest matrix ubuntu/windows/macos × py3.11–3.13, `fail-fast:false`; ruff + `mypy --strict` on ubuntu; tag-triggered Trusted Publishing `id-token: write`, TestPyPI dry-run first); README + Install + Architecture + Developer + Contribution + FAQ + Troubleshooting. ✔ **Fully done for real, not just locally**: pushed to `github.com/priyadip/LeetVault`, CI green on all 9 OS/Python combinations + lint on GitHub's own runners, `v0.1.0` tag published through the real Trusted Publishing pipeline (TestPyPI then PyPI, both verified live), confirmed `pip install leetvault` works from a clean environment. See PLAN.md Phase 7 for the two real bugs found and fixed along the way (a CI-only test flakiness bug, and a stray `Co-Authored-By: Claude` trailer removed from git history via a verified rewrite + force-push).
