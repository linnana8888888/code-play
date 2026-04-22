# code-play phase spec: `iterate_artifact`

**Status:** draft, 2026-04-18. Extends `phased-producer` in `code-play/config/pipelines.yaml`
with a cyclic phase. Schema + metric names live in `ITERATION_CONTRACT.md` §§2–3.

## Trigger

1. **Auto:** fires from `_advance_pipeline` (`src/main.py:801`) when the prior
   `build` step's task flips `completed` AND the project row has
   `iterate_enabled=1` (new column on `projects`; default 0 = linear pipeline).
2. **On-demand:** dashboard button `POST /api/pipelines/advance` on the project
   header → same entrypoint, with `?force_phase=iterate_artifact`.
3. **Cycle budget:** max 5 cycles per project, tracked in `memory` (key
   `iterate_cycle_n`). Beyond 5 → halt + escalate.

## Inputs (read-only, per cycle)

- `butt-shooting-game/GOALS.md` — targets by metric name (§2 of contract).
- `butt-shooting-game/telemetry/*.json` — latest N runs (schema §1).
- `memory` artifact keys: `mechanics_v1`, `laf_brief_v1`, `tech_plan_v1`,
  `game_html_v{cycle-1}`, `postmortem_v{cycle-1}` (if any).
- `git HEAD` of `butt-shooting-game` (for reproducibility tag on telemetry).

## Sub-phases

All are `steps:` under a new `iterate_artifact:` pipeline key in
`config/pipelines.yaml`. Each runs as a task row (`created_by='pipeline:iterate_artifact'`).

| # | step id | agent (from `config/agents.yaml`) | est. duration | est. cost |
|---|---|---|---|---|
| 1 | `playtest` | `qa-engineer` (has `playwright_browser`) — runs `playtest_bot.mjs` N=5 times, writes JSON to `telemetry/`, saves rollup as `telemetry_v{n}` | 4–6 min | ~$0.20 (GPT-5 orchestrating headless loop) |
| 2 | `postmortem` | `support-analytics-reporter` — diffs `telemetry_v{n}` medians against `GOALS.md`, writes `postmortem_v{n}` artifact (top-3 gaps, each citing a §2 metric name) | 1–2 min | ~$0.40 (Sonnet) |
| 3 | `propose` | Fan-out: `game-designer`, `design-ux-researcher`, `technical-artist`, `rapid-prototyper` — each writes a **spec** (markdown, not code) to `proposal_{agent}_v{n}`. Parallel, no cross-dep. `product-feedback-synthesizer` runs last to pull in qual signal if available. | 3–5 min wall-clock (parallel) | ~$1.50 total (4× Sonnet/GPT-5) |
| 4 | `synthesis_gate` | `type: human-gate`, `review_of: propose` — dashboard lists the N specs side-by-side with delta-vs-goals from step 2. Human (or `project-management-studio-producer` if `auto_synthesis=1`) picks one, stores pick as `chosen_proposal_v{n}`. | human time (min–hr) | $0 |
| 5 | `implement` | `frontend-developer` — reads `chosen_proposal_v{n}` + `game_html_v{cycle-1}`, produces `game_html_v{n}`, commits to `butt-shooting-game` HEAD, writes `iterate_cycle_n = n`. Then loops back: step 1 of next cycle. | 5–10 min | ~$0.80 (GPT-5) |

Per-cycle envelope: ~$2.90, 15–25 min wall-clock + human gate time. Matches the
$7–10/cycle ceiling in `ITERATION_LOOP_PROPOSAL.md` once reviewer/QA are added.

## Outputs

- `telemetry/<iso8601>-<run-id>.json` (git-tracked; see contract §3).
- `memory` artifacts: `telemetry_v{n}`, `postmortem_v{n}`, `proposal_*_v{n}`,
  `chosen_proposal_v{n}`, `game_html_v{n}` (reuses existing memory table).
- New git commits on `butt-shooting-game` main: one per cycle, tagged
  `iter/v{n}` — the implement step authors them.
- Dashboard cards: one kanban task per sub-phase in the existing `tasks` table;
  gate surfaces via existing `gate_ready` WebSocket event (`src/main.py:833`).
- `decisions/iter-v{n}.md` (doc category `decision` via `document_write` tool)
  — the synthesis-gate reviewer's note: which proposal + why.

