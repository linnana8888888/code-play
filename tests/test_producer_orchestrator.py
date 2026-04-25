"""Tests for ProducerOrchestrator.

Covers:
  - on_run_start initialises run_status_v1 with correct shape
  - on_step_completed increments steps_done, updates last_event, adds producer note
  - on_step_failed with retry_count=0 adds intervention "retry"
  - on_step_failed with retry_count=2 sets status=blocked and escalates
  - on_cd_verdict REJECT adds intervention note
  - on_run_completed writes run_summary_v1
  - WebSocket broadcast is called on every event (mocked)
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

from src.orchestrator.producer_orchestrator import ProducerOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(broadcast_fn=None, escalate_fn=None):
    """Build a ProducerOrchestrator with mocked dependencies."""
    memory = MagicMock()
    memory.read.return_value = None   # cold start — no persisted status
    memory.write.return_value = 1

    bus = MagicMock()
    bus.post = AsyncMock()
    if escalate_fn:
        bus.escalate = escalate_fn
    else:
        bus.escalate = AsyncMock()

    if broadcast_fn is None:
        broadcast_fn = AsyncMock()

    orch = ProducerOrchestrator(
        project_memory=memory,
        message_bus=bus,
        broadcast_fn=broadcast_fn,
    )
    return orch, memory, bus, broadcast_fn


def run(coro):
    """Run a coroutine synchronously, always using a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# on_run_start
# ---------------------------------------------------------------------------

class TestOnRunStart:
    def test_initialises_run_status_shape(self):
        orch, memory, bus, broadcast = _make_orchestrator()
        project_id = "proj-test-001"
        run_id = str(uuid.uuid4())

        run(orch.on_run_start(project_id, "phased-producer", run_id, 22))

        # run_status_v1 should be in memory cache
        status = orch.get_run_status(project_id)
        assert status is not None
        assert status["run_id"] == run_id
        assert status["pipeline_id"] == "phased-producer"
        assert status["project_id"] == project_id
        assert status["status"] == "running"
        assert status["steps_total"] == 22
        assert status["steps_done"] == 0
        assert status["steps_pending"] == 22
        assert status["current_steps"] == []
        assert status["blocked_steps"] == []
        assert isinstance(status["producer_notes"], list)
        assert len(status["producer_notes"]) >= 1
        assert isinstance(status["interventions"], list)
        assert "updated_at" in status

    def test_broadcasts_producer_status(self):
        broadcast = AsyncMock()
        orch, _, _, _ = _make_orchestrator(broadcast_fn=broadcast)

        run(orch.on_run_start("proj-1", "phased-producer", "run-1", 10))

        broadcast.assert_called_once()
        call_args = broadcast.call_args[0][0]
        assert call_args["type"] == "producer_status"
        assert call_args["project_id"] == "proj-1"
        assert call_args["data"]["status"] == "running"

    def test_posts_to_message_bus(self):
        orch, _, bus, _ = _make_orchestrator()

        run(orch.on_run_start("proj-2", "phased-producer", "run-2", 5))

        bus.post.assert_called_once()
        call_kwargs = bus.post.call_args[1]
        assert call_kwargs["channel"] == "producer"
        assert "🚀" in call_kwargs["content"]

    def test_persists_to_memory(self):
        orch, memory, _, _ = _make_orchestrator()

        run(orch.on_run_start("proj-3", "phased-producer", "run-3", 8))

        memory.write.assert_called()
        write_call = memory.write.call_args
        assert write_call[0][2] == "run_status_v1"  # key


# ---------------------------------------------------------------------------
# on_step_completed
# ---------------------------------------------------------------------------

