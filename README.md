# leetvault

Mirror your LeetCode account (accepted submissions + source code + metadata) into a normalized
SQLite database and a GitHub repository with an auto-generated README dashboard.

Sync is **account-based**, driven by your authenticated LeetCode session — not a browser
extension. Your LeetCode account is the single source of truth. Free and open source; the only
external services involved are LeetCode and GitHub.

> Status: under active development. See [PLAN.md](PLAN.md) and
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions and progress.

## Install

```bash
pip install -e ".[dev]"
```

## Commands

- `leetvault login` — store your `LEETCODE_SESSION` + `csrftoken` (and optionally a GitHub PAT)
  in the OS keyring.
- `leetvault import` — full history import of every accepted submission (resumable).
- `leetvault sync` — incremental sync of new accepted submissions since the last run.
- `leetvault watch` — poll LeetCode and sync automatically.
- `leetvault status` — show session validity/expiry and sync state.
- `leetvault logout` — remove stored credentials.
- `leetvault config` — get/set persistent configuration.

## Honest limits

- `watch` is polling (60-120s), not a real-time push — LeetCode has no public webhook/streaming
  API.
- LeetCode may Cloudflare-challenge automated HTTP clients; leetvault fails gracefully rather than
  faking success.
- Storing session cookies for automated access may be against LeetCode's Terms of Service. Use at
  your own risk, against your own account only.

## Development

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy --strict
pytest
```
