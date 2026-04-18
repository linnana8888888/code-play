"""Success criteria CRUD against the studio DB."""
from __future__ import annotations

import uuid

from src.database import get_studio_db
from src.models.criteria import (
    CriterionCreate,
    CriterionStatus,
    CriterionUpdate,
    SuccessCriterion,
)


def _row_to_model(row) -> SuccessCriterion:
    return SuccessCriterion(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        description=row["description"] or "",
        acceptance_test=row["acceptance_test"] or "",
        status=CriterionStatus(row["status"]),
        order_index=row["order_index"] or 0,
        created_by=row["created_by"] or "human",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create(project_id: str, data: CriterionCreate, created_by: str = "human") -> SuccessCriterion:
    cid = f"crit-{uuid.uuid4().hex[:10]}"
    with get_studio_db() as db:
        db.execute(
            """INSERT INTO success_criteria
               (id, project_id, title, description, acceptance_test, order_index, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, project_id, data.title, data.description, data.acceptance_test,
             data.order_index, created_by),
        )
        row = db.execute("SELECT * FROM success_criteria WHERE id = ?", (cid,)).fetchone()
    return _row_to_model(row)


def list_for_project(project_id: str) -> list[SuccessCriterion]:
    with get_studio_db() as db:
        rows = db.execute(
            "SELECT * FROM success_criteria WHERE project_id = ? ORDER BY order_index, created_at",
            (project_id,),
        ).fetchall()
    return [_row_to_model(r) for r in rows]


def get(criterion_id: str) -> SuccessCriterion | None:
    with get_studio_db() as db:
        row = db.execute("SELECT * FROM success_criteria WHERE id = ?", (criterion_id,)).fetchone()
    return _row_to_model(row) if row else None


def update(criterion_id: str, data: CriterionUpdate) -> SuccessCriterion | None:
    fields = []
    params: list = []
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        fields.append(f"{key} = ?")
        params.append(value.value if hasattr(value, "value") else value)
    if not fields:
        return get(criterion_id)
    fields.append("updated_at = datetime('now')")
    params.append(criterion_id)
    with get_studio_db() as db:
        db.execute(
            f"UPDATE success_criteria SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        row = db.execute("SELECT * FROM success_criteria WHERE id = ?", (criterion_id,)).fetchone()
    return _row_to_model(row) if row else None


def delete(criterion_id: str) -> bool:
    with get_studio_db() as db:
        cur = db.execute("DELETE FROM success_criteria WHERE id = ?", (criterion_id,))
    return cur.rowcount > 0


def link_task(task_id: str, criterion_id: str | None) -> bool:
    with get_studio_db() as db:
        cur = db.execute(
            "UPDATE tasks SET criterion_id = ?, updated_at = datetime('now') WHERE id = ?",
            (criterion_id, task_id),
        )
    return cur.rowcount > 0