class TestOnStepCompleted:
    def _setup(self, project_id="proj-sc-001", total=10):
        orch, memory, bus, broadcast = _make_orchestrator()
        run(orch.on_run_start(project_id, "phased-producer", "run-sc", total))
        broadcast.reset_mock()
        return orch, broadcast

    def test_increments_steps_done(self):
        orch, _ = self._setup()
        run(orch.on_step_completed("proj-sc-001", "concept", "concept-agent", ["concept_options_v1"]))

        status = orch.get_run_status("proj-sc-001")
        assert status["steps_done"] == 1
        assert status["steps_pending"] == 9

    def test_updates_last_event(self):
        orch, _ = self._setup()
        run(orch.on_step_completed("proj-sc-001", "concept", "concept-agent", ["concept_options_v1"]))

        status = orch.get_run_status("proj-sc-001")
        assert "concept" in status["last_event"]
        assert "concept_options_v1" in status["last_event"]

    def test_adds_producer_note(self):
        orch, _ = self._setup()
        run(orch.on_step_completed("proj-sc-001", "concept", "concept-agent", ["concept_options_v1"]))

        status = orch.get_run_status("proj-sc-001")
        notes = status["producer_notes"]
        # Should have at least the start note + completion note
        assert len(notes) >= 2
        last_note = notes[-1]["note"]
        assert "concept" in last_note

    def test_removes_from_current_steps(self):
        orch, _ = self._setup()
        # Manually add to current_steps first
        run(orch.on_step_started("proj-sc-001", "concept", "concept-agent"))
        run(orch.on_step_completed("proj-sc-001", "concept", "concept-agent", []))

        status = orch.get_run_status("proj-sc-001")
        assert "concept" not in status["current_steps"]

    def test_broadcasts_on_completion(self):
        orch, broadcast = self._setup()
        run(orch.on_step_completed("proj-sc-001", "concept", "concept-agent", ["concept_options_v1"]))

        broadcast.assert_called_once()
        call_args = broadcast.call_args[0][0]
        assert call_args["type"] == "producer_status"

    def test_detects_phase_transition(self):
        orch, _ = self._setup()
        run(orch.on_step_completed("proj-sc-001", "mechanics", "game-designer", ["mechanics_v1"]))

        status = orch.get_run_status("proj-sc-001")
        assert status["phase"] == "mechanics"


# ---------------------------------------------------------------------------
# on_step_failed
# ---------------------------------------------------------------------------

class TestOnStepFailed:
    def _setup(self, project_id="proj-sf-001"):
        orch, memory, bus, broadcast = _make_orchestrator()
        run(orch.on_run_start(project_id, "phased-producer", "run-sf", 10))
        broadcast.reset_mock()
        return orch, bus, broadcast

    def test_retry_count_0_adds_retry_intervention(self):
        orch, _, _ = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "LLM timeout", retry_count=0))

        status = orch.get_run_status("proj-sf-001")
        interventions = status["interventions"]
        assert any("retry" in i["action"] for i in interventions)

    def test_retry_count_1_adds_retry_intervention(self):
        orch, _, _ = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "LLM timeout", retry_count=1))

        status = orch.get_run_status("proj-sf-001")
        interventions = status["interventions"]
        assert any("retry" in i["action"] for i in interventions)
        # Status should NOT be blocked yet
        assert status["status"] == "running"

    def test_retry_count_2_sets_status_blocked(self):
        orch, _, _ = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "Permanent error", retry_count=2))

        status = orch.get_run_status("proj-sf-001")
        assert status["status"] == "blocked"

    def test_retry_count_2_escalates_to_human(self):
        orch, bus, _ = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "Permanent error", retry_count=2))

        bus.escalate.assert_called_once()
        escalation_arg = bus.escalate.call_args[0][0]
        assert escalation_arg.project_id == "proj-sf-001"
        assert "concept" in escalation_arg.question

    def test_adds_to_blocked_steps(self):
        orch, _, _ = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "error", retry_count=0))

        status = orch.get_run_status("proj-sf-001")
        assert "concept" in status["blocked_steps"]

    def test_broadcasts_with_warning_severity(self):
        orch, _, broadcast = self._setup()
        run(orch.on_step_failed("proj-sf-001", "concept", "error", retry_count=0))

        broadcast.assert_called_once()
        call_data = broadcast.call_args[0][0]["data"]
        assert call_data["severity"] == "warning"


