"""Task queue models."""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    description: str = ""
    assigned_to: str | None = None             # agent instance ID
    assignee_type: str | None = None           # agent-type hint for auto-spawn
    parent_task_id: str | None = None          # enables task hierarchy
    criterion_id: str | None = None            # links this task to a success criterion
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    created_by: str = "human"
    model_override: str | None = None          # picks which LLM runs this task (overrides agent default)
    result: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskCreate(BaseModel):
    project_id: str
    title: str
    description: str = ""
    assignee_type: str | None = None           # agent-type hint (e.g. "frontend-developer")
    parent_task_id: str | None = None
    criterion_id: str | None = None
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    created_by: str = "human"
    model_override: str | None = None          # if set, overrides the agent's default_model when spawned


class TaskUpdate(BaseModel):
    """Partial update of an existing task — currently just the model override."""
    model_override: str | None = None
