# Iteration-Loop Proposal — butt-shooting-game × code-play

**Date:** 2026-04-18
**Status:** draft, pending user decision on first cut

## The gap

`butt-shooting-game` already emits 17 analytics event types (`analytics.mjs`)
and stores session rollups in localStorage — but no system consumes that data
between runs. Every iteration starts from zero: the developer plays, spots an
issue, fixes it, ships. This session was a textbook example: user reports
three bugs → I play serially all four roles (tester, analyst, designer,
implementer) → ship. No parallelism, no persistence, no goal function.

`code-play` already has the orchestration substrate — 21 specialist agents,
SQLite task queue with atomic checkout, per-agent worktrees, a phased pipeline
`concept → mechanics → laf → build`, and a dashboard at `/app`. What it lacks
is a **cycle**: the pipeline is linear and terminates at build.

## Proposed pipeline extension

```
build  →  playtest  →  postmortem  →  propose  →  [synthesis gate]  →  build
          (N bots)     (vs GOALS)     (fan-out)    (human/lead picks)
```

| Phase | Who runs | Output |
|---|---|---|
| playtest | headless bot × N | `telemetry/<run>.json` dumps |
| postmortem | one analyst agent | "top 3 gaps" doc vs GOALS.md |
| propose | N specialists in parallel | N **specs** (markdown), not diffs |
| synthesis gate | human (or lead agent) | one winning spec |
| implement | coding agent | diff → re-enters build |

## Key design decisions

1. **Goals must be measurable.** `GOALS.md` holds numeric targets (median run
   length, accuracy band, D1-retention proxy). Without this, agents have no
   loss function.

2. **Proposals are specs, not diffs.** Parallel diffs conflict; parallel specs
   don't. One implementer merges the winner.

3. **Termination rule.** If three cycles fail to move any metric, the loop
   halts and pings a human.

4. **Artifact independence.** `butt-shooting-game` stays a standalone repo
   with a `.codeplay/` dir for config. `code-play` is the orchestrator, not
   the home of the game code.

## Cost envelope

~7–10 agent calls per cycle:
- 1 playtest runner
- 1 analyst
- 3–5 proposers
- 1 implementer
- 1 reviewer

At code-play's $1/run budget that's $7–10 per cycle, 10–30 min turnaround.

## Smallest testable first cut (half day)

Files to create:

- `butt-shooting-game/GOALS.md` — 5 measurable targets
- `butt-shooting-game/playtest_bot.mjs` — 60s random-walk AI, dumps JSON
- `butt-shooting-game/telemetry/.gitkeep`
- `code-play/` — new phase definition `iterate_artifact`
- `code-play/agents/` — 4 new or mapped specialist roles for this pipeline

## Open questions

- How many bot runs per playtest? (suggest: 5 for noise reduction)
- Where does GOALS.md live on initial creation — human-authored or
  concept-phase agent output?
- Does the synthesis gate always require a human, or can a lead-agent
  pre-approve when metric delta is unambiguous?
- Are specialists scoped per-game or universal? (suggest: universal roles,
  per-game context files)
