# Self-Review Protocol for Code Reviewer

**CRITICAL:** Apply these same standards to YOUR OWN review before submitting. You are not immune to confirmation bias. The reviewer's checklist only works if it runs on the reviewer's output too.

Adapted for code-play from the ai-daily-assistant self-review protocol. Covers web (Three.js / Phaser / Pixi / canvas), Unity C#, and Roblox Luau game builds.

Before submitting any review or artifact (`code_review_v1`, BLOCKER list, acceptance criteria) YOU create:

---

## 1. Command Validation

- Verify commands and APIs exist before recommending. Don't suggest `window.requestIdleCallback` if tech plan pins a browser baseline that doesn't support it. Don't suggest Unity APIs introduced after the pinned engine version. Don't suggest Luau methods that don't exist in Roblox's sandboxed runtime.
- Check man pages / docs / `tech_plan_v1.engine_version` before citing any API as the fix.

---

## 2. Cross-Reference Verification

- When findings claim "X does Y", read X and verify it's true.
- Don't trust prose — verify against implementation.
- Example: if the review says `tech_plan_v1 §4.2 mandates server-auth`, open `tech_plan_v1` and confirm §4.2 exists and says that. Cite the exact section, not from memory.
- Example: if the review says `game.mjs:42 leaks the frame budget`, open `game.mjs:42` and confirm the leak is on that line, not line 38.

---

## 3. Consistency Checks

- When creating artifacts that exist elsewhere (`code_review_v1`, `postmortem_v1`, `proposal_v1`), compare against prior runs in the same project's memory.
- Match established patterns — severity labels, verdict strings, heading order.
- Check how earlier `code_review_v{n-1}` was structured before creating `code_review_v{n}`.

---

## 4. Progressive Disclosure Validation

- Claim "`game.mjs` is ~200 lines, acceptable" → verify against `wc -l game.mjs`. Don't claim "~80 lines" if file is 183.
- Size claims in the review must match actual size. `codebase_tree_v1` is the ground truth when it's fresh.
- If tech plan mandates "<500 lines per module" and your review says "module size compliant", verify every module.

---

## 5. Path Verification

- Verify relative paths resolve correctly from the location where they're cited.
- Reference link from `code_review_v1` to `tech_plan_v1` artifact: verify the memory key is correct, not guessed.
- File paths in findings: copy-paste-run-able. `artifacts/<game>-v<N>/src/game.mjs:42` should be a real path.
- **CRITICAL:** When the review TEACHES a path pattern ("always import from `/assets/` relative root"), test every example path — don't spot-check.

---

## 6. Infrastructure Claims Verification

- When the review claims "X exists" (CI check, hook, config file, ScriptableObject, RemoteEvent), verify the file actually exists in the artifact folder or scene.
- Don't assume `.git/hooks/` or local dev setup is tracked in version control.
- Example: claiming "telemetry pipeline asserts event schema" requires pointing at the validator file. If none exists, either the review is wrong or the claim is aspirational — flag it, don't approve.

---

## 7. Version Regression Detection

- When reviewing changes to version fields or iteration artifacts, check for downgrades.
- Compare current version against previous: `game_html_v{n}` should extend or supersede `v{n-1}`, not silently revert.
- Flag any gameplay constant that moved backward without postmortem justification: e.g. `player_speed: 240 → 180` across v2 → v3 without a §2 goal tying to it.
- Version should only go UP unless there's explicit iterate_artifact rationale logged in `postmortem_v{n}`.

---

## 8. Version-Capability Consistency

- When version and features change together, cross-reference with `postmortem_v{n}` and implementer's notes.
- Verify features in `game_html_v{n}` match the `proposal_v{n}` that produced it.
- Example: `game_html_v3` includes new enemy type — confirm `proposal_v3` mentions it. A v3 build with features that no proposal introduced = unaccountable scope creep.

---

## 9. Changelog Maintenance

- When iteration advances `game_html_v{n} → v{n+1}`, verify `postmortem_v{n}` + `proposal_v{n+1}` + `code_review_v{n+1}` tell one story.
- Version bump without corresponding postmortem entry = incomplete iteration. Flag as LOW (documentation debt).
- Example: jumping from v4 → v5 with no `postmortem_v4` = process violation, not a code issue — route to producer.

