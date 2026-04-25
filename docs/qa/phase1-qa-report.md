# Phase 1 QA Report

**Branch:** `phase1-improvements`
**Base:** `main`
**Reviewer:** Senior QA (subagent)
**Date:** 2026-04-25

## Scope

Reviewed 6 commits delivering:

1. `config/artifact_schemas.yaml` — required-field / shape rules for 11 artifact keys
2. `config/agents.yaml` — omlx fallbacks swapped for Haiku on tool-use agents; new `kid-safety-reviewer`
3. `config/pipelines.yaml` — `kid-safety-laf` and `kid-safety-qa` inserted before LAF and QA gates
4. `agents/testing/kid-safety-reviewer.md` — new agent prompt
5. `src/runtime/task_validator.py` — `validate_artifact_content()` wired into `validate_outputs` as warn-only
6. `src/main.py` — `_CD_STEP_MAP`, `_check_cd_verdict`, `_maybe_enforce_cd_verdicts`, playtest auto-REVISE
7. `src/iteration/iterate_runner.py` — `_check_playtest_thresholds()` wired into `run_playtest_batch`

## Check results

| # | Item | Result |
|---|------|--------|
| 1 | Diff reads cleanly | PASS |
| 2 | Full test suite runs | PASS (same 16 pre-existing failures on `main`, no regressions) |
| 3 | Targeted tests (`test_task_validator_substitution`, `test_iterate_runner`, `test_bootstrap`) | PASS (25/25) |
| 4 | New symbols import cleanly | PASS |
| 5 | `tests/test_phase1.py` (new) | PASS (20/20) |
| 6a | `_CD_STEP_MAP` keys match pipelines.yaml | PASS (4/4) |
| 6b | `gate-laf` depends_on `kid-safety-laf` | PASS |
| 6c | `gate-qa` depends_on `kid-safety-qa` | PASS |
| 6d | `kid-safety-reviewer` agent name identical in agents.yaml and pipelines.yaml | PASS |
| 7 | CD artifact keys in `_CD_STEP_MAP` match the keys the CD tasks actually write | PASS (4/4) |

### Full-suite summary

```
main (baseline):            16 failed, 250 passed, 1 skipped
phase1-improvements:        16 failed, 270 passed, 1 skipped (20 new Phase 1 tests)
phase1-improvements + fix:  16 failed, 270 passed, 1 skipped
```

Every failing test also fails on `main`; Phase 1 introduces **zero regressions**.
The 16 pre-existing failures are in `test_e2e.py`, `test_agent_tool_skill_parity.py`,
and one `test_pipelines_expected_outputs.py` case (templated key in non-cyclic
`phased-producer`); all predate this branch and are out of scope.

## Bugs found

### BUG-1 (HIGH, fixed): multi-upstream CD REJECT creates N parallel CD tasks

**File:** `src/main.py`
**Original lines:** ~2095–2195 (`_maybe_enforce_cd_verdicts`, REJECT < 2 branch)

`_CD_STEP_MAP["cd-proposal-check"]` maps to four upstream steps
(`propose-designer`, `propose-ux`, `propose-artist`, `propose-proto`).
The original REJECT path iterated `for upstream_id in upstream_steps:` and
**inside** that loop it:

1. created a revision task for one upstream step,
2. created a **new CD task** depending only on that one revision, and
3. rewired all downstream dependents of the old CD task to the latest new CD task.

Consequences:

- On a REJECT of `cd-proposal-check`, 4 parallel CD tasks are created.
- Only the CD task created in the first iteration inherits the original
  downstream dependents (`implement`, etc.); iterations 2–4 rewire over
  each other, and the last-written rewire wins. Earlier rewires are not
  undone cleanly, leaving the DAG in an inconsistent state.
- The final CD task only depends on the 4th revision task; the other 3
  revisions have no CD check gating them.
- The pipeline runs CD four times where once was intended.

**Fix (commit `phase1-qa: fix CD-proposal REJECT creating N parallel CD tasks`):**
collect all revision task IDs, then create exactly one new CD task that
`depends_on` the full list, and rewire downstream dependents once.

For the single-upstream case (concept, mechanics, laf) behaviour is
identical to before.

### Minor findings (not blocking, not patched)

- **`_check_cd_verdict(project_id, verdict_key, db)`** takes a `db` parameter
  that is never used. The caller opens a `get_studio_db()` session purely to
  pass it in. Safe, but wasteful; candidate for cleanup.
- **Templated verdict key without `iteration_tag`:** if a future CD step uses
  `{{iteration_tag}}` in `_CD_STEP_MAP` but the cd_task metadata has no
  `iteration_tag`, the placeholder is left literal. Current callers all
  have an iteration tag via `cd-proposal-check`; guard only matters for
  future map entries.
- **`_CD_VERDICT_RE` uses `IGNORECASE` only** (no `MULTILINE`); `$` therefore
  matches end-of-string. With the `(?=\n|$)` lookahead the lazy `.*?` works
  correctly for a single verdict line. Confirmed with direct test.
- **Warn-only schema validation** (task_validator) correctly swallows
  JSON-parse errors and treats content as raw string for `game_html_v1`.
  Expected behaviour for Phase 1 ("warn only, hard-fail in Phase 2").
- **`_check_playtest_thresholds`** divides by `max(duration_min, 0.1)` so
  a 0-second session is capped at 10× deaths per minute rather than div-by-zero.
  Good defensive choice.

## New tests

`tests/test_phase1.py` (20 tests) covers:

- `validate_artifact_content`
  - valid `mechanics_v1`, missing `win_condition`, `player_verbs` wrong type,
    `concept_options_v1` under-populated, `concept_options_v1` direction
    missing `pitch`, short `game_html_v1`, long `game_html_v1`, unknown key
    graceful, `None` value graceful, empty dict reports all required fields.
- `_check_playtest_thresholds`
  - good session passes, short session fails, high death rate fails,
    empty sessions list fails, missing `sessions` key fails gracefully,
    sessions missing `events` key still pass without crash.
- CD verdict parse
  - REJECT with em-dash reason, APPROVE with no reason, CONCERNS with
    reason, and a cross-check against `src.main._CD_VERDICT_RE`.

All 20 pass.

## Verdict

**APPROVE WITH FIXES** (fix already committed on this branch).

The Phase 1 change set is well-scoped and does not regress the existing
suite. The schema validator and playtest gate are small, focused, and
correctly wired. The CD enforcement path had one real structural bug in
the multi-upstream case that is now corrected; the remaining items are
minor polish and acceptable for Phase 1.

Recommend merge of `phase1-improvements` once the QA fix commit lands
in review.
