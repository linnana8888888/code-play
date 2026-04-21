"""Project Memory — per-project SQLite knowledge store.

Each game project gets its own memory database for:
- Decisions: architecture choices, design decisions with rationale
- Artifacts: references to generated files, assets, code modules
- Feedback: human and agent feedback on outputs
- Context: runtime context, conversation summaries, shared state
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.database import get_project_db, get_studio_db, init_project_db

logger = logging.getLogger(__name__)


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


    def compile_briefing(self, project_id: str) -> str:
        """Compile a rich BRIEFING.md from all available project state.

        Designed to replace 200k+ tokens of agent file-discovery with a
        single ~3-8k token document injected at spawn time.
        """
        from src.runtime.workspace import list_project_files

        sections: list[str] = []

        # ── 1. Project summary from studio DB ──
        with get_studio_db() as db:
            row = db.execute(
                "SELECT name, description, goal, tech_stack FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row:
            sections.append(
                f"# Project: {row['name']}\n\n"
                f"{row['description'] or ''}\n\n"
                f"- **Tech stack**: {row['tech_stack'] or 'not specified'}\n"
                f"- **Goal**: {row['goal'] or 'not specified'}"
            )

        # ── 2. Iteration state ──
        cycle_n = self.read(project_id, "cycle", "n")
        if cycle_n:
            sections.append(f"## Iteration cycle: {cycle_n}")

        # ── 3. GOALS.md (full, not truncated) ──
        goals = self.read(project_id, "artifact", "goals_md")
        if goals:
            sections.append(f"## Goals\n\n{goals.strip()}")

        # ── 4. Artifact repo file tree ──
        repo_path_raw = self.read(project_id, "artifact", "artifact_repo_path")
        if repo_path_raw:
            repo_path = Path(repo_path_raw.strip()).expanduser()
            if repo_path.is_dir():
                tree = list_project_files(repo_path)
                sections.append(f"## File tree ({repo_path.name}/)\n\n```\n{tree}\n```")

        # ── 5. Last postmortem ──
        postmortem = self.read(project_id, "artifact", "postmortem_v1")
        if postmortem:
            trimmed = postmortem.strip()[:3000]
            sections.append(f"## Last postmortem\n\n{trimmed}")

        # ── 6. Active proposals (if any) ──
        proposal_keys = [
            "proposal_designer_v1", "proposal_ux_v1",
            "proposal_proto_v1", "proposal_artist_v1",
        ]
        proposals = []
        for key in proposal_keys:
            content = self.read(project_id, "artifact", key)
            if content:
                label = key.replace("proposal_", "").replace("_v1", "")
                proposals.append(f"### {label}\n{content.strip()[:800]}")
        if proposals:
            sections.append("## Active proposals\n\n" + "\n\n".join(proposals))

        # ── 7. Decisions (full content) ──
        decisions = self.list_by_type(project_id, "decision")
        if decisions:
            lines = ["## Key decisions"]
            for d in decisions:
                lines.append(f"- **{d['key']}**: {d['content']}")
            sections.append("\n".join(lines))

        # ── 8. Latest telemetry summary ──
        for v in range(10, 0, -1):
            telem = self.read(project_id, "artifact", f"telemetry_v{v}")
            if telem:
                sections.append(f"## Latest telemetry (v{v})\n\n{telem.strip()[:2000]}")
                break

        if not sections:
            return f"# Project {project_id}\n\nNo briefing data available yet."

        briefing = "\n\n---\n\n".join(sections)
        logger.info("Compiled briefing for %s: %d chars", project_id, len(briefing))
        return briefing


# Singleton
project_memory = ProjectMemory()
