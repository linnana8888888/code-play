---
name: Git Workflow
description: Branching, commit, and review conventions for the code-play studio
---

# Git Workflow

## Branches
- `main` is always deployable. Never commit directly; open a PR.
- Feature branches: `feat/<short-slug>`, bugs: `fix/<short-slug>`, experiments: `spike/<short-slug>`.
- Delete the branch after merge; keep the repo tidy.

## Commits
- Imperative mood, ≤72 chars on the subject line.
- Conventional-commit prefix when it adds signal: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- Body (optional): *why* the change exists — constraints, incidents, stakeholder asks. Don't restate *what*; the diff does that.
- One logical change per commit. Bundle only when splitting would be pure churn.

## Before Committing
- Run the relevant tests locally; do not stage red files.
- `git diff --staged` and read what you're shipping.
- Never commit: secrets, API keys, `.env*` files, large binaries, build artifacts, `node_modules/`, `.venv/`.
- `git add <file>` by name. Avoid `git add -A` / `git add .` — they pick up junk.

## Pull Requests
- Title: same rules as commit subject.
- Body: **Summary** (1–3 bullets of intent), **Test plan** (what you ran, what to run to verify).
- Link to the spec / issue / task that asked for the change.
- Small PRs over big PRs. If >400 lines changed, justify it in the body.

## Review Expectations
- Reviewer: read the test plan first, then the diff. Ask *why*, not just *what*.
- Author: respond to every review comment (resolve or discuss). Don't force-push after review starts — push fix-up commits so the reviewer sees the delta.

## Things That Need a Human Before They Happen
- `git push --force` to any shared branch
- `git reset --hard` on shared history
- Rewriting published commits
- Deleting branches you didn't create
- Committing a merge that touches >3 files you don't own

These are `restricted`-tier operations in the studio. Use `escalate` before attempting them.

## Safe Defaults
- Pull with `--rebase` to keep history linear.
- Sign commits if the repo requires it; never pass `--no-verify` unless explicitly told.
- If a pre-commit hook fails, *fix the underlying issue*, don't bypass it.
