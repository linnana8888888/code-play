"""Tool governance models."""

from enum import Enum
from pydantic import BaseModel
from datetime import datetime


class GovernanceDecision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"
    BLOCKED = "blocked"


class ToolPermission(str, Enum):
    BUILTIN = "builtin"           # always allowed
    PRE_APPROVED = "pre_approved"  # user's existing tools, always allowed
    RESTRICTED = "restricted"      # needs human approval
    BLOCKED = "blocked"            # always denied


class ApprovalRequest(BaseModel):
    id: int | None = None
    agent_instance_id: str
    tool_name: str
    params: dict | None = None
    status: str = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None
