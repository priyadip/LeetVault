# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/leetvault/leetvault/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/leetvault/leetvault/releases/tag/v0.1.0
