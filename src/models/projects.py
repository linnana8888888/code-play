"""Project models."""

from pydantic import BaseModel
from datetime import datetime


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    tech_stack: str = ""
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    tech_stack: str = "threejs"
