"""Tests for governance batch-approve respecting task dependencies.

Before this fix, approving a roster batch spawned ALL agents at once,
ignoring `depends_on`. Downstream agents ran against empty inputs.

The fix defers spawning for tasks with unmet dependencies, letting
`_advance_pipeline` pick them up as upstream tasks complete.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

def _run(coro):
    """Run an async coroutine safely regardless of existing event loop state."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

import pytest

from src.database import get_studio_db
from src.models.tasks import TaskCreate, TaskStatus
from src.models.proposals import AgentProposalCreate, ProposalPhase, ProposalStatus
from src.orchestrator.task_queue import task_queue
from src.memory import proposals_store


@pytest.fixture
def project_row(request):
    pid = f"test-batch-{request.node.name}"
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, auto_iterate, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "batch dep test", "", "html5", None, None, 1, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM agent_proposals WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


def _mk_task(project_id: str, title: str, depends_on: list[str] | None = None) -> str:
    t = task_queue.create(
        TaskCreate(
            project_id=project_id,
            title=title,
            description=f"test task: {title}",
            depends_on=depends_on or [],
            created_by="pipeline:test",
        )
    )
    return t.id


def _mk_proposal(project_id: str, task_id: str, agent_type: str, batch_id: str) -> str:
    p = proposals_store.create(
        AgentProposalCreate(
            project_id=project_id,
            agent_type=agent_type,
            rationale=f"test proposal for {task_id}",
            proposer="pipeline:test",
            phase=ProposalPhase.KICKOFF,
            batch_id=batch_id,
            task_id=task_id,
        )
    )
    return p.id


