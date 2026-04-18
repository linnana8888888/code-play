"""Per-project cycle state for `iterate_artifact` pipelines.

Wraps `project_memory` (type `"cycle"`) so `_advance_pipeline` does not need to
know memory-key conventions. Keys live under the `cycle` type:

- `n`            → "1"..."5"  (current cycle number, INT as string)
- `halt_reason`  → free-form string if set (e.g. "stalled", "manual")
- `budget`       → "5" (max cycles; overridable per-project)
"""

from __future__ import annotations

from src.memory.project_memory import project_memory

_TYPE = "cycle"
_DEFAULT_BUDGET = 5


def get_cycle_n(project_id: str) -> int:
    """Current cycle number. 0 = iteration has never run for this project."""
    raw = project_memory.read(project_id, _TYPE, "n")
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def bump_cycle(project_id: str, created_by: str = "pipeline:iterate_artifact") -> int:
    """Increment the cycle counter and return the new value."""
    n = get_cycle_n(project_id) + 1
    project_memory.write(project_id, _TYPE, "n", str(n), created_by=created_by)
    return n


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


def should_relaunch(project_id: str) -> bool:
    """True iff `_advance_pipeline` should enqueue cycle n+1.

    False when we've hit the budget OR a halt reason is pinned. Caller is
    responsible for bumping the counter after a successful relaunch.
    """
    if get_halt_reason(project_id):
        return False
    if get_cycle_n(project_id) >= get_budget(project_id):
        return False
    return True
