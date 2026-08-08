"""The `leetvault bot` command: install a GitHub Actions workflow that answers issues.

GitHub renders Markdown; it does not run one. So a chat box inside `Problems/<slug>/` is not
possible, but the thing you actually want is: ask a question where the code lives, from any
device, and have the answer kept. Issues plus Actions give exactly that - the issue is the
chat window, the workflow is the bot, and the answer lands both as a comment and as a commit
to `qa.md`.

Two things this deliberately does *not* do. It never writes your API key anywhere - the key
lives in GitHub's encrypted secrets and the workflow reads it from there. And the workflow
refuses to answer anyone but the repository owner: on a public repo, any stranger can open an
issue, and without that gate every one of them would be spending your quota.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from rich.console import Console

from leetvault.config import ConfigStore

# Every backend whose credential is a plain API key the workflow can use.
_KEY_PROVIDERS = ("gemini", "groq", "nvidia", "anthropic")
_SECRET_NAMES = {name: f"{name.upper()}_API_KEY" for name in _KEY_PROVIDERS}

WORKFLOW_PATH = ".github/workflows/leetvault-qa.yml"
TEMPLATE_PATH = ".github/ISSUE_TEMPLATE/ask-about-a-problem.yml"

# `issues`/`issue_comment` events run in the base repository with access to its secrets, so
# the author check is the only thing standing between a public repo and an open API bill.
WORKFLOW = """# Answers questions asked as GitHub issues, using leetvault.
# Installed by `leetvault bot --install`. Safe to edit or delete.
name: leetvault Q&A

on:
  issues:
    types: [opened]
  issue_comment:
    types: [created]

permissions:
  contents: write
  issues: write

# One at a time. Two questions asked close together would otherwise race to commit qa.md,
# and the loser's push is refused. Queue rather than cancel - cancelling would silently
# drop an answer the user is waiting for.
concurrency:
  group: leetvault-qa
  cancel-in-progress: false

jobs:
  answer:
    # Only the repository owner. Anyone can open an issue on a public repo, and every one
    # of them would otherwise spend the owner's API quota.
    if: >-
      github.event.issue.user.login == github.repository_owner &&
      !github.event.issue.pull_request &&
      (github.event_name == 'issues' ||
       github.event.comment.user.login == github.repository_owner)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install leetvault
        run: pip install --quiet leetvault

      - name: Work out what was asked
        id: ask
        env:
          ISSUE_TITLE: ${{ github.event.issue.title }}
          ISSUE_BODY: ${{ github.event.issue.body }}
          COMMENT_BODY: ${{ github.event.comment.body }}
        run: |
          # Parsing lives in leetvault, not here: logic inlined in YAML cannot be tested,
          # and the version that was inlined silently preferred an issue form's
          # "_No response_" placeholder over the real question asked in the title.
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import os
          from leetvault.bot import parse_issue
          comment = os.environ.get("COMMENT_BODY") or ""
          body = comment or os.environ.get("ISSUE_BODY") or ""
          # On a follow-up the title's question was already answered; only the comment is
          # the new question.
          problem, question = parse_issue(
              os.environ.get("ISSUE_TITLE", ""), body, is_comment=bool(comment)
          )
          print(f"problem={problem}")
          print("question<<EOF")
          print(question)
          print("EOF")
          PY

      - name: Answer
        id: answer
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          # --model is passed only when set. An empty one would override the provider's
          # own default with nothing, and those defaults differ per provider.
          ARGS=(--provider "${{ vars.LEETVAULT_AI_PROVIDER || 'gemini' }}")
          MODEL="${{ vars.LEETVAULT_AI_MODEL }}"
          if [ -n "$MODEL" ]; then ARGS+=(--model "$MODEL"); fi
          leetvault ask "${{ steps.ask.outputs.problem }}" \\
            "${{ steps.ask.outputs.question }}" \\
            "${ARGS[@]}" --repo . --no-push | tee /tmp/answer.txt

      - name: Comment with the answer
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            let body = fs.readFileSync('/tmp/answer.txt', 'utf8').trim();
            if (body.length > 65000) body = body.slice(0, 65000) + '\\n\\n_(truncated)_';
            await github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body || '_No answer was produced. Check the workflow log._',
            });

      - name: Commit the Q&A log
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add "Problems/*/qa.md" || true
          git diff --staged --quiet && exit 0
          git commit -m "leetvault: answer issue #${{ github.event.issue.number }}"
          # Rebase before pushing and retry: a local `leetvault sync` may have pushed while
          # this job was thinking, and a bare push is refused as a non-fast-forward. The
          # concurrency group above keeps two of these jobs apart, but nothing coordinates
          # this job with a push from someone's laptop.
          for attempt in 1 2 3; do
            git pull --rebase --autostash origin "${GITHUB_REF_NAME}" || git rebase --abort || true
            if git push origin "HEAD:${GITHUB_REF_NAME}"; then exit 0; fi
            sleep $((attempt * 5))
          done
          echo "::error::Could not push the Q&A log after 3 attempts."
          exit 1
