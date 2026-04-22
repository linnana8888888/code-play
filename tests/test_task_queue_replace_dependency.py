"""Tests for TaskQueue.replace_dependency.

The review↔implementer fix-loop needs to rewire downstream dependents from a
completed-but-revise-spawned review task to the fresh next-round review task.
Without this primitive, every dependent stays wired to the already-completed
review → get_ready_tasks releases them immediately → pipeline advances past
unresolved blockers.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.database import get_studio_db
from src.models.tasks import TaskCreate
from src.orchestrator.task_queue import task_queue


@pytest.fixture
def project_row(request):
    pid = f"test-rewire-{request.node.name.replace('[', '-').replace(']', '')}"
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "rewire test", "", "html5", None, None, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


def _mk(pid: str, title: str, deps=None):
    return task_queue.create(
        TaskCreate(
            project_id=pid,
            title=title,
            description=title,
            depends_on=deps or [],
            created_by="test",
        )
    )


def test_replaces_single_dep(project_row):
    a = _mk(project_row, "a")
    b = _mk(project_row, "b")
    c = _mk(project_row, "c", deps=[a.id])
    updated = task_queue.replace_dependency(c.id, a.id, b.id)
    assert updated.depends_on == [b.id]


def test_unknown_task_returns_none(project_row):
    assert task_queue.replace_dependency("nonexistent-task-id", "x", "y") is None


def test_missing_old_dep_is_noop(project_row):
    a = _mk(project_row, "a")
    b = _mk(project_row, "b")
    c = _mk(project_row, "c", deps=[a.id])
    # old_dep_id="zzz" not in c's deps → no-op, returns task unchanged.
    result = task_queue.replace_dependency(c.id, "zzz-not-a-dep", b.id)
    assert result.depends_on == [a.id]


def test_preserves_other_deps(project_row):
    a = _mk(project_row, "a")
    b = _mk(project_row, "b")
    c = _mk(project_row, "c")
    d = _mk(project_row, "d", deps=[a.id, b.id, c.id])
    updated = task_queue.replace_dependency(d.id, b.id, c.id)
    # b replaced by c, c already present → dedupe, order preserved.
    assert updated.depends_on == [a.id, c.id]


def test_dedupes_when_new_dep_already_present(project_row):
    a = _mk(project_row, "a")
    b = _mk(project_row, "b")
    c = _mk(project_row, "c", deps=[a.id, b.id])
    updated = task_queue.replace_dependency(c.id, a.id, b.id)
    assert updated.depends_on == [b.id]


def test_multiple_occurrences_all_replaced(project_row):
    """Shouldn't happen in practice (deps are supposed to be unique), but the
    contract is that every instance of old_dep_id becomes new_dep_id, then the
    list is deduped."""
    a = _mk(project_row, "a")
    b = _mk(project_row, "b")
    # Manually craft duplicate deps by round-tripping through the DB.
    import json
    from src.database import get_studio_db as _db
    c = _mk(project_row, "c", deps=[a.id])
    with _db() as db:
        db.execute(
            "UPDATE tasks SET depends_on = ? WHERE id = ?",
            (json.dumps([a.id, a.id]), c.id),
        )
    updated = task_queue.replace_dependency(c.id, a.id, b.id)
    assert updated.depends_on == [b.id]
