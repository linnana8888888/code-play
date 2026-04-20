"""SQLite database management for tasks, messages, and project memory."""

import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

from src.settings import settings


def _db_dir() -> Path:
    """Project root directory — read from settings each call so tests that
    monkeypatch `settings.projects_dir` land in the same folder the rest of
    the app uses (this was the source of orphan `projects/proj-xxx/` dirs:
    tests pointed the cleanup path at a tmpdir while memory.db kept being
    written to the hardcoded `projects/`)."""
    return Path(settings.projects_dir)


def _get_studio_db_path() -> Path:
    d = _db_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "studio.db"


def _get_project_db_path(project_id: str) -> Path:
    project_dir = _db_dir() / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / "memory.db"


class ProjectNotFoundError(Exception):
    """Raised when a caller asks for a project_id that has no studio row."""


def _project_exists(project_id: str) -> bool:
    """Cheap existence check against the studio DB."""
    db_path = _db_dir() / "studio.db"
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT 1 FROM projects WHERE id = ? LIMIT 1", (project_id,)
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


@contextmanager
def get_studio_db():
    """Connection to the studio-wide database (tasks, agents, governance)."""
    db_path = _get_studio_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_project_db(project_id: str, *, require_exists: bool = True):
    """Connection to a project-specific database (memory, artifacts).

    Defaults to refusing unknown project_ids — that's what was generating
    orphan `projects/proj-xxx/` folders when agents or tools fat-fingered
    an id. Call with `require_exists=False` only during the very first
    project-creation transaction (studio row inserted but folder not yet
    materialized)."""
    if require_exists and not _project_exists(project_id):
        raise ProjectNotFoundError(
            f"Project {project_id!r} has no studio row — refusing to create its folder"
        )
    db_path = _get_project_db_path(project_id)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_studio_db():
    """Create studio-wide tables."""
    with get_studio_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                goal TEXT DEFAULT '',
                tech_stack TEXT,
                status TEXT DEFAULT 'active',
                repo_url TEXT,
                repo_name TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                assigned_to TEXT,
                parent_task_id TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                depends_on TEXT DEFAULT '[]',
                created_by TEXT DEFAULT 'human',
                result TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (parent_task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS agent_instances (
                id TEXT PRIMARY KEY,
                agent_type TEXT NOT NULL,
                project_id TEXT,
                task_id TEXT,
                status TEXT DEFAULT 'idle',
                model TEXT,
                provider TEXT,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'general',
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                mentions TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS governance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_instance_id TEXT,
                tool_name TEXT NOT NULL,
                params TEXT,
                decision TEXT NOT NULL,
                reason TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS approval_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_instance_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                params TEXT,
                status TEXT DEFAULT 'pending',
                decided_by TEXT,
                decided_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS cost_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_instance_id TEXT,
                project_id TEXT,
                provider TEXT,
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS success_criteria (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                acceptance_test TEXT,
                status TEXT DEFAULT 'pending',
                order_index INTEGER DEFAULT 0,
                created_by TEXT DEFAULT 'human',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE INDEX IF NOT EXISTS idx_criteria_project ON success_criteria(project_id);

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                category TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                current_version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'draft',
                created_by TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(project_id, category, slug),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);

            CREATE TABLE IF NOT EXISTS document_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                change_summary TEXT,
                created_by TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (document_id) REFERENCES documents(id)
            );
            CREATE INDEX IF NOT EXISTS idx_revisions_doc ON document_revisions(document_id);

            CREATE TABLE IF NOT EXISTS agent_proposals (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                rationale TEXT,
                proposer TEXT,
                phase TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                task_id TEXT,
                model_override TEXT,
                decided_by TEXT,
                decided_at TEXT,
                spawned_instance_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE INDEX IF NOT EXISTS idx_proposals_batch ON agent_proposals(batch_id);
            CREATE INDEX IF NOT EXISTS idx_proposals_status ON agent_proposals(status);
        """)

        # Migrations for existing databases
        _migrate_add_column(db, "projects", "goal", "TEXT DEFAULT ''")
        _migrate_add_column(db, "projects", "require_roster_approval", "INTEGER DEFAULT 0")
        _migrate_add_column(db, "tasks", "parent_task_id", "TEXT")
        _migrate_add_column(db, "tasks", "assignee_type", "TEXT")
        _migrate_add_column(db, "tasks", "model_override", "TEXT")
        _migrate_add_column(db, "tasks", "criterion_id", "TEXT")
        # iterate_artifact pipeline support
        _migrate_add_column(db, "projects", "iterate_enabled", "INTEGER DEFAULT 0")
        _migrate_add_column(db, "projects", "auto_synthesis", "INTEGER DEFAULT 0")
        _migrate_add_column(db, "tasks", "metadata", "TEXT")
        _migrate_add_column(db, "projects", "auto_iterate", "INTEGER DEFAULT 1")


def _migrate_add_column(db, table: str, column: str, col_type: str):
    """Add a column if it doesn't exist (idempotent migration)."""
    try:
        cols = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass


def init_project_db(project_id: str):
    """Create project-specific memory tables."""
    with get_project_db(project_id) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(type);
            CREATE INDEX IF NOT EXISTS idx_memory_key ON memory(key);
        """)
