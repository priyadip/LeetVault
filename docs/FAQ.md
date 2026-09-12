# FAQ

**Does leetvault use an official LeetCode API?**
No - LeetCode has no public/official API. Every endpoint leetvault uses is reverse-engineered
from the browser's own network traffic, isolated behind `src/leetvault/client.py`. This is
inherently fragile: LeetCode can change these endpoints at any time without notice.

**Is `watch` real-time?**
No. It's polling (default every 90 seconds, configurable via `--interval`). LeetCode has no
webhook or streaming API for submission events, so there is no way to get a true real-time
push notification.

**Will leetvault get my LeetCode account banned?**
Storing session cookies for automated access may be against LeetCode's Terms of Service. Use
this against your own account, at your own risk. leetvault stays under conservative rate
limits (well below the ~480-sequential-request threshold that empirically triggers a 403) and
never does anything but read your own submission history - but the ToS risk itself is not
something leetvault can eliminate.

**My LeetCode session expired but my GitHub PAT is fine - do I have to re-enter both?**
No. `leetvault login` live-checks each credential independently and only prompts for the ones
that are actually missing or expired; anything still valid is left untouched. You can also
target one explicitly with `leetvault login --leetcode` or `leetvault login --github`, or
re-enter everything with `--force`.

**Where are my credentials stored?**
In your OS's native credential store via the `keyring` library (Windows Credential Manager,
macOS Keychain, or a Secret Service provider on Linux), under service name `leetvault`. Never
in a plaintext file, `.env`, `.git/config`, or in a commit.

**Can I sync more than one LeetCode account?**
Not in v1. Credentials are keyed by `--site` (`com`/`cn`), not by account - logging in again
for the same site overwrites the previous session.

**Does it store every submission, or just the latest per problem?**
Every *accepted* submission, deduplicated by default: only the newest accepted submission for
a given problem within a rolling 24-hour window is kept (the exact window is
`dedup_window_seconds` in `leetvault config`, default `86400`). Non-accepted attempts (Wrong
Answer, TLE, etc.) are never stored. `latest.py`/`metadata.json` always reflect whichever
accepted submission for that problem is truly newest, even if it arrives in a later `sync` run
than the one that first stored that problem.

**How do I keep every accepted submission, even near-duplicates minutes apart?**
Pass `--keep-all` to `import`/`sync`, or make it the permanent default with
`leetvault config dedup_window_seconds 0` (so you never have to remember the flag). Note that
`--keep-all` only affects *future* processing - it can't retroactively un-dedupe a submission
that an earlier run (without `--keep-all`) already decided to drop, since `sync` only walks
forward from the last submission it saw. If you turned dedup off *after* losing an earlier
attempt, that specific submission is still on LeetCode and can be recovered, but leetvault has
no built-in command for it in v1 - see
[docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md#i-solved-a-problem-again-but-github-still-only-shows-the-old-solution).

**Why does `import` only run once?**
It's a full-history operation, gated on having completed successfully before. Re-running it is
a safe no-op (it makes zero API calls once completed) rather than redundantly re-walking your
entire history. Use `sync` for picking up new submissions afterward - `import` is a one-time
bootstrap.

**Can I use a personal (classic) GitHub token instead of a fine-grained PAT?**
It'll work as long as it has `repo` scope, but a fine-grained PAT scoped to exactly one
repository with `Contents: Read and write` is strongly recommended - it's the minimum
privilege leetvault actually needs.

**What happens if I revoke my GitHub PAT?**
`sync`/`import`/`watch` will still update your local DB and disk files; the git commit/push
step will fail with a clear error (with the PAT scrubbed from any message) and the tool will
tell you to check `leetvault login` again. Nothing is lost - the next successful run will push
everything, including anything that piled up while the PAT was broken.

**Does the web page show my problems differently from GitHub?**
No, and that is enforced rather than hoped for. `leetvault site` publishes a page whose
Markdown renderer is written against GitHub's own output as its specification, and it matches
GitHub on every `question.md`, `analysis.md` and `notes.md` file of a real 149-problem
repository. A recorded sample of GitHub's rendering lives in
`tests/fixtures/github_markdown.json` so a test can hold the page to it without the network.

**Why is an underlined part of a problem statement not underlined on the page?**
Because it is not underlined on GitHub either. LeetCode marks a matched subsequence with
`<u>`, but `<u>` is not on GitHub's tag allowlist, so GitHub's sanitizer drops it and renders
the text plain. The page matches GitHub, which means the underline is lost in both places.
Anything the statement expresses in Markdown - bold, code, tables, images - is unaffected.

**The page is static. Is it safe that it renders files an AI wrote?**
`analysis.md` is model-generated and `notes.md` can be edited by anyone with push access, so
both are treated as untrusted. Every tag is rebuilt from its name alone, so no attribute
survives - there is nowhere for an `onerror=` to go. The only exceptions are `href` on `<a>`
and `src` on `<img>`, which keep a URL only if it is http, https, mailto, a fragment, or
relative with no scheme; `javascript:` never reaches the page.

**Do I need to re-run `leetvault site` after solving a new problem?**
No. `sync` refreshes the catalogue, and the page reads `Problems/<slug>/...` directly, so new
problems and any file you edit on GitHub show up without regenerating the page. Re-run
`leetvault site` when you upgrade leetvault, to pick up a newer version of the page itself.

