"""Unit tests for TaskQueue.record_spawn_failure.

Locks the contract that spawn-retry drift surfaces loudly after N failures
instead of silently looping forever. Before PR-4, a pipelines.yaml agent
reference that didn't match agents.yaml would log a warning every ~6s and
stall one branch of a fan-out indefinitely.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.database import get_studio_db
from src.models.tasks import TaskCreate, TaskStatus
from src.orchestrator.task_queue import task_queue


@pytest.fixture
def project_row(request):
    pid = f"test-spawn-{request.node.name}"
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "spawn test", "", "html5", None, None, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


def _mk_task(project_id: str) -> str:
    t = task_queue.create(
        TaskCreate(
            project_id=project_id,
            title="test-task",
            description="spawn-failure fixture",
            created_by="test",
        )
    )
    return t.id


def test_first_failure_returns_count_1_and_does_not_block(project_row):
    tid = _mk_task(project_row)

    count, blocked = task_queue.record_spawn_failure(tid, "Unknown agent type: foo")

    assert count == 1
    assert blocked is False
    t = task_queue.get(tid)
    assert t.status == TaskStatus.PENDING
    assert t.result["spawn_failures"] == 1
    assert t.result["spawn_errors"] == ["Unknown agent type: foo"]


def test_third_failure_blocks_task_and_preserves_error_history(project_row):
    tid = _mk_task(project_row)

    task_queue.record_spawn_failure(tid, "err 1")
    task_queue.record_spawn_failure(tid, "err 2")
    count, blocked = task_queue.record_spawn_failure(tid, "err 3")

    assert count == 3
    assert blocked is True
    t = task_queue.get(tid)
    assert t.status == TaskStatus.BLOCKED
    assert t.result["spawn_failures"] == 3
    assert t.result["spawn_errors"] == ["err 1", "err 2", "err 3"]


def test_error_history_capped_at_last_five(project_row):
    tid = _mk_task(project_row)

    for i in range(8):
        task_queue.record_spawn_failure(tid, f"err {i}", max_failures=100)

    t = task_queue.get(tid)
    assert t.result["spawn_failures"] == 8
    assert len(t.result["spawn_errors"]) == 5
    assert t.result["spawn_errors"][0] == "err 3"
    assert t.result["spawn_errors"][-1] == "err 7"


def test_custom_max_failures_respected(project_row):
    tid = _mk_task(project_row)

    task_queue.record_spawn_failure(tid, "e1", max_failures=2)
    count, blocked = task_queue.record_spawn_failure(tid, "e2", max_failures=2)

    assert count == 2
    assert blocked is True
    assert task_queue.get(tid).status == TaskStatus.BLOCKED


def test_missing_task_returns_zero_and_false(project_row):
    count, blocked = task_queue.record_spawn_failure("task-does-not-exist", "x")

    assert count == 0
    assert blocked is False


def test_does_not_re_block_once_status_is_blocked(project_row):
    """Subsequent failures after BLOCKED still increment count but do not
    regress state — the task stays blocked, errors still accumulate.
    """
    tid = _mk_task(project_row)

    for _ in range(3):
        task_queue.record_spawn_failure(tid, "fail")
    assert task_queue.get(tid).status == TaskStatus.BLOCKED

    count, blocked = task_queue.record_spawn_failure(tid, "fail-again")

    assert count == 4
    assert blocked is True
    assert task_queue.get(tid).status == TaskStatus.BLOCKED
