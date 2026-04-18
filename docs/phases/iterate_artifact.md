# Phase: `iterate_artifact`

A cyclic pipeline that takes an existing game artifact (shipped by
`phased-producer` or hand-authored against `docs/iteration_contract.md`) and
makes it better over 2–5 cycles of headless playtesting.

> **Companion files.** `config/pipelines.yaml → iterate_artifact:` defines the
> step graph. `src/iteration/iterate_runner.py` runs the headless batch.
> `src/iteration/cycle_state.py` gates relaunches. Keep this runbook in sync
> when any of those change.

## What one cycle looks like

```
playtest  →  postmortem  →  ┌─ propose-designer ─┐
                             ├─ propose-ux ──────┤
                             ├─ propose-artist ──┤→  synthesis_gate  →  implement  →  (loop)
                             └─ propose-proto ───┘
```

1. **`playtest`** (qa-engineer) — `iterate_runner.run_playtest_batch(project_id,
   repo_path, cycle_n, runs=5, seconds_per_run=60)`:
   - Picks a free port, spawns `python3 -m http.server` rooted at the artifact repo.
   - Shells `node playtest_bot.mjs --runs 5 --seconds 60 --tag v{n}`.
   - Aggregates `<repo>/telemetry/*.json` whose `iteration_tag` matches, drops
     `outcome == "quit"` rows (bot-crash, not a play signal), writes rollup to
     project memory as `telemetry_v{n}`, broadcasts `playtest_batch_complete`.
2. **`postmortem`** (support-analytics-reporter) — reads `telemetry_v{n}` +
   `goals_md`, writes `postmortem_v{n}` tying §2 metrics to §3 targets. All
   metric names must pass `validate_goals_md()` — no `fps`, no `drop_rate`.
3. **`propose-designer` / `propose-ux` / `propose-artist` / `propose-proto`** —
   run in parallel (no `depends_on` between them). Each picks one angle,
   cites the §2 metric it expects to move, writes
   `proposal_<kind>_v{n}`.
4. **`synthesis_gate`** (human-gate, `review_of: propose-designer`) — human
   compares the 4 proposals against `postmortem_v{n}`, approves ONE.
5. **`implement`** (frontend-developer) — applies the approved proposal on top
   of `game_html_v{n}`, writes `game_html_v{n+1}`, commits to the project's
   iteration branch. When the task completes, `_advance_pipeline` calls
   `_maybe_relaunch_cyclic` → if `should_relaunch` passes (cycle_n < budget and
   no `halt_reason`), the `playtest` step is re-enqueued for cycle `n+1`.

## Lifecycle

| Event                                       | Who writes                          | Who reads             |
|---------------------------------------------|-------------------------------------|-----------------------|
| Project registered with `iterate_enabled=1` | dashboard or `/api/pipelines/advance?force_phase=iterate_artifact` | `run_pipeline`     |
| `cycle_state(n)` bumped to 1                | `run_pipeline` (cyclic=true)       | relaunch check        |
| `telemetry_v{n}` written                    | `iterate_runner`                    | postmortem, dashboard |
| `postmortem_v{n}` written                   | support-analytics-reporter          | all 4 proposers       |
| `proposal_*_v{n}` (x4) written              | 4 proposers in parallel             | synthesis_gate        |
| `game_html_v{n+1}` written                  | frontend-developer                  | next cycle's playtest |
| `cycle_state(n)` bumped to n+1              | `_maybe_relaunch_cyclic`            | next relaunch check   |
| `halt_reason` set                           | any proposer/human                  | `should_relaunch` (halts loop) |
| Cycle budget reached (default 5)            | n/a                                 | `should_relaunch` (halts loop) |

## Kickoff

```bash
# For a project that already has GOALS.md + playtest_bot.mjs in its artifact repo:
curl -X POST "localhost:${PORT}/api/pipelines/advance?project_id=${PID}&force_phase=iterate_artifact"
```

The endpoint routes to `run_pipeline("iterate_artifact", …)`, which:
- Sets `projects.iterate_enabled = 1` for `${PID}`.
- Stamps `cycle_state = {"n": 1}` in project memory.
- Clears any stale `halt_reason`.
- Creates the 8 cycle-1 tasks; the first (`playtest`) gets `metadata =
  {"iteration_tag": "v1", "cycle_n": 1}`.

## Halting

Set `halt_reason` in project memory (type=`cycle`, key=`halt_reason`) to stop
the loop without deleting state. Valid reasons are free-form; examples:
`"stalled"`, `"budget_exhausted"`, `"qa_fail"`. The next `_maybe_relaunch_cyclic`
sweep sees it and refuses to enqueue cycle `n+1`.

To resume later, `clear_halt(project_id)` and the next task-completion sweep
picks up where it left off.

## Budget

The default budget is 5 cycles (see `cycle_state.DEFAULT_BUDGET`). Override
per-project by writing `{"budget": <int>}` to the cycle memory key. Once
`cycle_n >= budget`, `should_relaunch` returns `False` even without a
`halt_reason`.

## Observed rollup shape (from `aggregate_telemetry`)

```json
{
  "cycle_n": 1,
  "iteration_tag": "v1",
  "n_runs": 5,
  "n_valid": 4,
  "outcome_counts": {"win": 1, "death": 2, "timeout": 1, "quit": 1},
  "aggregates": {
    "session_duration_sec": {"median": 82.5, "p25": 55.0, "p75": 110.0},
    "accuracy": {"median": 0.42, "p25": 0.31, "p75": 0.58},
    "...": {"...": "..."}
  },
  "raw_values": {"levels_reached": [0.0, 1.0, 2.0, 3.0]},
  "upgrades_histogram": {"dmg": 4, "fan": 1}
}
```

Everything except `outcome` and `upgrades_picked` is a numeric metric from
`src.iteration.contract.METRIC_NAMES`. The postmortem agent cites these
verbatim.

## Integration drill

1. Start dev server; register a code-play project pointing at the artifact repo.
2. `POST /api/pipelines/advance?project_id=...&force_phase=iterate_artifact`.
3. Watch for:
   - `playtest` task spawns → http server port live → node bot runs 5× →
     telemetry files written → `telemetry_v1` memory artifact → WS event
     `playtest_batch_complete`.
   - `postmortem` spawns, writes `postmortem_v1`.
   - Four proposers fan out; 4 `proposal_*_v1` artifacts land in memory.
   - WS `gate_ready` event with `review_of: propose-designer`; human approves one.
   - `implement` writes `game_html_v2`, commits to the iteration branch.
   - WS `cycle_relaunched` with `cycle_n: 2`; playtest spawns again at v2.

## Failure drills

- **Bot crashes** (node exits non-zero): `run_playtest_batch` still writes what
  it can but `stdout_tail` is carried in `RunnerResult`. The qa-engineer task
  should surface it on `blocked`, not mark `completed` with a partial rollup.
- **Missing `telemetry/` dir**: `load_telemetry_dir` returns empty; rollup has
  `n_runs=0, n_valid=0`, aggregates all zero. Postmortem must detect this and
  escalate rather than fabricate conclusions.
- **`halt_reason` set mid-cycle**: cycle in flight finishes its current steps;
  `_maybe_relaunch_cyclic` refuses to enqueue the next. No state is lost.