---

## 10. Date / Calendar Validation in Examples

- When the review includes specific dates with day-of-week labels, verify accuracy.
- Use `cal MM YYYY` to check calendars before committing to specific date examples.
- Example error: "Monday, Feb 10, 2026" when Feb 10 is actually Tuesday.
- Why: reviews that teach date/time operations need accurate examples to be trustworthy (daily-reset timers, session boundaries, leaderboard epochs).
- Alternative: use generic placeholders ("Monday, [date]") or remove day-of-week labels entirely.
- Severity: MEDIUM — undermines credibility, especially in date/time-sensitive features.

---

## 11. Exhaustive Instance Search (Within Scope)

- When flagging an issue, search for ALL instances within the files you're reviewing.
- **Scope:** iteration review = search `artifacts/<game>-v<N>/` | full-repo review = search whole repo.
- Use grep to find every occurrence before marking finding as complete.
- Example: flagged `innerHTML` at `game.mjs:43`, but same file has same issue at line 71 and `ui.mjs:22`. Partial flag = partial fix = bug survives v{n+1}.
- Command pattern: `grep -rn "innerHTML" artifacts/<game>-v<N>/` for iteration scope.
- Don't assume you found the only instance — verify exhaustively within scope.
- Severity: MEDIUM — partial fixes leave inconsistent state across the code.

---

## 12. Validation Rule Testing (False Positives)

- When flagging a pattern as an anti-pattern (regex, grep, lint rule), test for false positives.
- Check: does the flag catch things it SHOULDN'T catch?
- Example: rule "no `eval`" must not flag `evaluatePhysics()` or `.evaluate()` on Three.js curves. Pattern `\beval\b` not substring `eval`.
- Test against known safe cases: method names that start with or contain the banned token, string literals in comments, safe DOM APIs.
- Better: explicit patterns or negative lookahead.
- Consider: what legitimate code matches this pattern? Should it be excluded?
- Severity: MEDIUM — breaks legitimate workflows, trains implementers to ignore review output.

---

## 13. Artifact Metadata Validation

**CRITICAL for review completion:** Before writing `code_review_v{n}`, verify all required fields.

**Artifact structure:**

- [ ] **Verdict field is valid:**
  - One of: `APPROVE`, `APPROVE WITH FIXES`, `REVISE` (exact casing)
  - Not: `approved`, `LGTM`, or other variants
  - Mismatched verdict strings cause producer routing failures

- [ ] **Findings grouped by severity:**
  - Exactly: `BLOCKER`, `FIX BEFORE SHIP`, `NIT`
  - Every finding cites `<file>:<line>` — no floating "general code quality" findings
  - BLOCKERs have an owner (`frontend-developer`, `gameplay-programmer`, `roblox-systems-scripter`) + acceptance criterion

- [ ] **Plan reference present:**
  - Every finding points at `tech_plan_v1` section it violates (or marks as "plan silent, reviewer judgment")
  - "Plan silent" findings are fair — but must be labeled, not laundered as plan violations

- [ ] **Summary line is descriptive:**
  - NOT: "Done" / "Reviewed" (too generic)
  - SHOULD be: "2 blockers (`innerHTML` XSS at game.mjs:43, missing window.__game hook); 3 suggestions"
  - Reviewer should be able to reconstruct what was found from the summary alone.

- [ ] **Files list matches actual files reviewed:**
  - `code_review_v{n}.files_reviewed` matches `game_html_v{n}` folder contents
  - Partial reviews labeled as partial, not claimed as full

**Why this check prevents iteration failures:**
- Malformed artifacts cause producer state machine to deadlock
- Generic summaries make postmortems useless next cycle
- Missing required fields break the `code_review_v{n} → proposal_v{n+1}` chain

---

## How to Use

1. Before writing any finding, run through rules 1-6 (verification).
2. Before submitting the review, run through rules 7-13 (consistency + completeness).
3. Time cost: 2-3 minutes. Saves a round of review-of-review bounces.

---

**The Meta-Lesson:** Use the review checklist on yourself. Treat your own work as critically as you treat others'. Confirmation bias is real — systematic processes defeat it.
