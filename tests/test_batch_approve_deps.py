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
