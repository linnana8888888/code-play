"""Agent proposal models — human-gated roster allocation."""
from __future__ import annotations

from enum import Enum
from datetime import datetime

from pydantic import BaseModel, Field


class ProposalPhase(str, Enum):
    KICKOFF = "kickoff"
    IN_FLIGHT = "in_flight"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SPAWNED = "spawned"


class AgentProposal(BaseModel):
    id: str
    project_id: str
    batch_id: str
    agent_type: str
    rationale: str = ""
    proposer: str = "human"
    phase: ProposalPhase = ProposalPhase.IN_FLIGHT
    status: ProposalStatus = ProposalStatus.PENDING
    task_id: str | None = None
    model_override: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    spawned_instance_id: str | None = None
    created_at: datetime | None = None


class AgentProposalCreate(BaseModel):
    project_id: str
    agent_type: str
    rationale: str = ""
    proposer: str = "human"
    phase: ProposalPhase = ProposalPhase.IN_FLIGHT
    batch_id: str | None = None        # caller-supplied id groups kickoff batches
    task_id: str | None = None
    model_override: str | None = None


class BatchDecision(BaseModel):
    decided_by: str = "human"
    keep_proposal_ids: list[str] | None = None  # approve subset; None = approve all
    reason: str = ""


class SingleDecision(BaseModel):
    decided_by: str = "human"
    reason: str = ""
