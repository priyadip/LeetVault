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
- `leetvault import` — full history import of every accepted submission (resumable, one-time
  per site).
- `leetvault sync` — incremental sync of new accepted submissions since the last run.
- `leetvault watch` — poll LeetCode and sync automatically (`--interval`, default 90s).
- `leetvault status` — show session validity/expiry and sync state.
- `leetvault logout` — remove stored credentials.
- `leetvault config` — get/set persistent configuration (repo URL, DB path, dedup window, ...).

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

By default, same-day accepted submissions for the same problem are deduplicated (only the
newest is kept); pass `--keep-all` to `import`/`sync` to disable that.

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