# ---------------------------------------------------------------------------
# on_cd_verdict
# ---------------------------------------------------------------------------

class TestOnCdVerdict:
    def _setup(self, project_id="proj-cd-001"):
        orch, memory, bus, broadcast = _make_orchestrator()
        run(orch.on_run_start(project_id, "phased-producer", "run-cd", 10))
        broadcast.reset_mock()
        return orch, broadcast

    def test_approve_adds_note(self):
        orch, _ = self._setup()
        run(orch.on_cd_verdict("proj-cd-001", "cd-concept-check", "APPROVE", "Solid concept"))

        status = orch.get_run_status("proj-cd-001")
        notes_text = " ".join(n["note"] for n in status["producer_notes"])
        assert "cd-concept-check" in notes_text
        assert "APPROVE" in notes_text

    def test_reject_adds_intervention(self):
        orch, _ = self._setup()
        run(orch.on_cd_verdict("proj-cd-001", "cd-concept-check", "REJECT", "Needs more originality"))

        status = orch.get_run_status("proj-cd-001")
        interventions = status["interventions"]
        assert any("re-queuing" in i["action"] for i in interventions)

    def test_concerns_adds_note_with_flag(self):
        orch, _ = self._setup()
        run(orch.on_cd_verdict("proj-cd-001", "cd-mechanics-check", "CONCERNS", "Pacing issues"))

        status = orch.get_run_status("proj-cd-001")
        notes_text = " ".join(n["note"] for n in status["producer_notes"])
        assert "CONCERNS" in notes_text

    def test_broadcasts_on_every_verdict(self):
        orch, broadcast = self._setup()
        run(orch.on_cd_verdict("proj-cd-001", "cd-concept-check", "APPROVE", ""))

        broadcast.assert_called_once()
        assert broadcast.call_args[0][0]["type"] == "producer_status"

    def test_reject_broadcasts_warning(self):
        orch, broadcast = self._setup()
        run(orch.on_cd_verdict("proj-cd-001", "cd-concept-check", "REJECT", "Bad"))

        call_data = broadcast.call_args[0][0]["data"]
        assert call_data["severity"] == "warning"


# ---------------------------------------------------------------------------
# on_run_completed
# ---------------------------------------------------------------------------

class TestOnRunCompleted:
    def _setup(self, project_id="proj-rc-001", steps=10):
        orch, memory, bus, broadcast = _make_orchestrator()
        run(orch.on_run_start(project_id, "phased-producer", "run-rc", steps))
        broadcast.reset_mock()
        memory.write.reset_mock()
        bus.post.reset_mock()
        return orch, memory, bus, broadcast

    def test_writes_run_summary_v1(self):
        orch, memory, _, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "shipped"))

        # Check that run_summary_v1 was written
        write_calls = memory.write.call_args_list
        summary_calls = [c for c in write_calls if c[0][2] == "run_summary_v1"]
        assert len(summary_calls) == 1

        summary_json = summary_calls[0][0][3]
        summary = json.loads(summary_json)
        assert summary["outcome"] == "shipped"
        assert "steps_completed" in summary
        assert "interventions" in summary
        assert "completed_at" in summary

    def test_sets_status_completed_for_shipped(self):
        orch, _, _, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "shipped"))

        status = orch.get_run_status("proj-rc-001")
        assert status["status"] == "completed"

    def test_sets_status_halted_for_halted(self):
        orch, _, _, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "halted"))

        status = orch.get_run_status("proj-rc-001")
        assert status["status"] == "halted"

    def test_broadcasts_final_status(self):
        orch, _, _, broadcast = self._setup()
        run(orch.on_run_completed("proj-rc-001", "shipped"))

        broadcast.assert_called_once()
        assert broadcast.call_args[0][0]["type"] == "producer_status"

    def test_posts_to_message_bus(self):
        orch, _, bus, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "shipped"))

        bus.post.assert_called_once()
        content = bus.post.call_args[1]["content"]
        assert "✅" in content

    def test_posts_halted_message_for_halted(self):
        orch, _, bus, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "halted"))

        content = bus.post.call_args[1]["content"]
        assert "🛑" in content

    def test_summary_includes_duration(self):
        orch, memory, _, _ = self._setup()
        run(orch.on_run_completed("proj-rc-001", "shipped"))

        write_calls = memory.write.call_args_list
        summary_calls = [c for c in write_calls if c[0][2] == "run_summary_v1"]
        summary = json.loads(summary_calls[0][0][3])
        # duration_s may be 0 in fast tests but key must exist
        assert "duration_s" in summary


