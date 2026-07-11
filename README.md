# leetvault

Mirror your LeetCode account (accepted submissions + source code + metadata) into a normalized
SQLite database and a GitHub repository with an auto-generated README dashboard.

Sync is **account-based**, driven by your authenticated LeetCode session — not a browser
extension. Your LeetCode account is the single source of truth. Free and open source; the only
external services involved are LeetCode and GitHub.

## Install

```bash
pip install leetvault
```

Requires Python 3.11+. See [docs/DEVELOPER.md](docs/DEVELOPER.md) for an editable/dev install.

## Quickstart

```bash
leetvault login                                          # paste LEETCODE_SESSION + csrftoken
leetvault config repo_url https://github.com/you/repo.git # optional: enable GitHub push
leetvault import                                          # one-time full history
leetvault sync                                             # incremental, run anytime
leetvault watch                                             # or: poll automatically
```

## Commands

- `leetvault login` — store your `LEETCODE_SESSION` + `csrftoken` (and optionally a GitHub PAT)
  in the OS keyring.
- `leetvault import [--keep-all]` — full history import of every accepted submission
  (resumable, one-time per site).
- `leetvault sync [--keep-all]` — incremental sync of new accepted submissions since the last
  run.
- `leetvault watch` — poll LeetCode and sync automatically (`--interval`, default 90s).
- `leetvault status` — show session validity/expiry and sync state.
- `leetvault logout` — remove stored credentials.
- `leetvault config` — get/set persistent configuration (repo URL, DB path, dedup window, ...).

### `--keep-all`

By default, `import`/`sync` keep only the **newest** accepted submission per problem within a
rolling 24-hour window (`dedup_window_seconds` in `leetvault config`, default `86400`) — solving
the same problem twice in one sitting doesn't clutter history with near-duplicate attempts.
`--keep-all` disables that and stores every accepted submission individually:

```bash
leetvault sync --keep-all      # one-off: keep everything from this run onward
leetvault import --keep-all    # same, for the initial full-history import
```

To make this the permanent default instead of retyping the flag every time:

```bash
leetvault config dedup_window_seconds 0
```

`--keep-all` only changes how *future* submissions are processed — it can't retroactively
recover a submission an earlier (non-`--keep-all`) run already deduped, since `sync` only walks
forward from the last submission it saw. See
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#i-solved-a-problem-again-but-github-still-only-shows-the-old-solution)
if you hit that.

## What gets stored

A normalized SQLite database (problems, submissions, source code, topics, sync state) plus a
disk layout per problem:

```
Problems/<slug>/
  latest.<ext>          the most recent accepted submission
  history/submission_<id>.<ext>   every kept accepted submission
  metadata.json          difficulty, topics, runtime/memory percentiles, ...
  notes.md                yours - never overwritten once created
README.md                 auto-generated dashboard: progress, streaks, full solutions table
```

Deduplicated by default within a 24h window — see [`--keep-all`](#--keep-all) above to change
that.

## Honest limits

- `watch` is polling (default 90s, configurable), not a real-time push — LeetCode has no public
  webhook/streaming API.
- LeetCode may Cloudflare-challenge automated HTTP clients; leetvault fails gracefully rather
  than faking success.
- Storing session cookies for automated access may be against LeetCode's Terms of Service. Use
  at your own risk, against your own account only.
- LeetCode has no official API — every endpoint leetvault uses is reverse-engineered and could
  change without notice.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — data flow, module responsibilities, and every
  place live API behavior diverged from initial assumptions.
- [docs/DEVELOPER.md](docs/DEVELOPER.md) — dev setup, project layout, running checks.
- [docs/FAQ.md](docs/FAQ.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CHANGELOG.md](CHANGELOG.md)

## License

MIT — see [LICENSE](LICENSE).
