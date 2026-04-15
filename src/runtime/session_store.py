"""Session Store — persist and resume agent conversations."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.database import get_studio_db


class SessionStore:
    """Save and load agent conversation state to/from SQLite."""

    def ensure_table(self):
        """Create the agent_sessions table if it doesn't exist."""
        with get_studio_db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    conversation TEXT NOT NULL DEFAULT '[]',
                    tokens_used INTEGER DEFAULT 0,
                    iteration INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

    def save(
        self,
        instance_id: str,
        conversation: list[dict],
        tokens_used: int = 0,
        iteration: int = 0,
        session_id: str = None,
    ) -> str:
        """Save or update a session. Returns session_id."""
        now = datetime.now(timezone.utc).isoformat()
        conv_json = json.dumps(conversation)

        if session_id:
            with get_studio_db() as db:
                db.execute(
                    """UPDATE agent_sessions SET conversation = ?, tokens_used = ?,
                       iteration = ?, updated_at = ? WHERE id = ?""",
                    (conv_json, tokens_used, iteration, now, session_id),
                )
            return session_id

        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        with get_studio_db() as db:
            db.execute(
                """INSERT INTO agent_sessions (id, instance_id, conversation, tokens_used, iteration, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, instance_id, conv_json, tokens_used, iteration, now, now),
            )
        return session_id

    def load(self, session_id: str) -> dict | None:
        """Load a saved session. Returns dict with conversation, tokens_used, iteration."""
        with get_studio_db() as db:
            row = db.execute(
                "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "instance_id": row["instance_id"],
            "conversation": json.loads(row["conversation"]),
            "tokens_used": row["tokens_used"],
            "iteration": row["iteration"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_sessions(self, instance_id: str = None) -> list[dict]:
        """List sessions, optionally filtered by instance."""
        sql = "SELECT id, instance_id, tokens_used, iteration, created_at, updated_at FROM agent_sessions"
        params = []
        if instance_id:
            sql += " WHERE instance_id = ?"
            params.append(instance_id)
        sql += " ORDER BY updated_at DESC"

        with get_studio_db() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def delete(self, session_id: str):
        """Delete a session."""
        with get_studio_db() as db:
            db.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))


# Singleton
session_store = SessionStore()
