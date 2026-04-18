"""Project documents with append-only revisions.

Content lives in the workspace at `docs/{category}/{slug}.md`; DB stores
revision metadata. Every write creates a new row in document_revisions —
never UPDATE. The documents row tracks the current_version pointer.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

from src.database import get_studio_db
from src.settings import settings


VALID_CATEGORIES = {"design", "architecture", "testing", "analytics", "notes"}


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return s or "doc"


def _doc_id() -> str:
    return f"doc-{uuid.uuid4().hex[:10]}"


def _project_dir(project_id: str) -> Path:
    return Path(settings.projects_dir) / project_id


def _is_git_repo(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path),
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _write_file(project_id: str, category: str, slug: str, content: str,
                change_summary: str, version: int) -> Path | None:
    """Mirror content to docs/{category}/{slug}.md inside the project dir.

    Returns the file path written (None if project dir missing).
    """
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        return None
    docs_dir = project_dir / "docs" / category
    docs_dir.mkdir(parents=True, exist_ok=True)
    file_path = docs_dir / f"{slug}.md"
    file_path.write_text(content, encoding="utf-8")

    # Optional auto-commit when project is a git repo (non-fatal on failure)
    if _is_git_repo(project_dir):
        try:
            subprocess.run(
                ["git", "add", str(file_path.relative_to(project_dir))],
                cwd=str(project_dir), capture_output=True, timeout=10,
            )
            msg = f"docs({category}): v{version} — {change_summary or slug}"
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(project_dir), capture_output=True, timeout=10,
            )
        except Exception:
            pass
    return file_path


def write(
    project_id: str,
    category: str,
    slug: str,
    title: str,
    content: str,
    change_summary: str = "",
    created_by: str = "agent",
) -> tuple[str, int]:
    """Create-or-append a document revision. Returns (document_id, version)."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of {VALID_CATEGORIES}")
    slug = _slugify(slug)

    with get_studio_db() as db:
        row = db.execute(
            "SELECT id, current_version FROM documents WHERE project_id = ? AND category = ? AND slug = ?",
            (project_id, category, slug),
        ).fetchone()

        if row:
            doc_id = row["id"]
            version = (row["current_version"] or 0) + 1
            db.execute(
                "UPDATE documents SET current_version = ?, title = ?, updated_at = datetime('now') WHERE id = ?",
                (version, title, doc_id),
            )
        else:
            doc_id = _doc_id()
            version = 1
            db.execute(
                """INSERT INTO documents (id, project_id, category, slug, title, current_version, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, project_id, category, slug, title, version, created_by),
            )

        db.execute(
            """INSERT INTO document_revisions (document_id, version, content, change_summary, created_by)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, version, content, change_summary, created_by),
        )

    _write_file(project_id, category, slug, content, change_summary, version)
    return doc_id, version


def get_document(doc_id: str) -> dict | None:
    with get_studio_db() as db:
        row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def read(project_id: str, category: str, slug: str, version: int | None = None) -> dict | None:
    """Read a document at latest or a specific version. Returns dict with metadata + content."""
    slug = _slugify(slug)
    with get_studio_db() as db:
        doc = db.execute(
            "SELECT * FROM documents WHERE project_id = ? AND category = ? AND slug = ?",
            (project_id, category, slug),
        ).fetchone()
        if not doc:
            return None
        target_version = version if version is not None else doc["current_version"]
        rev = db.execute(
            "SELECT * FROM document_revisions WHERE document_id = ? AND version = ?",
            (doc["id"], target_version),
        ).fetchone()
    if not rev:
        return None
    return {
        **dict(doc),
        "version": rev["version"],
        "content": rev["content"],
        "change_summary": rev["change_summary"] or "",
        "revision_created_at": rev["created_at"],
    }


def read_by_id(doc_id: str, version: int | None = None) -> dict | None:
    with get_studio_db() as db:
        doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            return None
        target = version if version is not None else doc["current_version"]
        rev = db.execute(
            "SELECT * FROM document_revisions WHERE document_id = ? AND version = ?",
            (doc_id, target),
        ).fetchone()
    if not rev:
        return None
    return {
        **dict(doc),
        "version": rev["version"],
        "content": rev["content"],
        "change_summary": rev["change_summary"] or "",
        "revision_created_at": rev["created_at"],
    }


def list_docs(project_id: str, category: str | None = None) -> list[dict]:
    sql = "SELECT * FROM documents WHERE project_id = ?"
    params: list = [project_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY category, updated_at DESC"
    with get_studio_db() as db:
        rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def history(doc_id: str) -> list[dict]:
    with get_studio_db() as db:
        rows = db.execute(
            "SELECT version, change_summary, created_by, created_at FROM document_revisions WHERE document_id = ? ORDER BY version DESC",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_meta(doc_id: str, title: str | None = None, status: str | None = None) -> dict | None:
    fields: list[str] = []
    params: list = []
    if title is not None:
        fields.append("title = ?"); params.append(title)
    if status is not None:
        fields.append("status = ?"); params.append(status)
    if not fields:
        return get_document(doc_id)
    fields.append("updated_at = datetime('now')")
    params.append(doc_id)
    with get_studio_db() as db:
        db.execute(f"UPDATE documents SET {', '.join(fields)} WHERE id = ?", tuple(params))
    return get_document(doc_id)
