"""Task Queue — SQLite-backed task management with dependency resolution."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.models.tasks import Task, TaskCreate, TaskStatus, TaskUpdate
from src.database import get_studio_db


class TaskQueue:
    def create(self, task_input: TaskCreate) -> Task:
        """Create a new task."""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        metadata_json = (
            json.dumps(task_input.metadata) if task_input.metadata else None
        )

        with get_studio_db() as db:
            db.execute(
                """INSERT INTO tasks (id, project_id, title, description, parent_task_id, criterion_id, assignee_type, priority, depends_on, created_by, model_override, metadata, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    task_id,
                    task_input.project_id,
                    task_input.title,
                    task_input.description,
                    task_input.parent_task_id,
                    task_input.criterion_id,
                    task_input.assignee_type,
                    task_input.priority,
                    json.dumps(task_input.depends_on),
                    task_input.created_by,
                    task_input.model_override,
                    metadata_json,
                    now,
                    now,
                ),
            )

        return Task(
            id=task_id,
            project_id=task_input.project_id,
            title=task_input.title,
            description=task_input.description,
            parent_task_id=task_input.parent_task_id,
            criterion_id=task_input.criterion_id,
            assignee_type=task_input.assignee_type,
            priority=task_input.priority,
            depends_on=task_input.depends_on,
            created_by=task_input.created_by,
            model_override=task_input.model_override,
            metadata=task_input.metadata,
            status=TaskStatus.PENDING,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        with get_studio_db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(
        self,
        project_id: str = None,
        status: TaskStatus = None,
        assigned_to: str = None,
    ) -> list[Task]:
        """List tasks with optional filters."""
        sql = "SELECT * FROM tasks WHERE 1=1"
        params = []

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        if status:
            sql += " AND status = ?"
            params.append(status.value)
        if assigned_to:
            sql += " AND assigned_to = ?"
            params.append(assigned_to)

        sql += " ORDER BY priority DESC, created_at ASC"

        with get_studio_db() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def assign(self, task_id: str, agent_instance_id: str) -> Task | None:
        """Assign a task to an agent instance (backwards-compatible wrapper)."""
        return self.checkout(task_id, agent_instance_id)

    def checkout(self, task_id: str, agent_instance_id: str) -> Task | None:
        """Atomically claim a pending task. Returns None if already taken.

        Uses a single UPDATE with WHERE conditions so only one agent
        can claim the task even under concurrent access.
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_studio_db() as db:
            cursor = db.execute(
                """UPDATE tasks SET assigned_to = ?, status = 'assigned', updated_at = ?
                   WHERE id = ? AND status = 'pending' AND assigned_to IS NULL""",
                (agent_instance_id, now, task_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(task_id)

    def update(self, task_id: str, patch: TaskUpdate) -> Task | None:
        """Partial update of a task (currently just model_override)."""
        fields = patch.model_dump(exclude_unset=True)
        if not fields:
            return self.get(task_id)
        now = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(f"{k}=?" for k in fields.keys())
        values = list(fields.values()) + [now, task_id]
        with get_studio_db() as db:
            cursor = db.execute(
                f"UPDATE tasks SET {cols}, updated_at=? WHERE id=?",
                values,
            )
            if cursor.rowcount == 0:
                return None
        return self.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus, result: dict = None):
        """Update task status and optionally store result."""
        with get_studio_db() as db:
            if result is not None:
                db.execute(
                    "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                    (status.value, json.dumps(result), datetime.now(timezone.utc).isoformat(), task_id),
                )
            else:
                db.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, datetime.now(timezone.utc).isoformat(), task_id),
                )

    def get_ready_tasks(self, project_id: str) -> list[Task]:
        """Get pending tasks whose dependencies are all completed."""
        pending = self.list_tasks(project_id=project_id, status=TaskStatus.PENDING)
        ready = []

        for task in pending:
            if not task.depends_on:
                ready.append(task)
                continue

            # Check all dependencies
            all_done = True
            for dep_id in task.depends_on:
                dep = self.get(dep_id)
                if not dep or dep.status != TaskStatus.COMPLETED:
                    all_done = False
                    break
            if all_done:
                ready.append(task)

        def _sort_key(t):
            ts = t.created_at
            if ts is None:
                return (-t.priority, "")
            # Normalize tz to get consistent ordering across naive/aware timestamps
            iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            return (-t.priority, iso)
        return sorted(ready, key=_sort_key)

    def _row_to_task(self, row) -> Task:
        depends = json.loads(row["depends_on"]) if row["depends_on"] else []
        result = json.loads(row["result"]) if row["result"] else None
        # Columns added via migration may not exist on old rows
        parent_task_id = None
        assignee_type = None
        model_override = None
        criterion_id = None
        try:
            parent_task_id = row["parent_task_id"]
        except (IndexError, KeyError):
            pass
        try:
            assignee_type = row["assignee_type"]
        except (IndexError, KeyError):
            pass
        try:
            model_override = row["model_override"]
        except (IndexError, KeyError):
            pass
        try:
            criterion_id = row["criterion_id"]
        except (IndexError, KeyError):
            pass
        metadata = None
        try:
            raw_metadata = row["metadata"]
            if raw_metadata:
                metadata = json.loads(raw_metadata)
        except (IndexError, KeyError, json.JSONDecodeError):
            pass
        return Task(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"] or "",
            assigned_to=row["assigned_to"],
            assignee_type=assignee_type,
            parent_task_id=parent_task_id,
            criterion_id=criterion_id,
            status=TaskStatus(row["status"]),
            priority=row["priority"] or 0,
            depends_on=depends,
            created_by=row["created_by"] or "human",
            model_override=model_override,
            metadata=metadata,
            result=result,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )


# Singleton
task_queue = TaskQueue()
