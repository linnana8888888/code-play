"""Agent definition and instance models."""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class AgentStatus(str, Enum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentDefinition(BaseModel):
    """Parsed from .md files with YAML frontmatter."""
    id: str                                    # filename without .md
    name: str
    description: str
    category: str = ""                         # directory name
    color: str = ""
    emoji: str = ""
    vibe: str = ""
    default_model: str = ""                    # e.g. "openrouter/qwen/qwen3-coder:free"
    fallback_model: str = ""                   # e.g. "omlx/qwen3.5-9b"
    tools: list[str] = Field(default_factory=list)  # tool names this agent can use
    system_prompt: str = ""                    # the markdown body
    source_path: str = ""                      # path to the .md file


class AgentInstance(BaseModel):
    """A running instance of an agent working on a task."""
    id: str
    agent_type: str                            # references AgentDefinition.id
    project_id: str | None = None
    task_id: str | None = None
    status: AgentStatus = AgentStatus.IDLE
    model: str = ""
    provider: str = ""
    conversation: list[dict] = Field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
