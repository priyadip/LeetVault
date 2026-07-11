# Contributing

Thanks for considering a contribution to leetvault.

## Before you start

- For anything beyond a small fix, open an issue first to discuss the approach - especially
  for anything touching `client.py` (LeetCode's API is entirely reverse-engineered; changes
  there need live verification, see [docs/DEVELOPER.md](docs/DEVELOPER.md)).
- This project is free/open-source and intentionally scoped to LeetCode + GitHub as its only
  external services. PRs adding new third-party services are unlikely to be accepted.

## Workflow

1. Fork and branch from `main`.
2. Install dev dependencies: `pip install -e ".[dev]"`.
3. Make your change. Match the existing style: full type hints, no comments unless they
   explain a non-obvious *why*, no speculative abstraction.
4. Before opening a PR, all of these must be clean:
   ```bash
   pytest
   ruff check .
   ruff format --check .
   mypy --strict
   ```
5. Write a [Conventional Commit](https://www.conventionalcommits.org/) message
   (`feat: ...`, `fix: ...`, `docs: ...`, etc.).
6. Open a PR against `main`. CI runs the full matrix (Ubuntu/Windows/macOS × Python 3.11-3.13)
   plus lint/type-check on every PR.

## Reporting bugs

Open a GitHub issue with:

- your OS and Python version
- the command you ran and its full output (`leetvault --help` output plus the failing command)
- **never include your `LEETCODE_SESSION`, `csrftoken`, or GitHub PAT** in an issue - those are
  credentials, not debug info

## Security

leetvault stores your LeetCode session cookies and GitHub PAT via the OS keyring, never in
plaintext files, `.env`, `.git/config`, logs, or commits. If you find a way those could leak,
please report it privately rather than opening a public issue - see
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for how credentials are handled.
