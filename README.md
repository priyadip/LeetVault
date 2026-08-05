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

- `leetvault login [--leetcode|--github] [--force]` — store your `LEETCODE_SESSION` +
  `csrftoken` (and optionally a GitHub PAT) in the OS keyring. Only prompts for what's
  actually missing or expired — see [below](#refreshing-credentials).
- `leetvault import [--keep-all]` — full history import of every accepted submission
  (resumable, one-time per site).
- `leetvault sync [--keep-all]` — incremental sync of new accepted submissions since the last
  run.
- `leetvault watch` — poll LeetCode and sync automatically (`--interval`, default 90s).
- `leetvault status` — show session validity/expiry and sync state.
- `leetvault logout` — remove stored credentials.
- `leetvault config` — get/set persistent configuration (repo URL, DB path, dedup window, ...).
- `leetvault ai` — set up optional AI-generated solution analysis (**off by default**).

### Refreshing credentials

Your LeetCode session cookies expire roughly every 14 days; a GitHub PAT lasts until you revoke
it or it hits its own expiry. They fail independently, so `login` checks each one **live** and
only prompts for what actually needs replacing:

```bash
leetvault login            # checks both, prompts only for what's expired/missing
leetvault login --leetcode # only refresh LeetCode cookies, never touch the stored PAT
leetvault login --github   # only refresh the GitHub PAT, never re-ask for cookies
leetvault login --force    # re-prompt for everything, even if still valid
```

If both are still good, `login` prompts for nothing and tells you so. `leetvault status` shows
the same live check without changing anything.

### AI solution analysis (optional, off by default)

`leetvault ai` can generate an `analysis.md` next to each solution — explaining the approach,
walking through your actual code, and covering complexity and edge cases. It is **disabled
until you turn it on**, and your `notes.md` is never touched.

It works with whichever backend you already have; run `leetvault ai` and it detects them:

| Backend | Cost | Needs | Notes |
|---|---|---|---|
| **Gemini** | Free tier | Free API key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). No local hardware, no subscription. |
| **Groq** | Free tier | Free API key | [console.groq.com/keys](https://console.groq.com/keys). Very fast; no local hardware. |
| **Ollama** (local) | Free, unlimited | ~5 GB disk + RAM | `ollama pull qwen2.5-coder:7b`. Fully offline, no account. Slow without a GPU. |
| **Claude Code CLI** | Free | An existing Claude subscription | `npm i -g @anthropic-ai/claude-code`, then `claude` once to sign in. |
| **Anthropic API** | Paid, per token | API key | `pip install anthropic`. Highest quality. |

**Gemini and Groq are the fallback when you have neither spare RAM nor a Claude
subscription** — a free API key, and inference runs in the cloud.

```bash
leetvault ai                      # detect backends and choose one
leetvault ai --set-key gemini     # store a free Gemini key (or groq / anthropic)
leetvault ai --show               # print current settings
leetvault ai --disable            # turn it back off
leetvault config ai_model llama-3.3-70b-versatile   # override the model
```

Generation is best-effort — a failing or slow model never breaks a sync, and analysis is
written once per problem, never regenerated.

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
  question.md            the problem statement, examples, constraints + collapsed hints
  analysis.md            optional AI explanation of your solution (off by default)
  run.py                  runs your solution against the problem's example inputs
  metadata.json          difficulty, topics, runtime/memory percentiles, ...
  notes.md                yours - never overwritten once created
leetvault_runner.py       shared runner that each run.py delegates to
.devcontainer/            so the repo opens ready-to-run in GitHub Codespaces
README.md                 auto-generated dashboard: progress, streaks, full solutions table,
                          and clickable topic tags that jump to a per-topic problem list
```

### Running solutions in the browser

Open your solutions repo on GitHub and choose **Code ▸ Codespaces ▸ Create codespace** - you
get full VS Code with a terminal, and the devcontainer means Python is already set up:

```bash
python Problems/two-sum/run.py
```

It prints your solution's output for each of LeetCode's example inputs. It intentionally does
*not* report pass/fail: the API exposes example inputs but not their expected outputs, so any
verdict would be guesswork - check the `Output:` lines in that problem's `question.md`.
Problems needing non-JSON inputs (linked lists, trees) or with no single entry point (design
problems) say so rather than running incorrectly.

`question.md` is fetched once per problem and never re-fetched, so it costs nothing on
subsequent syncs. Disable it entirely with `leetvault config write_question_md false`. Problem
statements remain the property of LeetCode; each file notes this.

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

The AI analysis prompt is adapted from [leetcode-helper](https://github.com/amanattar/leetcode-helper) by Aman Attar (MIT) — see [NOTICE.md](NOTICE.md).
