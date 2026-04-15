"""Project Memory — per-project SQLite knowledge store.

Each game project gets its own memory database for:
- Decisions: architecture choices, design decisions with rationale
- Artifacts: references to generated files, assets, code modules
- Feedback: human and agent feedback on outputs
- Context: runtime context, conversation summaries, shared state
"""

import json
from datetime import datetime, timezone

from src.database import get_project_db, init_project_db


class ProjectMemory:
    """Read/write/search interface for per-project memory."""

    def ensure_db(self, project_id: str):
        """Ensure the project memory database exists."""
        init_project_db(project_id)

    def write(
        self,
        project_id: str,
        mem_type: str,
        key: str,
        content: str,
        created_by: str = "system",
    ) -> int:
        """Write or update a memory entry. Returns the row ID."""
        self.ensure_db(project_id)

        with get_project_db(project_id) as db:
            existing = db.execute(
                "SELECT id FROM memory WHERE type = ? AND key = ?",
                (mem_type, key),
            ).fetchone()

            if existing:
                db.execute(
                    """UPDATE memory SET content = ?, created_by = ?, updated_at = datetime('now')
                       WHERE type = ? AND key = ?""",
                    (content, created_by, mem_type, key),
                )
                return existing["id"]
            else:
                cursor = db.execute(
                    "INSERT INTO memory (type, key, content, created_by) VALUES (?, ?, ?, ?)",
                    (mem_type, key, content, created_by),
                )
                return cursor.lastrowid

    def read(self, project_id: str, mem_type: str, key: str) -> str | None:
        """Read a specific memory entry."""
        self.ensure_db(project_id)

        with get_project_db(project_id) as db:
            row = db.execute(
                "SELECT content FROM memory WHERE type = ? AND key = ?",
                (mem_type, key),
            ).fetchone()
        return row["content"] if row else None

    def search(
        self,
        project_id: str,
        query: str,
        mem_type: str = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search memory by keyword match on content."""
        self.ensure_db(project_id)

        sql = "SELECT type, key, content, created_by, updated_at FROM memory WHERE content LIKE ?"
        params = [f"%{query}%"]

        if mem_type:
            sql += " AND type = ?"
            params.append(mem_type)

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with get_project_db(project_id) as db:
            rows = db.execute(sql, params).fetchall()

        return [dict(r) for r in rows]

    def list_by_type(self, project_id: str, mem_type: str) -> list[dict]:
        """List all memory entries of a given type."""
        self.ensure_db(project_id)

        with get_project_db(project_id) as db:
            rows = db.execute(
                "SELECT type, key, content, created_by, updated_at FROM memory WHERE type = ? ORDER BY updated_at DESC",
                (mem_type,),
            ).fetchall()

        return [dict(r) for r in rows]

    def delete(self, project_id: str, mem_type: str, key: str) -> bool:
        """Delete a memory entry."""
        self.ensure_db(project_id)

        with get_project_db(project_id) as db:
            cursor = db.execute(
                "DELETE FROM memory WHERE type = ? AND key = ?",
                (mem_type, key),
            )
        return cursor.rowcount > 0

    def get_context_bundle(self, project_id: str) -> str:
        """Build a context summary to inject into agent prompts.

        Returns a formatted string with key decisions, active artifacts,
        and recent feedback — ready to append to system prompt.
        """
        self.ensure_db(project_id)

        sections = []

        # Key decisions
        decisions = self.list_by_type(project_id, "decision")
        if decisions:
            lines = ["## Project Decisions"]
            for d in decisions[:10]:
                lines.append(f"- **{d['key']}**: {d['content'][:200]}")
            sections.append("\n".join(lines))

        # Active artifacts
        artifacts = self.list_by_type(project_id, "artifact")
        if artifacts:
            lines = ["## Project Artifacts"]
            for a in artifacts[:15]:
                lines.append(f"- {a['key']}: {a['content'][:150]}")
            sections.append("\n".join(lines))

        # Recent feedback
        feedback = self.list_by_type(project_id, "feedback")
        if feedback:
            lines = ["## Recent Feedback"]
            for f in feedback[:5]:
                lines.append(f"- [{f['created_by']}] {f['content'][:200]}")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        return "\n\n".join(sections)


# Singleton
project_memory = ProjectMemory()
