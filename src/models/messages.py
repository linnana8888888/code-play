"""Communication models."""
from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime


class Message(BaseModel):
    id: int | None = None
    project_id: str
    channel: str = "general"
    sender: str
    content: str
    mentions: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class EscalationRequest(BaseModel):
    project_id: str
    agent_instance_id: str
    question: str
    options: list[str] = Field(default_factory=list)
    context: str = ""
    blocking: bool = True
