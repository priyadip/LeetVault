# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - 2026-08-04

### Added

- `login` now live-checks each credential and **only prompts for what's actually missing or
  expired**. LeetCode cookies (which roll over every ~14 days) and the GitHub PAT fail
  independently, so refreshing one no longer means re-entering the other. If both are still
  valid, `login` prompts for nothing.
- `login --leetcode` / `login --github` to target one credential explicitly, and `login
  --force` to re-prompt for everything regardless of validity.

### Changed

- `status` now live-validates the stored GitHub PAT (reporting the account it belongs to, or
  that it was revoked) instead of only reporting whether one is present.

## [0.2.0] - 2026-08-04

### Added

- Topic tags in the generated README dashboard are now clickable. Each tag links to a new
  "Problems by Topic" section listing every problem carrying that topic (with difficulty and a
  link to the stored solution), and each section links back up to the topic list. Anchors follow
  GitHub's own heading-slug rules, so names like `Heap (Priority Queue)` and `Depth-First
  Search` resolve correctly.

## [0.1.2] - 2026-07-11

### Fixed

- `leetvault config dedup_window_seconds 0` (intended as a persistent alternative to typing
  `--keep-all` every run) silently did nothing - the fallback `raw or 86400` treated an
  explicit `0` the same as "unset". Fixed to check for `None` explicitly.

### Docs

- Clarified that `--keep-all` only affects future processing and cannot retroactively recover
  a submission an earlier run already deduped; added recovery guidance to
  docs/TROUBLESHOOTING.md and docs/FAQ.md.

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

[Unreleased]: https://github.com/priyadip/LeetVault/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/priyadip/LeetVault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/priyadip/LeetVault/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/priyadip/LeetVault/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/priyadip/LeetVault/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/priyadip/LeetVault/releases/tag/v0.1.0