## Human gate

Exactly one gate per cycle: `synthesis_gate` between `propose` and `implement`.
Wired identically to `gate-laf` / `gate-qa` in `phased-producer` — lives in
`approval_queue` (studio.db) via the existing `human-gate` step type, surfaced
by `dashboard/src/components/gates/GatesPanel`. Gate approves (a) which
proposal wins and (b) whether to proceed to implement or halt the loop.
The build-phase `gate-qa` is **not** re-run here; QA runs implicitly via
`playtest` in the next cycle's step 1.

## Failure modes

1. **No metric moves in 3 cycles.** `support-analytics-reporter` compares
   `postmortem_v{n}` medians against `postmortem_v{n-2}`; if zero §2 metrics
   cross their GOAL threshold direction, it writes `halt_reason=stalled` and
   raises an `escalate` tool call. `_advance_pipeline` sees the halt flag and
   stops spawning cycle n+1. Human must clear via dashboard.
2. **Telemetry missing / empty.** `playtest` asserts
   `len(telemetry_v{n}.runs) >= 3` (configurable). On failure → task status
   `blocked`, result includes playwright console log. The cycle pauses; no
   postmortem runs on empty input. (Avoids the silent-failure class flagged
   in `docs/redesign-2026-04-17/session-improvements.md` §2.)
3. **Implementer can't compile.** `implement` step runs a smoke check:
   headless load of `game_html_v{n}`, assert `window.__game` exposed (same
   hook as `tech_plan_v1`). On fail → `code-reviewer` spawned on the diff;
   if still broken, revert to `game_html_v{n-1}` and mark cycle `failed`.
   The loop continues with the prior HEAD; telemetry tag on the next cycle
   records `iteration_tag="v{n}-rollback"`.

## Integration points

**Touch (est. line counts):**
- `code-play/config/pipelines.yaml` — add ~55-line `iterate_artifact:` block
  mirroring `phased-producer` step shape.
- `code-play/config/agents.yaml` — no new agents (all 5 roles already exist);
  optionally add `model_override` tuning for `propose` fan-out (~5 lines).
- `code-play/src/main.py` `_advance_pipeline` (L801–870) — add ~20 lines to
  recognize `iterate_artifact` as cyclic: when last step (`implement`)
  completes AND `iterate_cycle_n < 5` AND no `halt_reason`, re-enqueue
  `playtest` task. Plus `?force_phase=` query arg on `/api/pipelines/advance`.
- `code-play/src/database.py` migrations (L259+) — add
  `projects.iterate_enabled INTEGER DEFAULT 0` and `projects.auto_synthesis INTEGER DEFAULT 0`.
- `code-play/dashboard/src/components/gates/GatesPanel` — render spec-diff
  grid for `review_of: propose` (N specs + metric deltas). VERIFY: exact
  component file name — directory listed, file naming not read.

**Net-new:**
- `code-play/src/orchestrator/iterate_runner.py` (~120 lines) — wraps the
  playtest sub-phase: shells `node playtest_bot.mjs` in the artifact repo,
  aggregates runs into `telemetry_v{n}`, emits `playtest_batch_complete` WS
  event. Called by the `qa-engineer` agent's task body.
- `code-play/docs/phases/iterate_artifact.md` — human-facing runbook.
- `butt-shooting-game/.codeplay/config.yaml` — per-artifact config
  (N bot runs, cycle budget, `auto_synthesis` bool).

## VERIFY items

- `VERIFY:` GatesPanel exact filename — `dashboard/src/components/gates/` dir
  exists but contents not fetched.
- `VERIFY:` `escalate` tool semantics — listed in `config/governance.yaml`
  builtin set but halt-on-escalate behavior in `_advance_pipeline` not read.
- `VERIFY:` `document_write` category enum — `decisions/iter-v{n}.md` assumes
  a `decision` category; `documents.category` is free-text in schema but
  runtime may enforce.
- `VERIFY:` per-agent budget: $1/run default in `agents.yaml` — the `propose`
  fan-out at 4 agents stays under the per-cycle $7–10 envelope, but
  `playtest`'s long headless loop may exceed `budget_max_tokens=200000`.
  Tune `qa-engineer.max_tokens` or split into runner + analyst.
