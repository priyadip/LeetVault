# leetvault — kickoff prompt (autonomous run)

> Prerequisite: place `CLAUDE.md` in the (empty) project folder first, then open Claude Code there and paste the block below. From session 2 onward Claude Code auto-loads `CLAUDE.md`, so you won't need to re-paste anything. For fewest interruptions, also set the VS Code permission mode (see the note under this block).

---

Read `CLAUDE.md` in the repo root — it's the authoritative brief for this project: goal, v1 scope and non-goals, the reverse-engineered LeetCode API constraints, the exact stack, the SQLite data model, the working protocol, and the phase checklist.

Then build the entire v1 autonomously, following the working protocol in `CLAUDE.md`. Run **Phases 0 → 7 end-to-end**, looping on each: build → tests green → `ruff check` + `ruff format --check` + `mypy --strict` clean → Conventional Commit → one-line progress note → immediately start the next phase. **Do not pause for my approval between phases, and do not ask "should I continue?"** — keep going. For small decisions, pick the sensible default, log it in `PLAN.md`, and move on.

**Stop to ask me only at the two points where you need something only I have:**
- **Phase 2:** my `LEETCODE_SESSION` + `csrftoken` (I'll paste them into the `login` flow so they're stored in keyring — not into this chat).
- **Phase 4:** a fine-grained GitHub PAT (scoped to one repo, Contents: write) + the target repo URL.

Ask once at each of those, then continue autonomously to the end. Also stop before any irreversible action outside this repo (force-push, history rewrite, deleting files you didn't create).

Keep `PLAN.md` and `docs/ARCHITECTURE.md` current, never print or commit secrets, and never fake functionality — if something is genuinely blocked, tell me and propose a real fallback rather than skipping or stubbing it.

Start now: give me a one-paragraph plan for Phase 0, then proceed straight through.
