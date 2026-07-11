# Troubleshooting

## `leetvault status` says my session is invalid or expired

Your `LEETCODE_SESSION` cookie has a rolling ~14-day expiry (observed live; LeetCode doesn't
publish this). Run `leetvault login` again with fresh cookie values from a signed-in
`leetcode.com` browser session (DevTools -> Application -> Cookies -> `LEETCODE_SESSION` and
`csrftoken`).

## `login` fails with "Login validation failed"

This means the cookies you pasted didn't produce a signed-in session when checked live against
LeetCode's GraphQL `userStatus` query. Common causes:

- Cookie values were copied with extra whitespace or truncated mid-paste (a `LEETCODE_SESSION`
  JWT has three `.`-separated segments - if yours has fewer, it was cut off).
- You copied cookies from a logged-out session, or from `leetcode.cn` while running
  `--site com` (or vice versa).
- LeetCode's Cloudflare challenge intercepted the request. leetvault doesn't attempt to solve
  Cloudflare challenges - if this happens repeatedly, wait and retry, or fetch cookies from a
  fresh browser session.

## `import`/`sync` fails with a 403 or 429

leetvault backs off automatically (1s -> 3s -> 9s -> 27s, honoring `Retry-After` if LeetCode
sends one) and stays under a conservative request-rate ceiling. If you still see persistent
403s:

- Your session may have expired mid-run - check `leetvault status`.
- LeetCode's rate limits are undocumented and can change; if this becomes a recurring problem,
  please open an issue with the command output.

## Git push fails with a 403 / "Permission denied"

Your GitHub PAT doesn't have write access to the target repo. For a fine-grained PAT, check:

- **Repository access**: the target repo must be explicitly selected (not just "Public
  Repositories").
- **Permissions -> Contents**: must be **Read and write**, not Read-only.

The error message is always scrubbed of the raw PAT value before being printed, so it's safe
to paste into a bug report.

## A push succeeded but I don't see the commit on GitHub

Check `leetvault status` and the target repo's default branch - leetvault always pushes to
`main`. If your repo's default branch is named something else (e.g. `master`), the push will
still succeed (creating/updating a `main` branch), but it won't be what GitHub shows by
default. Rename the branch on GitHub or set `main` as the target repo's default.

## `watch` doesn't seem to notice a new solve

`watch` polls, it doesn't get pushed notifications - a fresh solve is picked up within one
`--interval` window, not instantly. If a full interval has passed with no update, check
whether the terminal running `watch` printed an error (a failed cycle is logged and retried,
not silent) and confirm `leetvault status` still reports a valid session.

## Windows: garbled progress bar / crash mentioning `cp1252`

This was a real bug in early development (fixed): rich's progress bar could try to render
Unicode through a legacy Win32 console code path that only supports the system codepage. If
you still see this, you're likely running a very old leetvault build - please upgrade.

## Where do I check what leetvault has stored?

- Credentials: OS keyring under service `leetvault` (not a file you can just `cat` - use your
  OS's credential manager UI, or `leetvault status`/`leetvault logout`).
- Non-secret config: `leetvault config` (no arguments) prints everything, including the
  resolved DB and repo paths.
- Sync state / submissions: `leetvault status`, or inspect the SQLite DB directly at the path
  `leetvault config db_path` reports.
