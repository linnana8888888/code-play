# Session: Agent Sweep & Pipeline Cleanup

**Date:** 2026-04-21  
**Commit:** `db0372c`

## What changed

### 1. Killed stuck iterate pipeline
- Cheekshot (butt-shooting-game) had a stuck `iterate_artifact` pipeline — `propose-proto` task blew its 12.8M token budget (used 13.2M), blocking all downstream tasks
- Cancelled 4 remaining tasks (propose-proto, synthesis_gate, cd-proposal-check, implement) via direct DB update
- Confirmed 5 tasks completed successfully (playtest, postmortem, propose-designer, propose-ux, propose-artist)

### 2. Agent instance list — collapse finished + sweep
- **InstanceList.tsx**: Split into active agents (full table) and finished agents (collapsed summary showing count, total tokens, total cost)
- Finished section has expand toggle and "Clear" button
- **Backend**: Added `DELETE /api/agents/instances/sweep?project_id=X` endpoint
- **agent_registry.py**: `sweep_finished()` removes terminated/completed/failed from both in-memory dict and DB (handles post-restart orphans too)
- **useAgents.ts**: Added `sweep()` function wired to `sweepInstances` API call
- **ProjectView.tsx**: Wired `onSweep` prop to InstanceList

### 3. DB cleanup
- Purged 38 finished + 5 orphan agent instances from studio.db
- Killed stale uvicorn process (PID 25884) that was holding port 8080, letting the `--reload` instance (PID 83921) take over

## Cheekshot version status (from repo)
- **v3** (`c1fa6d8`) — published on itch.io as "Cheekshot"
- **v6.1** (`d09f232`) — current on `main`, user says already on itch (registry not yet updated)
- Branches: v3, v4, v5, main

## Test results
- TypeScript: clean (`tsc --noEmit` + `vite build`)
- Backend: not re-run (no Python logic changes beyond new endpoint + registry method)

## Files touched
- `dashboard/src/components/agents/InstanceList.tsx` — rewrite with active/finished split
- `dashboard/src/hooks/useAgents.ts` — added sweep function
- `dashboard/src/api/client.ts` — added sweepInstances
- `dashboard/src/pages/ProjectView.tsx` — wired sweep to InstanceList
- `src/main.py` — added DELETE /api/agents/instances/sweep endpoint
- `src/orchestrator/agent_registry.py` — added sweep_finished method
