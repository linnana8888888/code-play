"""Success criteria models — measurable outcomes per project."""
from __future__ import annotations

from enum import Enum
from datetime import datetime

from pydantic import BaseModel


class CriterionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    MET = "met"
    FAILED = "failed"


class SuccessCriterion(BaseModel):
    id: str
    project_id: str
    title: str
    description: str = ""
    acceptance_test: str = ""
    status: CriterionStatus = CriterionStatus.PENDING
    order_index: int = 0
    created_by: str = "human"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CriterionCreate(BaseModel):
    title: str
    description: str = ""
    acceptance_test: str = ""
    order_index: int = 0


class CriterionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    acceptance_test: str | None = None
    status: CriterionStatus | None = None
    order_index: int | None = None