# ---------------------------------------------------------------------------
# on_schema_violation
# ---------------------------------------------------------------------------

class TestOnSchemaViolation:
    def test_adds_note_and_broadcasts_warning(self):
        orch, _, _, broadcast = _make_orchestrator()
        run(orch.on_run_start("proj-sv-001", "phased-producer", "run-sv", 5))
        broadcast.reset_mock()

        run(orch.on_schema_violation(
            "proj-sv-001", "build", "game_html_v1", ["missing key: title", "size < 1024"]
        ))

        status = orch.get_run_status("proj-sv-001")
        notes_text = " ".join(n["note"] for n in status["producer_notes"])
        assert "game_html_v1" in notes_text

        broadcast.assert_called_once()
        call_data = broadcast.call_args[0][0]["data"]
        assert call_data["severity"] == "warning"


# ---------------------------------------------------------------------------
# Broadcast called on every event
# ---------------------------------------------------------------------------

class TestBroadcastOnEveryEvent:
    """Verify that broadcast is called for each hook method."""

    def test_broadcast_called_for_all_hooks(self):
        broadcast = AsyncMock()
        orch, _, _, _ = _make_orchestrator(broadcast_fn=broadcast)
        pid = "proj-all-001"

        run(orch.on_run_start(pid, "phased-producer", "run-all", 5))
        run(orch.on_step_started(pid, "concept", "agent-1"))
        run(orch.on_step_completed(pid, "concept", "agent-1", ["concept_options_v1"]))
        run(orch.on_step_failed(pid, "mechanics", "timeout", retry_count=0))
        run(orch.on_cd_verdict(pid, "cd-concept-check", "APPROVE", "OK"))
        run(orch.on_schema_violation(pid, "build", "game_html_v1", ["error"]))
        run(orch.on_run_completed(pid, "shipped"))

        # Each of the 7 hook calls should have triggered at least one broadcast
        assert broadcast.call_count >= 7

    def test_broadcast_type_always_producer_status(self):
        broadcast = AsyncMock()
        orch, _, _, _ = _make_orchestrator(broadcast_fn=broadcast)
        pid = "proj-type-001"

        run(orch.on_run_start(pid, "phased-producer", "run-t", 3))
        run(orch.on_step_started(pid, "concept", "agent-1"))
        run(orch.on_step_completed(pid, "concept", "agent-1", []))
        run(orch.on_run_completed(pid, "shipped"))

        for call in broadcast.call_args_list:
            assert call[0][0]["type"] == "producer_status"


# ---------------------------------------------------------------------------
# get_run_status / get_producer_notes
# ---------------------------------------------------------------------------

class TestAccessors:
    def test_get_run_status_returns_none_before_run_start(self):
        orch, _, _, _ = _make_orchestrator()
        assert orch.get_run_status("no-such-project") is None

    def test_get_producer_notes_returns_empty_before_run_start(self):
        orch, _, _, _ = _make_orchestrator()
        assert orch.get_producer_notes("no-such-project") == []

    def test_get_producer_notes_returns_notes_after_events(self):
        orch, _, _, _ = _make_orchestrator()
        pid = "proj-notes-001"
        run(orch.on_run_start(pid, "phased-producer", "run-n", 5))
        run(orch.on_step_completed(pid, "concept", "agent", ["concept_options_v1"]))

        notes = orch.get_producer_notes(pid)
        assert len(notes) >= 2
        for note in notes:
            assert "at" in note
            assert "note" in note