"""

ISSUE_TEMPLATE = """name: Ask about a problem
description: Ask the leetvault bot a question about one of your solutions.
title: "[problem-slug]: your question"
body:
  - type: markdown
    attributes:
      value: |
        Put the problem's slug or number in the title, e.g. `[two-sum]: why a hash map?`
        or `[3348]: is this really greedy?`. The answer is posted as a comment and saved
        to that problem's `qa.md`. Replying in the thread asks a follow-up.
  - type: textarea
    id: question
    attributes:
      label: Question
      description: Leave blank to get a general explanation of the solution.
    validations:
      required: false
"""


@dataclass
class Step:
    """One thing the installer tried, and whether it worked."""

    name: str
    ok: bool
    detail: str = ""


def _gh() -> str | None:
    return shutil.which("gh")


def _run_gh(args: list[str], stdin: str | None = None) -> tuple[bool, str]:
    """Run a gh command, returning (ok, message).

    gh rather than the REST API on purpose. Uploading a secret means encrypting it with the
    repository's public key (libsodium sealed box), which would mean a new dependency; gh
    already does it, and its token carries the `workflow` scope a fine-grained PAT typically
    lacks - so it can also push files under .github/workflows/, which git otherwise refuses.
    """
    executable = _gh()
    if executable is None:
        return False, "the GitHub CLI (gh) is not installed"
    try:
        result = subprocess.run(  # noqa: S603 - executable resolved via shutil.which
            [executable, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return False, str(exc)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().splitlines()
        return False, message[-1] if message else f"gh exited {result.returncode}"
    return True, (result.stdout or "").strip()


# What a GitHub issue form writes into a field the user left blank. It is not empty, so
# naive truthiness picks it over a real question asked in the title.
_FORM_PLACEHOLDER = "_no response_"
# A hyphen is both part of a slug and a plausible separator, so one pattern cannot serve
# both: `two-sum` must stay whole while `3348 - explain` must split. Brackets and a colon
# are unambiguous; a bare hyphen only separates when it is spaced.
_BRACKETED = re.compile(r"^\s*[\[(]\s*([^\])]+?)\s*[\])]\s*[:\-]?\s*(.*)", re.DOTALL)


def _split_title(title: str) -> tuple[str, str]:
    """The problem and the question carried in an issue title."""
    text = (title or "").strip()
    match = _BRACKETED.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    if ":" in text:
        problem, _, question = text.partition(":")
        return problem.strip(), question.strip()
    if " - " in text:
        problem, _, question = text.partition(" - ")
        return problem.strip(), question.strip()
    return text, ""


def _meaningful(text: str) -> str:
    """A form body with its headings and placeholders removed."""
    kept = [
        line
        for line in (text or "").splitlines()
        # Issue forms emit "### Question" headings and "_No response_" for blank fields;
        # neither is anything the model should be asked to answer.
        if not line.strip().startswith("#") and line.strip().lower() != _FORM_PLACEHOLDER
    ]
    return "\n".join(kept).strip()


def parse_issue(title: str, body: str, *, is_comment: bool = False) -> tuple[str, str]:
    """Work out which problem an issue is about, and what it asks.

    On the opening issue the question may be in either place - the template's example puts
    it in the title, the form offers a body field - so both are used, and when both carry
    something neither is dropped.

    A follow-up comment is different. The title still names the problem, but its question
    has already been answered; merging it in would have the model answer the original
    question again alongside the new one.
    """
    problem, from_title = _split_title(title)
    from_body = _meaningful(body)

    if is_comment:
        question = from_body
    elif from_title and from_body:
        question = f"{from_title}\n\n{from_body}"
    else:
        question = from_body or from_title
    return problem, question or "Explain this solution."


def repo_slug(repo_url: str) -> str | None:
    """`owner/name` from a GitHub remote URL."""
    if not repo_url:
        return None
    # SSH remotes are `git@host:owner/name`, which urlsplit reads as a path-less scheme.
    path = repo_url.partition(":")[2] if repo_url.startswith("git@") else urlsplit(repo_url).path
    slug = path.strip("/").removesuffix(".git")
    return slug if slug.count("/") == 1 else None


def _upload_secrets(slug: str) -> list[Step]:
    """Push every stored provider key into the repository's encrypted secrets."""
    from leetvault.auth import load_provider_key

    steps: list[Step] = []
    for provider in _KEY_PROVIDERS:
        key = load_provider_key(provider)
        if not key:
            continue
        name = _SECRET_NAMES[provider]
        # No --body at all: gh reads the value from stdin only when the flag is absent, so
        # the key never reaches argv, a process listing, or shell history. `--body -` does
        # not mean stdin - it stores a literal "-", which is what every secret here was
        # until this was fixed, and it surfaces later as "Invalid API Key".
        ok, message = _run_gh(["secret", "set", name, "--repo", slug], stdin=key)
        steps.append(Step(f"secret {name}", ok, message))
    if not steps:
        steps.append(Step("secrets", False, "no provider keys stored - run `leetvault ai`"))
    return steps


