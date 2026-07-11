# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.1] - 2026-07-11

### Fixed

- Resolving an already-synced problem again later (even the same day) was silently dropped
  forever, and `latest.py` never updated past the first submission `sync` ever saw for that
  problem. The dedup window check used raw subtraction, which goes negative - and therefore
  always looks "within the window" - for any submission newer than the previously-kept one
  seen in an earlier run. Separately, "should this update `latest.py`" was gated on a
  once-ever check that could never re-trigger after the first sync of a problem. Both fixed:
  dedup now compares the absolute time difference, and "is this the latest" is a genuine
  newest-timestamp comparison that updates as submissions are processed.

## [0.1.0] - 2026-07-11

Initial release.

- `login`/`logout`/`status`: keyring-backed LeetCode session storage, live session validation,
  JWT expiry decoding, optional GitHub PAT storage.
- `import`/`sync`: resumable full-history import and incremental sync of accepted submissions,
  same-day dedup (`--keep-all` to disable), REST + GraphQL enrichment.
- Git layer: batched commit + transient-PAT push per run, never persisted to `.git/config`.
- Auto-generated README dashboard: progress, difficulty/language/topic breakdowns, streaks,
  recent solves, full searchable solutions table.
- `watch`: polling loop with graceful shutdown and session-expiry warnings.
- `config`: get/set persistent settings.

[Unreleased]: https://github.com/priyadip/LeetVault/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/priyadip/LeetVault/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/priyadip/LeetVault/releases/tag/v0.1.0
