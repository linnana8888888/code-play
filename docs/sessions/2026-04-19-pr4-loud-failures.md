# 2026-04-19 — Loud failures end-to-end (PR-4 + dashboard)

## Shipped

| SHA | What |
|-----|------|
| `08f943c` | bootstrap gate (`ensure_goals_md`) + spawn retry cap (`record_spawn_failure`) |
| `fd6450b` | dashboard surfaces `spawn_failed` — red row in ActivityFeed, dismissible banner stack on ProjectView |
| `7542be1` | `pytest.ini` — `pythonpath = .`, `testpaths = tests` so bare `pytest` collects all 133 tests without `PYTHONPATH=.` |
| `f051571` | merge resolution for PR #5 (`feature/publisher-agent`) — kept branch's 9-col Rating table + Cheekshot row |

## Why these changes

Two silent-degrade failure modes previously stalled a pipeline branch forever:
- **Agent-name drift** (`pipelines.yaml` refers to an agent that `agents.yaml` no longer defines): `agent_registry.spawn` raised `ValueError`, `_advance_pipeline` logged a warning every ~6s, nothing surfaced.
- **Mode-B bootstrap gap** (project enters `iterate_artifact` without going through `phased-producer`): `goals_md` is absent in memory, postmortems cite nothing, proposers drift to freeform.

Now both fail loudly:
- retry cap = 3, after which the task is `BLOCKED` and a `spawn_failed` WS event fires with `hint` pointing at the drift check
- `ensure_goals_md` gates `run_pipeline` at cyclic start — either noops (memory hit), auto-seeds from `<repo>/GOALS.md`, or raises `HTTPException(400)` with a concrete fix-hint

Dashboard now renders the `spawn_failed` event in two places — the live activity feed (red `blocked` row) and a project-scoped dismissible red banner stack (max 5, dedup'd by task_id).

## Tests

- `tests/test_bootstrap.py` — 6 cases covering memory-hit, repo-seed, missing-both, missing-file, empty-memory fallthrough, tilde expansion
- `tests/test_task_queue_spawn_failures.py` — 6 cases covering count-1, count-3-blocks, 5-error cap, custom max_failures, missing task, no regression after BLOCKED

12/12 green. After `7542be1`, bare `pytest` collects all 133 repo tests with no `PYTHONPATH` workaround.

## Open threads

1. **Re-drill `iterate_artifact` on bsg** under the new gate — confirms (a) gate noops since `goals_md` is seeded, (b) no spurious `spawn_failed` fires, (c) banner only triggers on real drift.
2. **Stale worktree** at `projects/bsg/worktrees/qa-engineer-f5ef23d1/` — leftover from an earlier drill, still carries a copy of `test_iteration_contract.py`. Housekeeping.
3. `pytest.mark.asyncio` warnings in `test_asset_tools.py` — missing `pytest-asyncio` registration, unrelated to this session but visible in collection output.

## Key files

- `src/iteration/bootstrap.py` (new) — `GoalsBootstrapError` + `ensure_goals_md`
- `src/orchestrator/task_queue.py` — `record_spawn_failure(task_id, error, max_failures=3)`
- `src/main.py` — gate in `run_pipeline`, spawn-retry-cap in both `_advance_pipeline` and `run_pipeline` fast-path, `spawn_failed` WS broadcast
- `dashboard/src/pages/ProjectView.tsx` — banner stack + WS handler
- `dashboard/src/components/activity/ActivityFeed.tsx` — red `blocked` row
- `pytest.ini` — pythonpath fix
