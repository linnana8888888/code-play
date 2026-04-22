# Re-Review Protocol

Shared reference for any reviewer re-entering the same artifact after a prior
round. Applies to `code-reviewer`, `creative-director`, and `qa-engineer` any
time they run on an artifact they (or a peer reviewer) already flagged.

**Why this exists:** reviewers drift. On round 2, it's easy to scan for
*new* problems and forget to check whether the *old* problems were fixed.
When that happens, issues bounce round-to-round undetected, the fix-loop
hits its cap with blockers unresolved, and the pipeline silently ships
broken work through a human-gate escape hatch.

The rule: **prior findings first, new findings second.** Always.

---

## 1. Read Prior Verdict FIRST

Before scanning the artifact for new issues, open the prior round's verdict
artifact from memory.

- `code-reviewer` round N: read `code_review_r{N-1}` (or
  `code_review_v{cycle}_r{N-1}` in cyclic pipelines).
- `creative-director` re-entry: read the prior
  `cd_{gate}_verdict_v{n-1}` or `cd_iterate_verdict_v{n-1}`.
- `qa-engineer` re-entry: read the prior `playtest_{{iteration_tag}}`
  rollup + any prior `qa_verdict_v{n-1}`.

If the prior verdict is missing, say so in the first line of your review and
treat the round as round 1 (full scan, no prior-findings pass).

---

## 2. Verify Prior Findings Line-by-Line

For EACH prior BLOCKER / FIX BEFORE SHIP / CONCERN / REJECT item:

- Open the file or artifact area cited in the prior finding.
- Confirm whether the fix landed. Unresolved = **still the same severity**.
  No severity downgrade without a written reason.
- If the implementer's note claims the finding is out of scope, you decide —
  don't rubber-stamp.

Example: round 1 flagged `innerHTML` XSS at `game.mjs:43` as BLOCKER. In
round 2, open `game.mjs:43`. Still `innerHTML`? Still BLOCKER. Swapped for
`textContent`? Confirm every call site is fixed (see rule 3 below), then
mark resolved.

---

## 3. Only AFTER Prior-Findings Pass, Scan for New Issues

Don't shortcut. Even if all prior blockers are clearly resolved, finish the
prior-findings pass before starting the new-issues scan. Two reasons:

1. Thoroughness — a fix often creates new adjacent issues (regressions,
   introduced anti-patterns, new files).
2. Calibration — finishing the prior-findings list first calibrates you on
   what the implementer already knows and what they missed. Your new-issues
   scan reads differently after you've seen what survived round 1.

---

## 4. Emit Diff-Aware Verdict

Verdict line must cite round-over-round progress so the human gate (and the
next-round reviewer) can see the loop converging or stalling.

Good:
```
VERDICT: REVISE (2 of 3 prior blockers resolved; 1 new finding)
```

```
VERDICT: APPROVE (all 4 prior blockers resolved; 0 new findings)
```

Bad:
```
VERDICT: REVISE
```
(no signal whether this round made progress — reviewer treated it as round 1)

If you're the orchestrator-faced reviewer (`code-reviewer`), the final line
must still match the machine shape: `VERDICT: APPROVE` /
`VERDICT: APPROVE WITH FIXES` / `VERDICT: REVISE`. The parenthetical
summary after the verdict keyword is fine — the parser reads only up to the
verdict keyword.

---

## Round-Cap Behavior

The orchestrator enforces `max_rounds = 3` per review_loop. If you're
writing round 3 and the verdict is still REVISE, the orchestrator will
spawn a human-gate task (`review-cap`) with your review attached. Your
verdict body should make the blockers + fix history unambiguous so the
human gate can choose approve-anyway / halt / extend cleanly.

If the artifact genuinely needs round 4+ because the fixes introduced
structural churn, say so explicitly in the verdict body — don't gate-crash
an APPROVE just to get out of the loop.
