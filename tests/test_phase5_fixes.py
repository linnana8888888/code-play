"""Tests for Phase 5 infrastructure fixes.

Fix 2: review-cap-gate recognized as human gate (_gate_context)
Fix 3: BUTLER_SKIP test mode for itchio_publish
Fix 4: Force-complete API endpoint (PATCH /api/tasks/{id})
Fix 5: upstream_timeout failure category for LEGO proxy 504s
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


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


# ---------------------------------------------------------------------------
# Fix 2 — review-cap-gate recognized as human gate
# ---------------------------------------------------------------------------

class TestReviewCapGateContext:
    """_gate_context() must return a valid dict for review-cap-gate tasks."""

    def _make_task(self, metadata=None, created_by="pipeline:phased-producer", title="review-cap-gate"):
        task = MagicMock()
        task.created_by = created_by
        task.title = title
        task.metadata = metadata or {}
        task.description = "Review cap reached. Choose: approve / halt / extend."
        task.depends_on = []
        task.project_id = "proj-test"
        return task

    def _get_gate_context(self):
        # Import lazily to avoid FastAPI startup side effects
        import importlib
        import src.main as main_mod
        return main_mod._gate_context

    def test_review_cap_gate_returns_valid_context(self):
        _gate_context = self._get_gate_context()
        task = self._make_task(metadata={
            "review_gate_kind": "review_cap",
            "linked_review_task_id": "task-abc123",
            "review_round_n": 3,
        })
        ctx = _gate_context(task)
        assert ctx, "Expected non-empty context for review-cap-gate task"
        assert ctx["step_id"] == "review-cap-gate"
        assert ctx["review_gate_kind"] == "review_cap"
        assert ctx["linked_review_task_id"] == "task-abc123"
        assert ctx["review_round_n"] == 3

    def test_review_cap_gate_context_has_required_keys(self):
        _gate_context = self._get_gate_context()
        task = self._make_task(metadata={
            "review_gate_kind": "review_cap",
            "linked_review_task_id": "task-xyz",
            "review_round_n": 1,
        })
        ctx = _gate_context(task)
        required_keys = {"pipeline", "step_id", "review_gate_kind", "review_of", "prompt"}
        for key in required_keys:
            assert key in ctx, f"Missing key: {key}"

    def test_non_review_cap_task_returns_empty(self):
        """Tasks without review_gate_kind should not match the review-cap path."""
        _gate_context = self._get_gate_context()
        task = self._make_task(metadata={"some_other_key": "value"})
        # This task has pipeline: prefix but no matching step in YAML — should return {}
        ctx = _gate_context(task)
        # Either empty (no pipeline match) or non-review-cap — either way
        # review_gate_kind must not be set
        assert ctx.get("review_gate_kind") != "review_cap"

    def test_review_cap_gate_without_pipeline_prefix(self):
        """review_gate_kind check should work regardless of created_by prefix."""
        _gate_context = self._get_gate_context()
        task = self._make_task(
            metadata={"review_gate_kind": "review_cap", "linked_review_task_id": "t1", "review_round_n": 2},
            created_by="orchestrator:review_loop",  # not pipeline: prefix
        )
        ctx = _gate_context(task)
        assert ctx, "review_gate_kind check should fire before created_by check"
        assert ctx["review_gate_kind"] == "review_cap"


# ---------------------------------------------------------------------------
# Fix 2 — approve_gate handles review-cap-gate actions
# ---------------------------------------------------------------------------

class TestReviewCapGateApprove:
    """approve_gate must handle halt / extend / default-approve for review-cap-gate."""

    def _make_task(self, metadata=None, project_id="proj-test"):
        task = MagicMock()
        task.id = "task-gate-001"
        task.project_id = project_id
        task.created_by = "orchestrator:review_loop"
        task.title = "review-cap-gate"
        task.description = "Review cap reached."
        task.depends_on = []
        task.metadata = metadata or {
            "review_gate_kind": "review_cap",
            "linked_review_task_id": "task-review-001",
            "review_round_n": 3,
        }
        return task

    def test_approve_default_advances_pipeline(self):
        import src.main as main_mod

        task = self._make_task()
        body = MagicMock()
        body.feedback = "approved"
        body.budget_decision = None
        body.selected = []
        body.custom = []

        with (
            patch.object(main_mod.task_queue, "get", return_value=task),
            patch.object(main_mod.task_queue, "update_status") as mock_update,
            patch.object(main_mod.ws_manager, "broadcast", new_callable=AsyncMock),
            patch("src.main._advance_pipeline", new_callable=AsyncMock) as mock_advance,
        ):
            result = _run(main_mod.approve_gate(task.id, body))

        assert result["status"] == "approved"
        assert result.get("review_cap_action") == "approved"
        mock_update.assert_called_once()
        mock_advance.assert_awaited_once_with(task.project_id)

    def test_approve_halt_sets_halt_reason(self):
        import src.main as main_mod
        from src.iteration import cycle_state as cs

        task = self._make_task()
        body = MagicMock()
        body.feedback = "halt — too many rounds"
        body.budget_decision = None
        body.selected = []
        body.custom = []

        with (
            patch.object(main_mod.task_queue, "get", return_value=task),
            patch.object(main_mod.task_queue, "update_status"),
            patch.object(main_mod.ws_manager, "broadcast", new_callable=AsyncMock),
            patch("src.main._advance_pipeline", new_callable=AsyncMock),
            patch.object(cs, "set_halt") as mock_halt,
        ):
            result = _run(main_mod.approve_gate(task.id, body))

        assert result.get("review_cap_action") == "halt"
        mock_halt.assert_called_once_with(
            task.project_id, "review_rounds_exhausted", created_by=f"gate:{task.id}"
        )

    def test_approve_extend_raises_budget(self):
        import src.main as main_mod
        from src.iteration import review_state as rs

        task = self._make_task()
        body = MagicMock()
        body.feedback = "extend — keep going"
        body.budget_decision = None
        body.selected = []
        body.custom = []

        with (
            patch.object(main_mod.task_queue, "get", return_value=task),
            patch.object(main_mod.task_queue, "update_status"),
            patch.object(main_mod.ws_manager, "broadcast", new_callable=AsyncMock),
            patch("src.main._advance_pipeline", new_callable=AsyncMock),
            patch.object(rs, "get_budget", return_value=3) as mock_get,
            patch.object(rs, "set_budget") as mock_set,
        ):
            result = _run(main_mod.approve_gate(task.id, body))

        assert result.get("review_cap_action") == "extend"
        mock_set.assert_called_once_with(
            task.project_id, 5, created_by=f"gate:{task.id}"
        )


# ---------------------------------------------------------------------------
# Fix 3 — BUTLER_SKIP test mode for itchio_publish
# ---------------------------------------------------------------------------

class TestButlerSkip:
    """_tool_itchio_publish must return simulated success when BUTLER_SKIP=true."""

    def _get_executor(self):
        from src.runtime.tool_executor import ToolExecutor
        return ToolExecutor()

    def test_butler_skip_true_returns_simulated(self, tmp_path):
        executor = self._get_executor()
        args = {
            "build_dir": str(tmp_path),
            "target": "testuser/testgame:html5",
        }
        with patch.dict(os.environ, {"BUTLER_SKIP": "true"}):
            result_str = _run(executor._tool_itchio_publish(args))
        result = json.loads(result_str)
        assert result["status"] == "simulated"
        assert "BUTLER_SKIP=true" in result["note"]
        assert result["target"] == args["target"]

    def test_butler_skip_1_returns_simulated(self, tmp_path):
        executor = self._get_executor()
        args = {
            "build_dir": str(tmp_path),
            "target": "testuser/testgame:html5",
        }
        with patch.dict(os.environ, {"BUTLER_SKIP": "1"}):
            result_str = _run(executor._tool_itchio_publish(args))
        result = json.loads(result_str)
        assert result["status"] == "simulated"

    def test_butler_skip_false_proceeds_normally(self, tmp_path):
        """When BUTLER_SKIP is not set, the function should proceed to butler check."""
        executor = self._get_executor()
        # Create a minimal build dir with index.html
        (tmp_path / "index.html").write_text("<html></html>")
        args = {
            "build_dir": str(tmp_path),
            "target": "testuser/testgame:html5",
        }
        env = {k: v for k, v in os.environ.items() if k != "BUTLER_SKIP"}
        with patch.dict(os.environ, env, clear=True):
            result_str = _run(executor._tool_itchio_publish(args))
        result = json.loads(result_str)
        # Should NOT be simulated — should fail with butler not found
        assert result["status"] != "simulated"
        assert result["status"] == "error"
        assert "butler" in result.get("error", "").lower()

    def test_butler_skip_includes_build_dir(self, tmp_path):
        executor = self._get_executor()
        args = {
            "build_dir": str(tmp_path),
            "target": "testuser/testgame:html5",
        }
        with patch.dict(os.environ, {"BUTLER_SKIP": "true"}):
            result_str = _run(executor._tool_itchio_publish(args))
        result = json.loads(result_str)
        assert "build_dir" in result


# ---------------------------------------------------------------------------
# Fix 4 — Force-complete API endpoint
# ---------------------------------------------------------------------------

def _insert_project(pid: str):
    """Insert a minimal project row so FK constraints pass."""
    from src.database import get_studio_db
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, auto_iterate, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "fix4 test", "", "html5", None, None, 0, 0, now, now),
        )


def _cleanup_project(pid: str):
    from src.database import get_studio_db
    with get_studio_db() as db:
        db.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


class TestForceCompleteTask:
    """PATCH /api/tasks/{id} must apply status + result to force-complete a blocked task."""

    def test_task_update_model_has_status_and_result(self):
        from src.models.tasks import TaskUpdate
        update = TaskUpdate(status="completed", result="Force completed by operator")
        assert update.status == "completed"
        assert update.result == "Force completed by operator"

    def test_task_queue_update_applies_status(self):
        """TaskQueue.update() must write status to the DB."""
        from src.orchestrator.task_queue import TaskQueue
        from src.models.tasks import TaskCreate, TaskStatus, TaskUpdate

        pid = "proj-fix4-test"
        _insert_project(pid)
        try:
            tq = TaskQueue()
            task = tq.create(TaskCreate(
                project_id=pid,
                title="Test force-complete task",
                description="Blocked task to force-complete",
                created_by="test",
            ))
            # Manually block the task
            tq.update_status(task.id, TaskStatus.BLOCKED, result={"error": "stuck"})
            blocked = tq.get(task.id)
            assert blocked.status == TaskStatus.BLOCKED

            # Force-complete via update()
            update_patch = TaskUpdate(status="completed", result="Operator force-completed")
            updated = tq.update(task.id, update_patch)
            assert updated is not None
            assert updated.status == TaskStatus.COMPLETED
            assert updated.result is not None
            assert updated.result.get("force_completed") is True
        finally:
            _cleanup_project(pid)

    def test_task_queue_update_result_is_json_decodable(self):
        """result column must remain JSON-decodable after a force-complete."""
        from src.orchestrator.task_queue import TaskQueue
        from src.models.tasks import TaskCreate, TaskStatus, TaskUpdate

        pid = "proj-fix4-result"
        _insert_project(pid)
        try:
            tq = TaskQueue()
            task = tq.create(TaskCreate(
                project_id=pid,
                title="Test result JSON",
                created_by="test",
            ))
            tq.update_status(task.id, TaskStatus.BLOCKED)
            update_patch = TaskUpdate(status="completed", result="some summary text")
            updated = tq.update(task.id, update_patch)
            # result must be a dict (not a raw string)
            assert isinstance(updated.result, dict)
            assert "summary" in updated.result or "force_completed" in updated.result
        finally:
            _cleanup_project(pid)

    def test_patch_task_endpoint_force_completes(self):
        """PATCH /api/tasks/{id} endpoint must apply status + result."""
        import src.main as main_mod
        from src.models.tasks import TaskCreate, TaskStatus, TaskUpdate

        pid = "proj-fix4-api"
        _insert_project(pid)
        try:
            task = main_mod.task_queue.create(TaskCreate(
                project_id=pid,
                title="API force-complete test",
                created_by="test",
            ))
            main_mod.task_queue.update_status(task.id, TaskStatus.BLOCKED, result={"error": "blocked"})

            body = TaskUpdate(status="completed", result="Manually resolved by operator")

            with patch.object(main_mod.ws_manager, "broadcast", new_callable=AsyncMock):
                result = _run(main_mod.patch_task(task.id, body))

            assert result["status"] == "completed"
        finally:
            _cleanup_project(pid)

    def test_patch_task_returns_404_for_unknown_id(self):
        """PATCH /api/tasks/{id} must return 404 for unknown task IDs."""
        import src.main as main_mod
        from src.models.tasks import TaskUpdate
        from fastapi import HTTPException

        body = TaskUpdate(status="completed")
        with pytest.raises(HTTPException) as exc_info:
            _run(main_mod.patch_task("task-does-not-exist-xyz", body))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Fix 5 — upstream_timeout failure category
# ---------------------------------------------------------------------------

class TestUpstreamTimeoutClassification:
    """_classify_failure must return 'upstream_timeout' for UpstreamTimeoutError."""

    def test_upstream_timeout_error_classified_correctly(self):
        import src.main as main_mod
        from src.runtime.llm_router import UpstreamTimeoutError

        exc = UpstreamTimeoutError("openai upstream 504 after 3 retries")
        category = main_mod._classify_failure(str(exc), exc=exc)
        assert category == "upstream_timeout"

    def test_regular_504_string_classified_as_transient(self):
        import src.main as main_mod

        # Without the exc kwarg, a 504 string still classifies as transient
        category = main_mod._classify_failure("HTTP 504 gateway timeout")
        assert category == "transient"

    def test_permanent_error_still_permanent(self):
        import src.main as main_mod

        category = main_mod._classify_failure("AttributeError: 'NoneType' has no attribute 'foo'")
        assert category == "permanent"

    def test_upstream_timeout_error_is_importable(self):
        from src.runtime.llm_router import UpstreamTimeoutError
        assert issubclass(UpstreamTimeoutError, RuntimeError)

    def test_context_token_warning_threshold(self):
        """max_context_tokens_before_summarize should default to 8000."""
        import src.runtime.llm_router as router_mod
        assert router_mod.max_context_tokens_before_summarize == 8000

    def test_context_token_warning_env_override(self):
        """MAX_CONTEXT_TOKENS_BEFORE_SUMMARIZE env var should override the default."""
        import importlib
        with patch.dict(os.environ, {"MAX_CONTEXT_TOKENS_BEFORE_SUMMARIZE": "4000"}):
            import src.runtime.llm_router as router_mod
            importlib.reload(router_mod)
            assert router_mod.max_context_tokens_before_summarize == 4000
        # Reload again to restore default
        importlib.reload(router_mod)
