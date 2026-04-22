"""Per-project review-round state for review↔implementer fix-loops.

Mirrors `src/iteration/cycle_state.py` but scoped to the inner review loop
that runs after a build-producing step (phased-producer `build`,
iterate_artifact `implement`). Wraps `project_memory` (type `"review"`) so
the orchestrator does not need to know memory-key conventions.

Keys under the `review` type:
- `round_n`      → "0"..."3"  (current review round; 0 = not yet entered)
- `halt_reason`  → free-form string if set (e.g. "rounds_exhausted")
- `budget`       → "3"        (max rounds; overridable per-project)

The orchestrator calls `reset_round()` on first entry to a review loop
(scope boundary) and `bump_round()` on each subsequent review after a
REVISE verdict. `should_continue()` returns False when the budget is hit
or a halt is pinned — the orchestrator then spawns `human-gate-review-cap`
instead of another review.
"""

from __future__ import annotations

from src.memory.project_memory import project_memory

_TYPE = "review"
_DEFAULT_BUDGET = 3


def get_round_n(project_id: str) -> int:
    """Current review round. 0 = the review loop has not run yet."""
    raw = project_memory.read(project_id, _TYPE, "round_n")
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def bump_round(project_id: str, created_by: str = "orchestrator:review_loop") -> int:
    """Increment the round counter and return the new value."""
    n = get_round_n(project_id) + 1
    project_memory.write(project_id, _TYPE, "round_n", str(n), created_by=created_by)
    return n


def reset_round(project_id: str, created_by: str = "orchestrator:review_loop") -> None:
    """Zero the counter on fresh-loop entry (new cycle, new DAG review step)."""
    project_memory.write(project_id, _TYPE, "round_n", "0", created_by=created_by)


def get_budget(project_id: str) -> int:
    raw = project_memory.read(project_id, _TYPE, "budget")
    try:
        return int(raw) if raw else _DEFAULT_BUDGET
    except ValueError:
        return _DEFAULT_BUDGET


def set_budget(project_id: str, budget: int, created_by: str = "system") -> None:
    project_memory.write(project_id, _TYPE, "budget", str(budget), created_by=created_by)


def get_halt_reason(project_id: str) -> str | None:
    """None if the loop may continue; a reason string if halted."""
    return project_memory.read(project_id, _TYPE, "halt_reason")


def set_halt(project_id: str, reason: str, created_by: str = "system") -> None:
    project_memory.write(project_id, _TYPE, "halt_reason", reason, created_by=created_by)


def clear_halt(project_id: str) -> None:
    project_memory.delete(project_id, _TYPE, "halt_reason")


def should_continue(project_id: str) -> bool:
    """True iff the orchestrator may enqueue another review round.

    False when round_n has hit the budget OR a halt reason is pinned.
    Caller is responsible for bumping the counter after a successful
    fix-implement → review re-entry.
    """
    if get_halt_reason(project_id):
        return False
    if get_round_n(project_id) >= get_budget(project_id):
        return False
    return True