class TestBatchApproveDepsCheck:
    """approve_proposal_batch only spawns tasks whose deps are met."""

    def test_only_root_task_spawned(self, project_row):
        """Given A -> B -> C, approving the batch spawns only A."""
        pid = project_row
        task_a = _mk_task(pid, "step-a")
        task_b = _mk_task(pid, "step-b", depends_on=[task_a])
        task_c = _mk_task(pid, "step-c", depends_on=[task_b])

        batch_id = f"batch-test-{pid}"
        prop_a = _mk_proposal(pid, task_a, "qa-engineer", batch_id)
        prop_b = _mk_proposal(pid, task_b, "analytics-reporter", batch_id)
        prop_c = _mk_proposal(pid, task_c, "game-designer", batch_id)

        # Import the endpoint handler
        from src.main import approve_proposal_batch
        from src.models.proposals import BatchDecision

        # Mock _spawn_from_approved_proposal to track calls without real agent spawn
        spawn_calls = []

        async def mock_spawn(proposal_id, task_prompt=None):
            spawn_calls.append(proposal_id)
            mock_inst = MagicMock()
            mock_inst.id = f"inst-{proposal_id}"
            return mock_inst

        with patch("src.main._spawn_from_approved_proposal", side_effect=mock_spawn), \
             patch("src.main.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            result = _run(approve_proposal_batch(batch_id, BatchDecision(decided_by="test")))

        # Only prop_a should have been spawned (no deps)
        assert prop_a in spawn_calls, "Root task proposal should be spawned"
        assert prop_b not in spawn_calls, "Task B depends on A — should be deferred"
        assert prop_c not in spawn_calls, "Task C depends on B — should be deferred"

        # All three should be approved
        assert len(result["approved"]) == 3
        assert len(result["spawned"]) == 1
        assert len(result["deferred"]) == 2

    def test_multiple_roots_all_spawned(self, project_row):
        """Parallel tasks with no deps should all spawn immediately."""
        pid = project_row
        task_a = _mk_task(pid, "parallel-a")
        task_b = _mk_task(pid, "parallel-b")

        batch_id = f"batch-parallel-{pid}"
        prop_a = _mk_proposal(pid, task_a, "qa-engineer", batch_id)
        prop_b = _mk_proposal(pid, task_b, "game-designer", batch_id)

        from src.main import approve_proposal_batch
        from src.models.proposals import BatchDecision

        spawn_calls = []

        async def mock_spawn(proposal_id, task_prompt=None):
            spawn_calls.append(proposal_id)
            mock_inst = MagicMock()
            mock_inst.id = f"inst-{proposal_id}"
            return mock_inst

        with patch("src.main._spawn_from_approved_proposal", side_effect=mock_spawn), \
             patch("src.main.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            result = _run(approve_proposal_batch(batch_id, BatchDecision(decided_by="test")))

        assert prop_a in spawn_calls
        assert prop_b in spawn_calls
        assert len(result["spawned"]) == 2
        assert len(result["deferred"]) == 0

    def test_completed_deps_allow_spawn(self, project_row):
        """If upstream task is already completed, downstream should spawn."""
        pid = project_row
        task_a = _mk_task(pid, "done-step")
        task_b = _mk_task(pid, "next-step", depends_on=[task_a])

        # Complete task A before batch approval
        task_queue.update_status(task_a, TaskStatus.COMPLETED, result={"summary": "done"})

        batch_id = f"batch-done-{pid}"
        prop_b = _mk_proposal(pid, task_b, "game-designer", batch_id)

        from src.main import approve_proposal_batch
        from src.models.proposals import BatchDecision

        spawn_calls = []

        async def mock_spawn(proposal_id, task_prompt=None):
            spawn_calls.append(proposal_id)
            mock_inst = MagicMock()
            mock_inst.id = f"inst-{proposal_id}"
            return mock_inst

        with patch("src.main._spawn_from_approved_proposal", side_effect=mock_spawn), \
             patch("src.main.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            result = _run(approve_proposal_batch(batch_id, BatchDecision(decided_by="test")))

        assert prop_b in spawn_calls, "Dep already completed — should spawn"
        assert len(result["deferred"]) == 0


class TestGetApprovedForTask:
    """proposals_store.get_approved_for_task returns correct proposal."""

    def test_returns_approved_proposal(self, project_row):
        pid = project_row
        task_id = _mk_task(pid, "lookup-test")
        batch_id = f"batch-lookup-{pid}"
        prop_id = _mk_proposal(pid, task_id, "qa-engineer", batch_id)

        # Before approval — should return None
        result = proposals_store.get_approved_for_task(task_id)
        assert result is None

        # Approve it
        proposals_store.approve(prop_id, decided_by="test")

        # Now should return the proposal
        result = proposals_store.get_approved_for_task(task_id)
        assert result is not None
        assert result.id == prop_id
        assert result.task_id == task_id

    def test_returns_none_after_spawned(self, project_row):
        pid = project_row
        task_id = _mk_task(pid, "spawned-test")
        batch_id = f"batch-spawned-{pid}"
        prop_id = _mk_proposal(pid, task_id, "qa-engineer", batch_id)

        proposals_store.approve(prop_id, decided_by="test")
        proposals_store.mark_spawned(prop_id, "inst-fake")

        # After marking spawned, status is 'spawned' not 'approved'
        result = proposals_store.get_approved_for_task(task_id)
        assert result is None

    def test_returns_none_for_no_proposal(self, project_row):
        pid = project_row
        task_id = _mk_task(pid, "no-proposal-test")

        result = proposals_store.get_approved_for_task(task_id)
        assert result is None


class TestCascadeCancel:
    """cancel_task_cascade cancels target + all downstream dependents."""

    def test_chain_cancel(self, project_row):
        """A -> B -> C: cancelling A cancels B and C."""
        pid = project_row
        a = _mk_task(pid, "cascade-a")
        b = _mk_task(pid, "cascade-b", depends_on=[a])
        c = _mk_task(pid, "cascade-c", depends_on=[b])

        cancelled = task_queue.cancel_task_cascade(a)
        assert set(cancelled) == {a, b, c}

        for tid in [a, b, c]:
            t = task_queue.get(tid)
            assert t.status == TaskStatus.FAILED
            assert t.result["cancelled"] is True

    def test_fan_out_cancel(self, project_row):
        """A -> B, A -> C: cancelling A cancels both B and C."""
        pid = project_row
        a = _mk_task(pid, "fan-a")
        b = _mk_task(pid, "fan-b", depends_on=[a])
        c = _mk_task(pid, "fan-c", depends_on=[a])

        cancelled = task_queue.cancel_task_cascade(a)
        assert set(cancelled) == {a, b, c}

    def test_completed_not_cancelled(self, project_row):
        """Completed tasks are not cancelled by cascade."""
        pid = project_row
        a = _mk_task(pid, "done-root")
        b = _mk_task(pid, "done-child", depends_on=[a])
        task_queue.update_status(a, TaskStatus.COMPLETED, result={"ok": True})

        cancelled = task_queue.cancel_task_cascade(a)
        assert a not in cancelled
        assert b in cancelled

    def test_no_double_cancel(self, project_row):
        """Already-cancelled tasks are skipped."""
        pid = project_row
        a = _mk_task(pid, "double-a")
        b = _mk_task(pid, "double-b", depends_on=[a])

        task_queue.cancel_task(a)
        cancelled = task_queue.cancel_task_cascade(a)
        assert a not in cancelled
        assert b in cancelled

    def test_cascade_reason_tag(self, project_row):
        """Downstream tasks get cancelled_reason referencing the root."""
        pid = project_row
        a = _mk_task(pid, "reason-a")
        b = _mk_task(pid, "reason-b", depends_on=[a])

        task_queue.cancel_task_cascade(a)
        tb = task_queue.get(b)
        assert f"upstream {a} cancelled" in tb.result.get("cancelled_reason", "")


class TestOrphanDetection:
    """get_orphaned_tasks finds pending tasks with dead dependencies."""

    def test_finds_orphaned(self, project_row):
        pid = project_row
        a = _mk_task(pid, "dead-parent")
        b = _mk_task(pid, "orphan-child", depends_on=[a])

        task_queue.cancel_task(a)
        orphaned = task_queue.get_orphaned_tasks(pid)
        assert any(t.id == b for t in orphaned)

    def test_no_false_positives(self, project_row):
        """Pending tasks with healthy deps are not orphaned."""
        pid = project_row
        a = _mk_task(pid, "healthy-parent")
        b = _mk_task(pid, "healthy-child", depends_on=[a])

        orphaned = task_queue.get_orphaned_tasks(pid)
        assert not any(t.id == b for t in orphaned)

    def test_completed_dep_not_orphaned(self, project_row):
        pid = project_row
        a = _mk_task(pid, "completed-parent")
        b = _mk_task(pid, "child-of-completed", depends_on=[a])
        task_queue.update_status(a, TaskStatus.COMPLETED, result={"ok": True})

        orphaned = task_queue.get_orphaned_tasks(pid)
        assert not any(t.id == b for t in orphaned)


class TestCancelCycleEndpoint:
    """POST /api/tasks/cancel-cycle cancels all tasks for a cycle."""

    def test_cancel_cycle(self, project_row):
        pid = project_row
        a = _mk_task(pid, "[iterate] generate-bot")
        b = _mk_task(pid, "[iterate] playtest", depends_on=[a])
        c = _mk_task(pid, "[iterate] postmortem", depends_on=[b])

        task_queue.merge_metadata(a, {"cycle_n": 3})
        task_queue.merge_metadata(b, {"cycle_n": 3})
        task_queue.merge_metadata(c, {"cycle_n": 3})

        from src.main import cancel_cycle_tasks

        with patch("src.main.ws_manager") as mock_ws, \
             patch("src.main.cycle_state") as mock_cs:
            mock_ws.broadcast = AsyncMock()
            result = _run(cancel_cycle_tasks(project_id=pid, cycle_n=3))

        assert result["status"] == "ok"
        assert len(result["cancelled"]) == 3

        for tid in [a, b, c]:
            t = task_queue.get(tid)
            assert t.status == TaskStatus.FAILED
            assert t.result["cancelled"] is True


class TestProjectHealth:
    """GET /api/projects/{id}/health surfaces stale state."""

    def test_healthy_when_clean(self, project_row):
        pid = project_row
        _mk_task(pid, "clean-task")

        from src.main import get_project_health
        result = _run(get_project_health(pid))
        assert result["healthy"] is True
        assert len(result["orphaned_tasks"]) == 0
        assert len(result["blocked_tasks"]) == 0

    def test_unhealthy_with_orphans(self, project_row):
        pid = project_row
        a = _mk_task(pid, "dead-parent")
        b = _mk_task(pid, "orphan", depends_on=[a])
        task_queue.cancel_task(a)

        from src.main import get_project_health
        result = _run(get_project_health(pid))
        assert result["healthy"] is False
        assert len(result["orphaned_tasks"]) == 1
        assert result["orphaned_tasks"][0]["id"] == b

    def test_unhealthy_with_blocked(self, project_row):
        pid = project_row
        a = _mk_task(pid, "blocked-task")
        task_queue.stall_task(a, "test stall")

        from src.main import get_project_health
        result = _run(get_project_health(pid))
        assert result["healthy"] is False
        assert len(result["blocked_tasks"]) == 1

    def test_unhealthy_with_pending_proposals(self, project_row):
        pid = project_row
        tid = _mk_task(pid, "proposal-task")
        batch_id = f"batch-health-{pid}"
        _mk_proposal(pid, tid, "qa-engineer", batch_id)

        from src.main import get_project_health
        result = _run(get_project_health(pid))
        assert result["healthy"] is False
        assert len(result["pending_proposals"]) == 1


class TestCleanupStale:
    """POST /api/projects/{id}/cleanup-stale resolves all stale state."""

    def test_cleanup_orphans_and_blocked(self, project_row):
        pid = project_row
        a = _mk_task(pid, "dead")
        b = _mk_task(pid, "orphan", depends_on=[a])
        c = _mk_task(pid, "stalled")
        task_queue.cancel_task(a)
        task_queue.stall_task(c, "test")

        from src.main import cleanup_stale

        with patch("src.main.ws_manager") as mock_ws, \
             patch("src.main.cycle_state") as mock_cs:
            mock_ws.broadcast = AsyncMock()
            mock_cs.get_halt_reason.return_value = "old halt"
            result = _run(cleanup_stale(pid))

        assert result["status"] == "ok"
        assert result["orphaned_cancelled"] >= 1
        assert result["blocked_cancelled"] >= 1
        mock_cs.clear_halt.assert_called_once_with(pid)

        tb = task_queue.get(b)
        assert tb.status == TaskStatus.FAILED
        tc = task_queue.get(c)
        assert tc.status == TaskStatus.FAILED


class TestRunPipelineHealthGate:
    """run_pipeline rejects launch when project is unhealthy."""

    def test_rejects_unhealthy(self, project_row):
        pid = project_row
        a = _mk_task(pid, "stalled-blocker")
        task_queue.stall_task(a, "test stall")

        from src.main import run_pipeline, PipelineRunBody
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(run_pipeline("iterate_artifact", PipelineRunBody(project_id=pid)))
        assert exc_info.value.status_code == 409

    def test_allows_force(self, project_row):
        pid = project_row
        a = _mk_task(pid, "stalled-but-forced")
        task_queue.stall_task(a, "test stall")

        from src.main import run_pipeline, PipelineRunBody
        from fastapi import HTTPException

        try:
            _run(run_pipeline("iterate_artifact", PipelineRunBody(project_id=pid, force=True)))
        except HTTPException as e:
            assert e.status_code != 409, "Should not reject with force=True"
