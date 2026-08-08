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

from pathlib import Path

from rich.console import Console

from leetvault.config import ConfigStore

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
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import os, re
          title = os.environ.get("ISSUE_TITLE", "")
          body = os.environ.get("COMMENT_BODY") or os.environ.get("ISSUE_BODY") or ""
          # "[3348] why is this greedy?" or "3348: why ..." or a bare slug in the title.
          match = re.match(r"\\s*[\\[(]?\\s*([A-Za-z0-9-]+)\\s*[\\])]?\\s*[:\\-]\\s*(.*)", title)
          problem = match.group(1) if match else title.strip()
          question = (body.strip() or (match.group(2).strip() if match else ""))
          print(f"problem={problem}")
          print("question<<EOF")
          print(question or "Explain this solution.")
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
          leetvault ask "${{ steps.ask.outputs.problem }}" \\
            "${{ steps.ask.outputs.question }}" \\
            --provider "${{ vars.LEETVAULT_AI_PROVIDER || 'gemini' }}" \\
            --repo . --no-push | tee /tmp/answer.txt

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
          git diff --staged --quiet || {
            git commit -m "leetvault: answer issue #${{ github.event.issue.number }}"
            git push
          }
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


def run_bot(console: Console, *, install: bool, repo: Path | None, show: bool) -> None:
    store = ConfigStore()
    repo_path = repo or store.resolved_repo_path()
    provider = store.get("ai_provider") or "gemini"

    if show or not install:
        console.print("[bold]GitHub Q&A bot[/bold] - ask questions as issues, in the browser.\n")
        console.print(f"Workflow : {repo_path / WORKFLOW_PATH}")
        console.print(f"Installed: {(repo_path / WORKFLOW_PATH).exists()}\n")
        _print_setup(console, str(provider))
        if not install:
            console.print("\nRun [bold]leetvault bot --install[/bold] to add it to your repo.")
        return

    workflow = repo_path / WORKFLOW_PATH
    template = repo_path / TEMPLATE_PATH
    workflow.parent.mkdir(parents=True, exist_ok=True)
    template.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(WORKFLOW, encoding="utf-8")
    template.write_text(ISSUE_TEMPLATE, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {workflow}")
    console.print(f"[green]Wrote[/green] {template}\n")
    _print_setup(console, str(provider))
    console.print(
        "\nCommit and push these, then open an issue titled "
        "[bold]\\[two-sum]: why a hash map?[/bold]"
    )


def _print_setup(console: Console, provider: str) -> None:
    key_name = {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider, "GEMINI_API_KEY")
    console.print("[bold]One-time setup on GitHub:[/bold]")
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
