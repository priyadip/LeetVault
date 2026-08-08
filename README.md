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
- `leetvault analyze [problem]` — regenerate an existing `analysis.md` with a different
  backend — see [below](#redoing-an-analysis).
- `leetvault ask <problem> "<question>"` — ask a question about one of your solutions and
  keep the answer — see [below](#asking-questions).
- `leetvault bot [--install]` — install a GitHub Actions workflow so you can ask from GitHub
  itself — see [below](#asking-from-github).
- `leetvault commands [--full]` — list every command and what it does, generated from the CLI
  itself so it cannot fall behind.

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
| **Groq** | Free tier | Free API key | [console.groq.com/keys](https://console.groq.com/keys). Very fast; no local hardware. Meters 8000 tokens/min. |
| **NVIDIA NIM** | Free tier | Free API key | [build.nvidia.com](https://build.nvidia.com). Very large open models with reasoning; quota separate from Gemini and Groq. |
| **Ollama** (local) | Free, unlimited | ~5 GB disk + RAM | `ollama pull qwen2.5-coder:7b`. Fully offline, no account. Slow without a GPU. |
| **Claude Code CLI** | Free | An existing Claude subscription | `npm i -g @anthropic-ai/claude-code`, then `claude` once to sign in. |
| **Anthropic API** | Paid, per token | API key | `pip install anthropic`. Highest quality. |

**Gemini, Groq and NVIDIA NIM are the fallback when you have neither spare RAM nor a Claude
subscription** — a free API key, and inference runs in the cloud. Their quotas are separate,
so a backfill stopped by one provider's daily limit can be finished on another.

For **Hard** problems, prefer a reasoning-capable model. Tracing code and justifying
complexity is multi-step arithmetic, and a mid-size instruct model will produce a confident,
wrong dry run rather than admitting it cannot follow the code.

```bash
leetvault ai                      # detect backends and choose one
leetvault ai --set-key gemini     # store a free key (or groq / nvidia / anthropic)
leetvault ai --show               # print current settings
leetvault ai --disable            # turn it back off
leetvault config ai_model llama-3.3-70b-versatile   # override the model
```

Generation is best-effort: a failing or slow model never breaks a sync. `sync` only fills
gaps — a problem that already has an `analysis.md` is skipped, which is what makes a backfill
resumable across a free tier's daily limit. To replace one you are not happy with, use
[`leetvault analyze`](#redoing-an-analysis).

Each file's footer records the model that wrote it, so a repo built across several providers
stays traceable.

#### How an analysis is assembled

leetvault asks for the whole analysis in one call and keeps that when it comes back complete.
If the reply is truncated or missing sections, it re-requests them in halves, then pairs, then
one section at a time, pausing between calls so a per-minute token budget is not spent in one
shot. A partial analysis is never written — a file that exists is a problem that never gets
looked at again.

### Redoing an analysis

```bash
leetvault analyze --list                  # which model wrote each analysis
leetvault analyze two-sum -p nvidia       # redo one problem
leetvault analyze --from groq -p nvidia   # redo everything Groq wrote
leetvault analyze --all -p gemini         # redo the lot, one model throughout
```

Name a problem by slug, number, or part of its title. You are asked before anything is
overwritten (`-y` skips that), and if the new provider fails, the existing analysis is kept
rather than lost.

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

### Asking questions

`analysis.md` answers the questions leetvault thought to ask. For everything else:

```bash
leetvault ask two-sum "why a hash map and not sorting first?"
leetvault ask 3348 "is this actually greedy, or dynamic programming?" --push
```

The question and answer append to that problem's `qa.md`, so the thread accumulates and
earlier exchanges are carried into later ones as context. A problem can be named by slug,
number, or part of its title. `--no-save` prints the answer without keeping it.

Context comes from the repository — `question.md`, your solution, and any existing
`analysis.md` — not from the database. That is what lets the same command run in CI.

### Asking from GitHub

```bash
leetvault bot --install
```

This writes a GitHub Actions workflow and an issue template into your solutions repo. After
committing them and adding your API key as a repository secret, you can open an issue titled

> `[two-sum]: why a hash map?`

and the bot replies as a comment and commits the exchange to `Problems/two-sum/qa.md`.
Replying in the thread asks a follow-up. It works from a phone, since it is just GitHub.

Two things worth knowing:

- **Your API key lives in GitHub's encrypted secrets**, never in the repo. `leetvault bot`
  prints the exact settings page and secret name for the backend you have configured.
- **Only issues you open are answered.** On a public repo anyone can file an issue, and
  without that check every stranger would be spending your quota. The workflow compares the
  issue author against the repository owner and does nothing otherwise.

GitHub renders Markdown but does not run it, so a chat box inside `Problems/<slug>/` is not
possible. Issues are the closest real equivalent — and they give you threading, search,
notifications and history for free.

## Discovering commands

```bash
leetvault commands          # every command and what it does
leetvault commands --full   # plus every argument and option
```

Generated from the CLI itself, so it cannot fall behind the commands that actually exist.

## Honest limits

- `watch` is polling (default 90s, configurable), not a real-time push — LeetCode has no public
  webhook/streaming API.
- LeetCode may Cloudflare-challenge automated HTTP clients; leetvault fails gracefully rather
  than faking success.
- Storing session cookies for automated access may be against LeetCode's Terms of Service. Use
  at your own risk, against your own account only.
- LeetCode has no official API — every endpoint leetvault uses is reverse-engineered and could
  change without notice.
- AI analysis is only as good as the model behind it. leetvault checks that a response is
  complete and rejects truncated or stub replies, but it cannot verify that a dry run or a
  complexity claim is *correct* — read generated analysis as a strong draft, not an authority,
  and prefer a reasoning-capable model for Hard problems.

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
