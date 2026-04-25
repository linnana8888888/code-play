"""ProducerOrchestrator — owns a pipeline run end-to-end.

Called by main.py hooks on every step transition. Updates run_status_v1 in
project memory and broadcasts producer_status events over WebSocket so the
dashboard can show a live producer feed.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

from src.models.messages import EscalationRequest

logger = logging.getLogger(__name__)

# Phase order for transition detection
_PHASE_ORDER = ["concept", "mechanics", "laf", "tech", "build", "qa", "publish"]

# Step-id prefix → phase name mapping
_STEP_PHASE_MAP: dict[str, str] = {
    "concept": "concept",
    "gate-concept": "concept",
    "cd-concept": "concept",
    "mechanics": "mechanics",
    "gate-mechanics": "mechanics",
    "cd-mechanics": "mechanics",
    "style-research": "laf",
    "look-and-feel": "laf",
    "gate-laf": "laf",
    "cd-laf": "laf",
    "tech-plan": "tech",
    "gate-tech": "tech",
    "build": "build",
    "telemetry": "build",
    "qa": "qa",
    "gate-qa": "qa",
    "review": "qa",
    "scaffold": "qa",
    "publish": "publish",
    "gate-publish": "publish",
}


def _phase_for_step(step_id: str) -> str | None:
    """Infer phase from step id prefix."""
    for prefix, phase in _STEP_PHASE_MAP.items():
        if step_id.startswith(prefix):
            return phase
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProducerOrchestrator:
    """
    Owns a pipeline run end-to-end. Called by main.py hooks on every
    step transition. Updates run_status_v1 in project memory and broadcasts
    producer_status events over WebSocket so the dashboard can show a live
    producer feed.

    Usage:
        producer_orchestrator = ProducerOrchestrator(
            project_memory=project_memory,
            message_bus=message_bus,
            broadcast_fn=ws_manager.broadcast,
        )
    """

    def __init__(
        self,
        project_memory,
        message_bus,
        broadcast_fn: Callable[[dict], Awaitable[None]],
    ):
        self._memory = project_memory
        self._bus = message_bus
        self._broadcast = broadcast_fn
        # In-memory cache of run status per project_id
        self._run_status: dict[str, dict] = {}
        # Track run start times for duration calculation
        self._run_start_times: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_status(self, project_id: str) -> dict | None:
        """Load run_status_v1 from project memory (falls back to in-memory cache)."""
        raw = self._memory.read(project_id, "artifact", "run_status_v1")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return self._run_status.get(project_id)

    def _save_status(self, project_id: str, status: dict) -> None:
        """Persist run_status_v1 to project memory and update in-memory cache."""
        status["updated_at"] = _now_iso()
        self._run_status[project_id] = status
        try:
            self._memory.write(
                project_id,
                "artifact",
                "run_status_v1",
                json.dumps(status, indent=2),
                created_by="producer-orchestrator",
            )
        except Exception as exc:
            logger.warning(f"[{project_id}] Failed to persist run_status_v1: {exc}")

    async def _broadcast_status(
        self,
        project_id: str,
        status: dict,
        note: str = "",
        severity: str = "info",
    ) -> None:
        """Broadcast a producer_status WebSocket event."""
        payload = {
            "type": "producer_status",
            "project_id": project_id,
            "data": {
                "status": status.get("status", "running"),
                "phase": status.get("phase", ""),
                "last_event": status.get("last_event", ""),
                "note": note or (status.get("producer_notes") or [{}])[-1].get("note", ""),
                "severity": severity,
                "run_status": status,
            },
        }
        try:
            await self._broadcast(payload)
        except Exception as exc:
            logger.warning(f"[{project_id}] Failed to broadcast producer_status: {exc}")

    def _add_note(self, status: dict, note: str) -> None:
        """Append a timestamped producer note."""
        if "producer_notes" not in status:
            status["producer_notes"] = []
        status["producer_notes"].append({"at": _now_iso(), "note": note})

    def _add_intervention(self, status: dict, intervention: str) -> None:
        """Append an intervention record."""
        if "interventions" not in status:
            status["interventions"] = []
        status["interventions"].append({"at": _now_iso(), "action": intervention})

    def _detect_phase(self, status: dict, step_id: str) -> str:
        """Return the current phase, updating if the step implies a new one."""
        inferred = _phase_for_step(step_id)
        if inferred:
            current = status.get("phase", "")
            if not current or _PHASE_ORDER.index(inferred) >= _PHASE_ORDER.index(current) if current in _PHASE_ORDER else True:
                return inferred
        return status.get("phase", "concept")

    # ------------------------------------------------------------------
    # Public hook methods
    # ------------------------------------------------------------------

    async def on_run_start(
        self,
        project_id: str,
        pipeline_id: str,
        run_id: str,
        total_steps: int,
    ) -> None:
        """Initialise run_status_v1 and announce pipeline start."""
        status = {
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "project_id": project_id,
            "phase": "concept",
            "status": "running",
            "steps_total": total_steps,
            "steps_done": 0,
            "steps_pending": total_steps,
            "current_steps": [],
            "blocked_steps": [],
            "budget_used_pct": 0,
            "last_event": f"Pipeline started — {total_steps} steps, {pipeline_id}",
            "producer_notes": [],
            "interventions": [],
            "updated_at": _now_iso(),
        }
        self._add_note(status, f"Pipeline started — {total_steps} steps, {pipeline_id}")
        self._run_start_times[project_id] = datetime.now(timezone.utc)
        self._save_status(project_id, status)

        await self._broadcast_status(
            project_id,
            status,
            note=f"Pipeline started — {total_steps} steps, {pipeline_id}",
        )

        try:
            await self._bus.post(
                project_id=project_id,
                channel="producer",
                sender="producer-orchestrator",
                content=f"🚀 Run started — {pipeline_id} ({total_steps} steps)",
            )
        except Exception as exc:
            logger.warning(f"[{project_id}] message_bus.post failed: {exc}")

    async def on_step_started(
        self,
        project_id: str,
        step_id: str,
        agent_id: str,
    ) -> None:
        """Record that a step has started running."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_step_started called before on_run_start — ignoring")
            return

        if step_id not in status.get("current_steps", []):
            status.setdefault("current_steps", []).append(step_id)

        status["phase"] = self._detect_phase(status, step_id)
        status["last_event"] = f"{step_id} started (agent: {agent_id})"
        self._save_status(project_id, status)

        await self._broadcast_status(
            project_id,
            status,
            note=f"{step_id} started (agent: {agent_id})",
        )

    async def on_step_completed(
        self,
        project_id: str,
        step_id: str,
        agent_id: str,
        artifacts_written: list[str],
    ) -> None:
        """Record step completion, update counts, detect phase transitions."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_step_completed called before on_run_start — ignoring")
            return

        # Move from current → done
        current = status.get("current_steps", [])
        if step_id in current:
            current.remove(step_id)
        status["current_steps"] = current

        status["steps_done"] = status.get("steps_done", 0) + 1
        total = status.get("steps_total", 0)
        done = status["steps_done"]
        status["steps_pending"] = max(0, total - done)

        # Detect phase transition
        new_phase = self._detect_phase(status, step_id)
        old_phase = status.get("phase", "")
        if new_phase != old_phase and new_phase in _PHASE_ORDER:
            phase_note = f"Phase transition: {old_phase} → {new_phase}"
            self._add_note(status, phase_note)
        status["phase"] = new_phase

        artifacts_str = ", ".join(artifacts_written) if artifacts_written else "(none)"
        event = f"{step_id} completed → {artifacts_str}"
        status["last_event"] = event
        note_text = f"{step_id} completed → {artifacts_str}"
        self._add_note(status, note_text)

        self._save_status(project_id, status)

        await self._broadcast_status(project_id, status, note=note_text)

    async def on_step_failed(
        self,
        project_id: str,
        step_id: str,
        reason: str,
        retry_count: int,
    ) -> None:
        """Handle step failure: retry if under threshold, escalate otherwise."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_step_failed called before on_run_start — ignoring")
            return

        # Remove from current, add to blocked
        current = status.get("current_steps", [])
        if step_id in current:
            current.remove(step_id)
        status["current_steps"] = current

        blocked = status.get("blocked_steps", [])
        if step_id not in blocked:
            blocked.append(step_id)
        status["blocked_steps"] = blocked

        status["last_event"] = f"{step_id} FAILED (retry {retry_count}): {reason[:200]}"

        if retry_count < 2:
            intervention = f"retry {step_id} (attempt {retry_count + 1})"
            self._add_intervention(status, intervention)
            note_text = f"{step_id} failed (attempt {retry_count + 1}/2): {reason[:200]}. Retrying."
            self._add_note(status, note_text)
            self._save_status(project_id, status)

            await self._broadcast_status(
                project_id, status, note=note_text, severity="warning"
            )
        else:
            # Escalate to human
            status["status"] = "blocked"
            intervention = f"escalate {step_id} to human after {retry_count + 1} failures"
            self._add_intervention(status, intervention)
            note_text = (
                f"{step_id} failed {retry_count + 1} times — escalating to human. "
                f"Last reason: {reason[:200]}"
            )
            self._add_note(status, note_text)
            self._save_status(project_id, status)

            await self._broadcast_status(
                project_id, status, note=note_text, severity="warning"
            )

            try:
                await self._bus.escalate(
                    EscalationRequest(
                        project_id=project_id,
                        agent_instance_id="producer-orchestrator",
                        question=(
                            f"Step '{step_id}' has failed {retry_count + 1} times. "
                            f"Last reason: {reason[:400]}\n\n"
                            "How should we proceed?"
                        ),
                        options=["retry", "skip", "halt"],
                        context=f"Pipeline: {status.get('pipeline_id', 'unknown')} | Phase: {status.get('phase', 'unknown')}",
                        blocking=False,
                    )
                )
            except Exception as exc:
                logger.warning(f"[{project_id}] escalate failed: {exc}")

    async def on_cd_verdict(
        self,
        project_id: str,
        step_id: str,
        verdict: str,
        reason: str,
    ) -> None:
        """Record a CD verdict and take action on REJECT."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_cd_verdict called before on_run_start — ignoring")
            return

        verdict_upper = verdict.upper()
        note_text = f"CD {step_id}: {verdict_upper} — {reason[:200]}"
        self._add_note(status, note_text)
        status["last_event"] = note_text

        severity = "info"
        if verdict_upper == "REJECT":
            intervention = f"re-queuing upstream agent for {step_id} (CD REJECT)"
            self._add_intervention(status, intervention)
            severity = "warning"
        elif verdict_upper == "CONCERNS":
            concern_note = f"CD {step_id} raised CONCERNS — flagging for human attention: {reason[:200]}"
            self._add_note(status, concern_note)
            severity = "warning"

        self._save_status(project_id, status)
        await self._broadcast_status(project_id, status, note=note_text, severity=severity)

    async def on_schema_violation(
        self,
        project_id: str,
        step_id: str,
        artifact_key: str,
        errors: list[str],
    ) -> None:
        """Record a schema validation failure."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_schema_violation called before on_run_start — ignoring")
            return

        errors_str = "; ".join(errors[:5]) if errors else "unknown"
        note_text = f"Schema violation in {artifact_key}: {errors_str}"
        self._add_note(status, note_text)
        status["last_event"] = note_text

        self._save_status(project_id, status)
        await self._broadcast_status(project_id, status, note=note_text, severity="warning")

    async def on_run_completed(
        self,
        project_id: str,
        outcome: str,
    ) -> None:
        """Finalise the run: write run_summary_v1, broadcast completion."""
        status = self._load_status(project_id)
        if not status:
            logger.warning(f"[{project_id}] on_run_completed called before on_run_start — ignoring")
            return

        # Calculate duration
        start_time = self._run_start_times.get(project_id)
        duration_s = None
        if start_time:
            duration_s = int((datetime.now(timezone.utc) - start_time).total_seconds())

        # Determine terminal status
        outcome_lower = outcome.lower()
        if outcome_lower in ("shipped", "completed"):
            status["status"] = "completed"
            status_emoji = "✅"
            bus_msg = "✅ Run complete"
        elif outcome_lower == "halted":
            status["status"] = "halted"
            status_emoji = "🛑"
            bus_msg = "🛑 Run halted"
        else:
            status["status"] = "blocked"
            status_emoji = "⚠️"
            bus_msg = f"⚠️ Run ended: {outcome}"

        steps_done = status.get("steps_done", 0)
        steps_total = status.get("steps_total", 0)
        steps_skipped = max(0, steps_total - steps_done - len(status.get("blocked_steps", [])))

        summary = {
            "run_id": status.get("run_id", ""),
            "pipeline_id": status.get("pipeline_id", ""),
            "project_id": project_id,
            "outcome": outcome,
            "steps_completed": steps_done,
            "steps_skipped": steps_skipped,
            "steps_total": steps_total,
            "duration_s": duration_s,
            "budget_used_pct": status.get("budget_used_pct", 0),
            "interventions": status.get("interventions", []),
            "producer_notes": status.get("producer_notes", []),
            "completed_at": _now_iso(),
        }

        try:
            self._memory.write(
                project_id,
                "artifact",
                "run_summary_v1",
                json.dumps(summary, indent=2),
                created_by="producer-orchestrator",
            )
        except Exception as exc:
            logger.warning(f"[{project_id}] Failed to write run_summary_v1: {exc}")

        note_text = (
            f"{status_emoji} Run {outcome}. "
            f"{steps_done}/{steps_total} steps completed"
            + (f" in {duration_s}s" if duration_s else "")
            + "."
        )
        self._add_note(status, note_text)
        status["last_event"] = note_text
        self._save_status(project_id, status)

        await self._broadcast_status(project_id, status, note=note_text)

        try:
            await self._bus.post(
                project_id=project_id,
                channel="producer",
                sender="producer-orchestrator",
                content=bus_msg,
            )
        except Exception as exc:
            logger.warning(f"[{project_id}] message_bus.post failed: {exc}")

        # Clean up in-memory state
        self._run_start_times.pop(project_id, None)

    # ------------------------------------------------------------------
    # Status accessors (used by REST endpoints)
    # ------------------------------------------------------------------

    def get_run_status(self, project_id: str) -> dict | None:
        """Return current run_status_v1 for a project."""
        return self._load_status(project_id)

    def get_producer_notes(self, project_id: str) -> list[dict]:
        """Return producer_notes array from run_status_v1."""
        status = self._load_status(project_id)
        if not status:
            return []
        return status.get("producer_notes", [])
