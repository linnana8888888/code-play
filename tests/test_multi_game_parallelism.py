"""Phase 4.1 — Multi-Game Parallelism tests.

Covers:
  - get_project_lock identity / idempotency
  - Two tasks for different projects can be enqueued without blocking
  - _count_active_pipeline_runs returns correct counts
  - run_pipeline endpoint returns 429 when MAX_CONCURRENT_PROJECTS reached
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.database import get_project_lock, _project_locks
from src.main import app, MAX_CONCURRENT_PROJECTS, _count_active_pipeline_runs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_project_locks():
    """Ensure per-project lock registry is clean between tests."""
    _project_locks.clear()
    yield
    _project_locks.clear()


@pytest.fixture
def tmp_projects(tmp_path, monkeypatch):
    """Isolate DB in a tmpdir and initialise it."""
    from src.settings import settings
    from src.database import init_studio_db

    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    init_studio_db()
    return tmp_path


client = TestClient(app)


# ---------------------------------------------------------------------------
# get_project_lock — identity and idempotency
# ---------------------------------------------------------------------------


class TestGetProjectLock:
    def test_different_ids_return_different_locks(self):
        lock_a = get_project_lock("proj-aaa")
        lock_b = get_project_lock("proj-bbb")
        assert lock_a is not lock_b

    def test_same_id_returns_same_lock_idempotent(self):
        lock1 = get_project_lock("proj-same")
        lock2 = get_project_lock("proj-same")
        assert lock1 is lock2

    def test_lock_is_acquirable(self):
        lock = get_project_lock("proj-acquire")
        acquired = lock.acquire(blocking=False)
        assert acquired
        lock.release()

    def test_locks_are_independent(self):
        """Acquiring one project's lock must not affect another project's lock."""
        lock_a = get_project_lock("proj-ind-a")
        lock_b = get_project_lock("proj-ind-b")

        lock_a.acquire()
        try:
            # lock_b should still be free
            acquired_b = lock_b.acquire(blocking=False)
            assert acquired_b, "lock_b should be acquirable while lock_a is held"
            lock_b.release()
        finally:
            lock_a.release()


# ---------------------------------------------------------------------------
# Task enqueue — different projects don't block each other
# ---------------------------------------------------------------------------


class TestTaskEnqueueParallelism:
    def test_tasks_for_different_projects_enqueue_independently(self, tmp_projects, monkeypatch):
        """Two tasks for different projects can be created without contention."""
        from src.database import get_studio_db
        from src.orchestrator.task_queue import task_queue
        from src.models.tasks import TaskCreate

        # Create two projects first
        with get_studio_db() as db:
            for pid in ("proj-game1", "proj-game2"):
                db.execute(
                    "INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)",
                    (pid, pid),
                )

        t1 = task_queue.create(
            TaskCreate(
                project_id="proj-game1",
                title="Game 1 task",
                description="desc",
                created_by="test",
            )
        )
        t2 = task_queue.create(
            TaskCreate(
                project_id="proj-game2",
                title="Game 2 task",
                description="desc",
                created_by="test",
            )
        )

        assert t1.project_id == "proj-game1"
        assert t2.project_id == "proj-game2"
        assert t1.id != t2.id


# ---------------------------------------------------------------------------
# _count_active_pipeline_runs
# ---------------------------------------------------------------------------


class TestCountActivePipelineRuns:
    def test_returns_zero_when_no_tasks(self, tmp_projects):
        import asyncio

        count = asyncio.run(_count_active_pipeline_runs())
        assert count == 0

    def test_returns_correct_count_with_active_tasks(self, tmp_projects):
        """Projects with at least one assigned task count toward the cap."""
        import asyncio
        from src.database import get_studio_db
        from src.orchestrator.task_queue import task_queue
        from src.models.tasks import TaskCreate, TaskStatus

        with get_studio_db() as db:
            for pid in ("proj-c1", "proj-c2"):
                db.execute(
                    "INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)",
                    (pid, pid),
                )

        t1 = task_queue.create(
            TaskCreate(project_id="proj-c1", title="t1", description="d", created_by="test")
        )
        t2 = task_queue.create(
            TaskCreate(project_id="proj-c2", title="t2", description="d", created_by="test")
        )
        # Mark both as assigned so they count toward the cap
        task_queue.update_status(t1.id, TaskStatus.ASSIGNED)
        task_queue.update_status(t2.id, TaskStatus.ASSIGNED)

        count = asyncio.run(_count_active_pipeline_runs())
        assert count == 2

    def test_pending_tasks_not_counted(self, tmp_projects):
        """Projects with only pending tasks do NOT count toward the cap."""
        import asyncio
        from src.database import get_studio_db
        from src.orchestrator.task_queue import task_queue
        from src.models.tasks import TaskCreate

        with get_studio_db() as db:
            db.execute(
                "INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)",
                ("proj-pending", "proj-pending"),
            )

        task_queue.create(
            TaskCreate(project_id="proj-pending", title="pending task", description="d", created_by="test")
        )
        # Task stays pending — should not count
        count = asyncio.run(_count_active_pipeline_runs())
        assert count == 0

    def test_completed_tasks_not_counted(self, tmp_projects):
        import asyncio
        from src.database import get_studio_db
        from src.orchestrator.task_queue import task_queue
        from src.models.tasks import TaskCreate, TaskStatus

        with get_studio_db() as db:
            db.execute(
                "INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)",
                ("proj-done", "proj-done"),
            )

        t = task_queue.create(
            TaskCreate(project_id="proj-done", title="done task", description="d", created_by="test")
        )
        task_queue.update_status(t.id, TaskStatus.COMPLETED)

        count = asyncio.run(_count_active_pipeline_runs())
        assert count == 0


# ---------------------------------------------------------------------------
# run_pipeline endpoint — 429 when cap reached
# ---------------------------------------------------------------------------


class TestRunPipelineConcurrencyLimit:
    def test_returns_429_when_max_concurrent_projects_reached(self, tmp_projects):
        """When _count_active_pipeline_runs returns MAX_CONCURRENT_PROJECTS,
        launching a NEW project's pipeline must return 429."""
        with patch(
            "src.main._count_active_pipeline_runs",
            new=AsyncMock(return_value=MAX_CONCURRENT_PROJECTS),
        ):
            # Also mock the DB check for "already_active" to return None
            # (this is a brand-new project, not already running)
            with patch("src.main.get_studio_db") as mock_db_ctx:
                mock_conn = mock_db_ctx.return_value.__enter__.return_value
                mock_conn.execute.return_value.fetchone.return_value = None

                resp = client.post(
                    "/api/pipelines/iterate_artifact/run",
                    json={"project_id": "proj-new-game", "input_text": ""},
                )

        assert resp.status_code == 429
        assert "Maximum concurrent projects reached" in resp.text

    def test_below_limit_does_not_return_429(self, tmp_projects):
        """When active count is below the cap, the 429 guard must not fire."""
        with patch(
            "src.main._count_active_pipeline_runs",
            new=AsyncMock(return_value=MAX_CONCURRENT_PROJECTS - 1),
        ):
            # The pipeline lookup will fail (no pipelines.yaml in tmp), but
            # that's a 404 — proof the 429 guard was NOT triggered.
            with patch("src.main._load_pipelines_yaml", return_value={"pipelines": {}}):
                resp = client.post(
                    "/api/pipelines/nonexistent_pipeline/run",
                    json={"project_id": "proj-ok", "input_text": ""},
                )

        # 404 = pipeline not found, meaning we passed the concurrency gate
        assert resp.status_code == 404

    def test_max_concurrent_projects_constant_is_3(self):
        assert MAX_CONCURRENT_PROJECTS == 3
