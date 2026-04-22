"""Agent proposal CRUD — roster allocation with human approval gate."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.database import get_studio_db
from src.models.proposals import (
    AgentProposal,
    AgentProposalCreate,
    ProposalPhase,
    ProposalStatus,
)


def _row_to_model(row) -> AgentProposal:
    def _dt(val):
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None
    return AgentProposal(
        id=row["id"],
        project_id=row["project_id"],
        batch_id=row["batch_id"],
        agent_type=row["agent_type"],
        rationale=row["rationale"] or "",
        proposer=row["proposer"] or "human",
        phase=ProposalPhase(row["phase"]),
        status=ProposalStatus(row["status"]),
        task_id=row["task_id"],
        model_override=row["model_override"],
        decided_by=row["decided_by"],
        decided_at=_dt(row["decided_at"]),
        spawned_instance_id=row["spawned_instance_id"],
        created_at=_dt(row["created_at"]),
    )


def create(data: AgentProposalCreate) -> AgentProposal:
    pid = f"prop-{uuid.uuid4().hex[:10]}"
    batch_id = data.batch_id or f"batch-{uuid.uuid4().hex[:10]}"
    with get_studio_db() as db:
        db.execute(
            """INSERT INTO agent_proposals
               (id, project_id, batch_id, agent_type, rationale, proposer, phase, status, task_id, model_override)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                pid, data.project_id, batch_id, data.agent_type, data.rationale,
                data.proposer, data.phase.value, data.task_id, data.model_override,
            ),
        )
        row = db.execute("SELECT * FROM agent_proposals WHERE id = ?", (pid,)).fetchone()
    return _row_to_model(row)


def get(proposal_id: str) -> AgentProposal | None:
    with get_studio_db() as db:
        row = db.execute("SELECT * FROM agent_proposals WHERE id = ?", (proposal_id,)).fetchone()
    return _row_to_model(row) if row else None


def list_proposals(
    project_id: str | None = None,
    batch_id: str | None = None,
    status: ProposalStatus | None = None,
) -> list[AgentProposal]:
    sql = "SELECT * FROM agent_proposals WHERE 1=1"
    params: list = []
    if project_id:
        sql += " AND project_id = ?"; params.append(project_id)
    if batch_id:
        sql += " AND batch_id = ?"; params.append(batch_id)
    if status:
        sql += " AND status = ?"; params.append(status.value)
    sql += " ORDER BY created_at DESC"
    with get_studio_db() as db:
        rows = db.execute(sql, params).fetchall()
    return [_row_to_model(r) for r in rows]


def list_batch(batch_id: str) -> list[AgentProposal]:
    return list_proposals(batch_id=batch_id)


def _set_status(proposal_id: str, status: ProposalStatus, decided_by: str) -> AgentProposal | None:
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        cur = db.execute(
            """UPDATE agent_proposals
               SET status = ?, decided_by = ?, decided_at = ?
               WHERE id = ? AND status = 'pending'""",
            (status.value, decided_by, now, proposal_id),
        )
        if cur.rowcount == 0:
            return None
    return get(proposal_id)


def approve(proposal_id: str, decided_by: str = "human") -> AgentProposal | None:
    return _set_status(proposal_id, ProposalStatus.APPROVED, decided_by)


def reject(proposal_id: str, decided_by: str = "human") -> AgentProposal | None:
    return _set_status(proposal_id, ProposalStatus.REJECTED, decided_by)


def approve_batch(
    batch_id: str,
    decided_by: str = "human",
    keep_proposal_ids: list[str] | None = None,
) -> list[AgentProposal]:
    """Approve all pending proposals in the batch (or subset if keep_proposal_ids given)."""
    proposals = list_batch(batch_id)
    approved: list[AgentProposal] = []
    keep_set = set(keep_proposal_ids) if keep_proposal_ids is not None else None
    for p in proposals:
        if p.status != ProposalStatus.PENDING:
            continue
        if keep_set is not None and p.id not in keep_set:
            updated = reject(p.id, decided_by)
            continue
        updated = approve(p.id, decided_by)
        if updated:
            approved.append(updated)
    return approved


def reject_batch(batch_id: str, decided_by: str = "human") -> list[AgentProposal]:
    rejected: list[AgentProposal] = []
    for p in list_batch(batch_id):
        if p.status != ProposalStatus.PENDING:
            continue
        updated = reject(p.id, decided_by)
        if updated:
            rejected.append(updated)
    return rejected


def get_approved_for_task(task_id: str) -> AgentProposal | None:
    """Return the approved (not yet spawned) proposal for a task, if any."""
    with get_studio_db() as db:
        row = db.execute(
            "SELECT * FROM agent_proposals WHERE task_id = ? AND status = 'approved' LIMIT 1",
            (task_id,),
        ).fetchone()
    return _row_to_model(row) if row else None


def mark_spawned(proposal_id: str, instance_id: str) -> AgentProposal | None:
    with get_studio_db() as db:
        cur = db.execute(
            """UPDATE agent_proposals
               SET status = 'spawned', spawned_instance_id = ?
               WHERE id = ? AND status = 'approved'""",
            (instance_id, proposal_id),
        )
        if cur.rowcount == 0:
            return None
    return get(proposal_id)