def _set_variable(slug: str, name: str, value: str) -> Step:
    """Set a repository variable. Unlike a secret this is plain text and readable in the
    settings UI, which is right for a provider or model name and wrong for a key."""
    ok, message = _run_gh(["variable", "set", name, "--repo", slug, "--body", value])
    return Step(f"variable {name}", ok, message)


def _allow_workflow_writes(slug: str) -> Step:
    """Let the workflow commit qa.md. Repositories default to read-only tokens."""
    ok, message = _run_gh(
        [
            "api",
            "-X",
            "PUT",
            f"repos/{slug}/actions/permissions/workflow",
            "-f",
            "default_workflow_permissions=write",
        ]
    )
    return Step("workflow write permission", ok, message)


def _git(
    repo_path: Path, args: list[str], *, credential_helper: str | None = None
) -> tuple[int, str]:
    prefix = ["git", "-C", str(repo_path)]
    if credential_helper:
        prefix += ["-c", f"credential.helper=!{credential_helper} auth git-credential"]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, paths not user-controlled
            [*prefix, *args], capture_output=True, text=True, timeout=300, check=False
        )
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return 1, str(exc)
    output = (result.stderr or result.stdout or "").strip()
    return result.returncode, output


def _commit_and_push(repo_path: Path, branch: str = "main") -> Step:
    """Commit the two files and push them using gh's credentials.

    A fine-grained PAT without the Workflows permission is refused outright when a push
    touches .github/workflows/, so the usual stored token cannot do this. gh's token can.

    The push names its refspec explicitly. A bare `git push` requires the branch to have an
    upstream, which a repository leetvault created and only ever pushed to by URL does not
    have - it failed with git's `push.autoSetupRemote` advice, which reads like a permissions
    problem and is not one.
    """
    executable = _gh()
    if executable is None:
        return Step("commit and push", False, "gh is not installed")

    _git(repo_path, ["add", ".github"])
    staged, _ = _git(repo_path, ["diff", "--staged", "--quiet"])
    if staged != 0:
        code, message = _git(repo_path, ["commit", "-m", "leetvault: install Q&A bot"])
        if code != 0:
            return Step("commit and push", False, message.splitlines()[-1] if message else "")

    # Rebase onto the remote first. The bot itself commits answers from CI, so the local
    # clone is behind after every question answered, and git refuses a non-fast-forward
    # push. Failure here is not fatal - the push below reports it properly.
    if _git(repo_path, ["fetch", "origin", branch], credential_helper=executable)[0] == 0:
        code, message = _git(repo_path, ["rebase", f"origin/{branch}"])
        if code != 0:
            _git(repo_path, ["rebase", "--abort"])
            return Step(
                "commit and push",
                False,
                "local and remote history diverged and could not be replayed; "
                "resolve it in the repo by hand, then re-run",
            )

    # Push unconditionally, even when there was nothing new to commit: a previous run may
    # have committed and then failed to push, and reporting "already up to date" there would
    # leave the workflow sitting on disk forever, never reaching GitHub.
    code, message = _git(
        repo_path, ["push", "origin", f"HEAD:{branch}"], credential_helper=executable
    )
    if code != 0:
        tail = message.splitlines()
        return Step("commit and push", False, tail[-1] if tail else "push failed")
    return Step("commit and push", True, "up to date" if staged == 0 else "")


