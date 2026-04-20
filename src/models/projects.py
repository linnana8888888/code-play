"""Project models."""
from __future__ import annotations

from pydantic import BaseModel
from datetime import datetime


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    goal: str = ""
    tech_stack: str = ""
    status: str = "active"
    repo_url: str | None = None
    repo_name: str | None = None
    require_roster_approval: bool = False
    auto_iterate: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    goal: str = ""
    tech_stack: str = "threejs"
    create_repo: bool = False
    require_roster_approval: bool = True  # new projects default ON; back-compat handled at migration level
    pipeline: str = "phased-producer"
    auto_iterate: bool = False
    game_slug: str | None = None
    repo_url: str | None = None
