"""Task queue models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field
from datetime import datetime


@dataclass
class WorkerSignal:
    """Structured completion signal agents write via report_completion tool."""
    status: Literal["completed", "blocked", "failed"]
    summary: str
    deliverables: list[str] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    escalation_reason: str | None = None


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
    metadata: dict | None = None               # free-form per-task context (e.g. iteration_tag, cycle_n)
    # Post-run completion contract. Each entry is one of:
    #   {"kind": "memory_key", "type": "artifact", "key": "engineer_result_eng-1_v2"}
    #   {"kind": "branch_commit", "branch": "iteration/eng-1-v2"}
    #   {"kind": "file_path", "path": "game.html", "min_bytes": 1024}
    # Validator blocks the task with failure_category="no_output" if any entry
    # isn't satisfied when the agent returns — catches silent-success runs
    # where the LLM closes out without producing the deliverables.
    expected_outputs: list[dict] | None = None
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
    metadata: dict | None = None               # free-form per-task context (e.g. iteration_tag, cycle_n)
    expected_outputs: list[dict] | None = None # see Task.expected_outputs for shape


class TaskUpdate(BaseModel):
    """Partial update of an existing task — currently just the model override."""
    model_override: str | None = None