def run_bot(
    console: Console, *, install: bool, repo: Path | None, show: bool, manual: bool = False
) -> None:
    store = ConfigStore()
    repo_path = repo or store.resolved_repo_path()
    provider = str(store.get("ai_provider") or "gemini")
    slug = repo_slug(str(store.get("repo_url") or ""))

    if show or not install:
        console.print("[bold]GitHub Q&A bot[/bold] - ask questions as issues, in the browser.\n")
        console.print(f"Repository: {slug or '(not configured)'}")
        console.print(f"Workflow  : {repo_path / WORKFLOW_PATH}")
        console.print(f"Installed : {(repo_path / WORKFLOW_PATH).exists()}\n")
        _print_setup(console, provider)
        if not install:
            console.print("\nRun [bold]leetvault bot --install[/bold] to set it up.")
        return

    workflow = repo_path / WORKFLOW_PATH
    template = repo_path / TEMPLATE_PATH
    workflow.parent.mkdir(parents=True, exist_ok=True)
    template.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(WORKFLOW, encoding="utf-8")
    template.write_text(ISSUE_TEMPLATE, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {workflow}")
    console.print(f"[green]Wrote[/green] {template}\n")

    if manual:
        _print_setup(console, provider)
        console.print("\nCommit and push these yourself, then open an issue.")
        return

    if _gh() is None:
        console.print(
            "[yellow]The GitHub CLI (gh) is not installed, so the rest cannot be "
            "automated.[/yellow] Install it from https://cli.github.com and re-run, or "
            "follow these steps:\n"
        )
        _print_setup(console, provider)
        return

    authed, message = _run_gh(["auth", "status"])
    if not authed:
        console.print(f"[yellow]gh is installed but not signed in[/yellow] ({message}).")
        console.print("Run [bold]gh auth login[/bold] and try again, or follow these steps:\n")
        _print_setup(console, provider)
        return

    if slug is None:
        console.print(
            "[red]No GitHub repo configured.[/red] Set one with `leetvault config repo_url <url>`."
        )
        return

    console.print(f"[bold]Setting up {slug}[/bold]\n")
    steps = [
        *_upload_secrets(slug),
        _set_variable(slug, "LEETVAULT_AI_PROVIDER", provider),
    ]
    # Only when a model is pinned locally. Left unset, each provider uses its own default,
    # which is what an install that has never chosen a model should do.
    model = str(store.get("ai_model") or "")
    if model:
        steps.append(_set_variable(slug, "LEETVAULT_AI_MODEL", model))
    steps += [_allow_workflow_writes(slug), _commit_and_push(repo_path)]

    for step in steps:
        if step.ok:
            console.print(f"  [green]OK[/green]   {step.name}")
        else:
            console.print(f"  [red]FAIL[/red] {step.name} - {step.detail}")

    failed = [s for s in steps if not s.ok]
    if not failed:
        console.print(
            f"\n[green]Done.[/green] Open an issue on {slug} titled "
            "[bold]\\[two-sum]: why a hash map?[/bold] and the bot will answer."
        )
        console.print(
            "[dim]It answers only issues you open, and your keys live in GitHub's "
            "encrypted secrets, never in the repo.[/dim]"
        )
        return

    # Only what actually failed, and only advice that matches the failure. Reprinting the
    # whole manual checklist after five of six steps succeeded reads as though nothing
    # worked, and blaming gh scopes for a git error sends you to the wrong settings page.
    console.print(f"\n[yellow]{len(failed)} step(s) need doing by hand:[/yellow]")
    for step in failed:
        console.print(f"  - {step.name}: {step.detail}")

    if any("403" in s.detail or "not accessible" in s.detail.lower() for s in failed):
        console.print(
            "\ngh is missing a scope - [bold]gh auth refresh -s repo,workflow[/bold] "
            "grants both, then re-run."
        )
    if any(s.name == "commit and push" for s in failed):
        console.print(
            "\nThe files are committed locally. Push them with:\n"
            f'  [bold]git -C "{repo_path}" push origin HEAD:main[/bold]'
        )
    if any(s.name.startswith(("secret", "variable")) for s in failed):
        console.print()
        _print_setup(console, provider)


def _print_setup(console: Console, provider: str) -> None:
    key_name = _SECRET_NAMES.get(provider, "GEMINI_API_KEY")
    console.print("[bold]Manual setup on GitHub:[/bold]")
    console.print(
        f"  1. Settings -> Secrets and variables -> Actions -> New repository secret\n"
        f"     Name: [bold]{key_name}[/bold], value: your key.\n"
        f"  2. Optional: add a variable [bold]LEETVAULT_AI_PROVIDER[/bold] = {provider}\n"
        f"     (defaults to gemini).\n"
        "  3. Settings -> Actions -> General -> Workflow permissions:\n"
        "     allow [bold]Read and write[/bold] so it can commit qa.md."
    )
    console.print(
        "\n[dim]The key is stored by GitHub, never written to the repo. The workflow answers "
        "only issues opened by you - on a public repo, anyone can file one.[/dim]"
    )
