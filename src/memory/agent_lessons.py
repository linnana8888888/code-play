"""Agent Lessons — per-agent-type behavioral memory.

Stores lessons learned from task failures and human feedback so agents
don't repeat the same mistakes across runs. Lessons are injected into
agent prompts at spawn time via _run_agent_task in main.py.

Storage: reuses the existing per-project `memory` table with
type='agent_lesson', key='{agent_type}::L{NNN}'.

Cross-game lessons (CrossGameLessonStore) are stored in the studio-wide
SQLite DB (studio.db) in the cross_game_lessons table.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from src.memory.project_memory import project_memory
from src.database import get_studio_db

logger = logging.getLogger(__name__)

MAX_LESSONS_PER_AGENT = 15
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class AgentLessons:

    def _next_lesson_id(self, project_id: str, agent_type: str) -> str:
        prefix = f"{agent_type}::"
        existing = [
            e["key"] for e in project_memory.list_by_type(project_id, "agent_lesson")
            if e["key"].startswith(prefix)
        ]
        nums = []
        for k in existing:
            m = re.search(r"::L(\d+)$", k)
            if m:
                nums.append(int(m.group(1)))
        next_n = max(nums, default=0) + 1
        return f"{agent_type}::L{next_n:03d}"

    def _get_raw(self, project_id: str, agent_type: str) -> list[dict]:
        prefix = f"{agent_type}::"
        entries = project_memory.list_by_type(project_id, "agent_lesson")
        results = []
        for e in entries:
            if not e["key"].startswith(prefix):
                continue
            try:
                data = json.loads(e["content"])
                data["_key"] = e["key"]
                results.append(data)
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    def _is_duplicate(self, existing: list[dict], new_lesson: str) -> bool:
        normalised = new_lesson.lower().strip()
        for e in existing:
            if normalised in e.get("lesson", "").lower() or e.get("lesson", "").lower() in normalised:
                return True
        return False

    def _enforce_cap(self, project_id: str, agent_type: str):
        lessons = self._get_raw(project_id, agent_type)
        if len(lessons) <= MAX_LESSONS_PER_AGENT:
            return
        lessons.sort(key=lambda x: (
            SEVERITY_ORDER.get(x.get("severity", "info"), 2),
            x.get("created_at", ""),
        ))
        to_evict = lessons[MAX_LESSONS_PER_AGENT:]
        for entry in to_evict:
            project_memory.delete(project_id, "agent_lesson", entry["_key"])
            logger.info("Evicted lesson %s for %s", entry["_key"], agent_type)

    def extract_from_failure(
        self,
        project_id: str,
        agent_type: str,
        failure_category: str,
        missing: list[str],
        task_description: str = "",
    ) -> str | None:
        existing = self._get_raw(project_id, agent_type)

        if failure_category == "no_output" and missing:
            keys_mentioned = ", ".join(missing[:3])
            lesson_text = (
                f"Always verify you have saved all required outputs before finishing. "
                f"Missing in last run: {keys_mentioned}. "
                f"Call memory_write for each expected output — the pipeline blocks if any are missing."
            )
            severity = "critical"
            context = f"Failure: {failure_category}. Missing: {keys_mentioned}."
        elif failure_category == "budget_exhausted":
            lesson_text = (
                "Keep tool calls focused and avoid redundant file reads. "
                "A previous run exhausted its token budget before producing deliverables."
            )
            severity = "warning"
            context = f"Failure: budget_exhausted on task: {task_description[:200]}"
        else:
            return None

        if self._is_duplicate(existing, lesson_text):
            logger.debug("Skipping duplicate lesson for %s: %s", agent_type, lesson_text[:80])
            return None

        key = self._next_lesson_id(project_id, agent_type)
        payload = json.dumps({
            "agent_type": agent_type,
            "source": "auto",
            "lesson": lesson_text,
            "context": context,
            "severity": severity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        project_memory.write(project_id, "agent_lesson", key, payload, created_by="validator")
        self._enforce_cap(project_id, agent_type)
        logger.info("Extracted lesson %s for %s: %s", key, agent_type, lesson_text[:80])
        return key

    def add_human_lesson(
        self,
        project_id: str,
        agent_type: str,
        lesson: str,
        severity: str = "warning",
    ) -> str:
        existing = self._get_raw(project_id, agent_type)
        if self._is_duplicate(existing, lesson):
            raise ValueError(f"Duplicate lesson for {agent_type}: {lesson[:80]}")

        key = self._next_lesson_id(project_id, agent_type)
        payload = json.dumps({
            "agent_type": agent_type,
            "source": "human",
            "lesson": lesson,
            "context": "Added by human via API",
            "severity": severity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        project_memory.write(project_id, "agent_lesson", key, payload, created_by="human")
        self._enforce_cap(project_id, agent_type)
        logger.info("Human lesson %s for %s: %s", key, agent_type, lesson[:80])
        return key

    def delete_lesson(self, project_id: str, lesson_key: str) -> bool:
        return project_memory.delete(project_id, "agent_lesson", lesson_key)

    def get_lessons(self, project_id: str, agent_type: str, limit: int = 15) -> list[dict]:
        lessons = self._get_raw(project_id, agent_type)
        lessons.sort(key=lambda x: (
            SEVERITY_ORDER.get(x.get("severity", "info"), 2),
            x.get("created_at", ""),
        ))
        return lessons[:limit]

    def format_for_prompt(self, project_id: str, agent_type: str, max_chars: int = 4000) -> str:
        lessons = self.get_lessons(project_id, agent_type)
        if not lessons:
            return ""

        by_severity: dict[str, list[str]] = {"critical": [], "warning": [], "info": []}
        total_chars = 0
        for entry in lessons:
            sev = entry.get("severity", "info")
            src = entry.get("source", "auto")
            date = entry.get("created_at", "")[:10]
            line = f"- {entry['lesson']} (source: {src}, {date})"
            if total_chars + len(line) > max_chars:
                break
            by_severity.setdefault(sev, []).append(line)
            total_chars += len(line)

        sections = []
        sections.append("## Lessons from past runs (you MUST follow these)\n")
        for sev in ("critical", "warning", "info"):
            lines = by_severity.get(sev, [])
            if lines:
                sections.append(f"### {sev.upper()}")
                sections.extend(lines)
                sections.append("")

        return "\n".join(sections).strip()


agent_lessons = AgentLessons()


class CrossGameLessonStore:
    """
    Studio-wide lesson store keyed by (agent_role, lesson_category).
    Lessons learned on any game are available to all future runs.

    Schema:
    - agent_role: str (e.g. "frontend-developer", "game-designer")
    - category: str (e.g. "three_js", "tool_use", "kid_safety", "roblox")
    - lesson: str (concise, actionable, present tense)
    - source_project_id: str
    - source_cycle: str (optional)
    - confidence: float 0.0-1.0 (increases when lesson confirmed across multiple projects)
    - created_at: ISO timestamp
    - last_confirmed_at: ISO timestamp
    - confirmation_count: int
    """

    # Confidence increment per confirmation, capped at 1.0
    _CONFIDENCE_STEP = 0.1

    def add_lesson(
        self,
        agent_role: str,
        category: str,
        lesson: str,
        source_project_id: str,
        source_cycle: str = None,
    ) -> int:
        """Add a new lesson or increment confirmation_count if identical text exists.

        Returns the lesson id (new or existing).
        """
        now = datetime.now(timezone.utc).isoformat()
        normalised = lesson.lower().strip()
        with get_studio_db() as db:
            # Check for exact-text duplicate (case-insensitive)
            row = db.execute(
                "SELECT id, confidence, confirmation_count FROM cross_game_lessons "
                "WHERE agent_role = ? AND lower(trim(lesson)) = ?",
                (agent_role, normalised),
            ).fetchone()
            if row:
                new_count = row["confirmation_count"] + 1
                new_conf = min(1.0, row["confidence"] + self._CONFIDENCE_STEP)
                db.execute(
                    "UPDATE cross_game_lessons "
                    "SET confirmation_count = ?, confidence = ?, last_confirmed_at = ? "
                    "WHERE id = ?",
                    (new_count, new_conf, now, row["id"]),
                )
                logger.debug(
                    "CrossGameLessonStore: duplicate lesson %s — incremented count to %d",
                    row["id"],
                    new_count,
                )
                return row["id"]

            cursor = db.execute(
                "INSERT INTO cross_game_lessons "
                "(agent_role, category, lesson, source_project_id, source_cycle, "
                " confidence, created_at, last_confirmed_at, confirmation_count) "
                "VALUES (?, ?, ?, ?, ?, 0.5, ?, NULL, 1)",
                (agent_role, category, lesson, source_project_id, source_cycle, now),
            )
            lesson_id = cursor.lastrowid
            logger.info(
                "CrossGameLessonStore: new lesson %d for role=%s category=%s",
                lesson_id,
                agent_role,
                category,
            )
            return lesson_id

    def get_lessons(self, agent_role: str, limit: int = 3) -> list[dict]:
        """Get top N lessons for an agent role, sorted by confidence desc."""
        with get_studio_db() as db:
            rows = db.execute(
                "SELECT * FROM cross_game_lessons "
                "WHERE agent_role = ? "
                "ORDER BY confidence DESC, confirmation_count DESC "
                "LIMIT ?",
                (agent_role, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def confirm_lesson(self, lesson_id: int, project_id: str) -> None:
        """Mark a lesson as confirmed by another project — increases confidence."""
        now = datetime.now(timezone.utc).isoformat()
        with get_studio_db() as db:
            row = db.execute(
                "SELECT confidence, confirmation_count FROM cross_game_lessons WHERE id = ?",
                (lesson_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Lesson {lesson_id} not found")
            new_conf = min(1.0, row["confidence"] + self._CONFIDENCE_STEP)
            new_count = row["confirmation_count"] + 1
            db.execute(
                "UPDATE cross_game_lessons "
                "SET confidence = ?, confirmation_count = ?, last_confirmed_at = ? "
                "WHERE id = ?",
                (new_conf, new_count, now, lesson_id),
            )
        logger.info(
            "CrossGameLessonStore: confirmed lesson %d from project %s (new conf=%.2f)",
            lesson_id,
            project_id,
            new_conf,
        )

    def get_all_lessons(self, category: str = None) -> list[dict]:
        """Get all lessons, optionally filtered by category."""
        with get_studio_db() as db:
            if category:
                rows = db.execute(
                    "SELECT * FROM cross_game_lessons WHERE category = ? "
                    "ORDER BY confidence DESC, confirmation_count DESC",
                    (category,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM cross_game_lessons "
                    "ORDER BY confidence DESC, confirmation_count DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def format_for_context(self, agent_role: str, limit: int = 3) -> str:
        """Format top lessons as a context block for agent injection.

        Returns empty string if no lessons exist.
        Format:
        ## Studio Lessons (learned from previous games)
        - [three_js] Three.js shadow maps cause 401 on LEGO proxy — disable shadows by default
        - [tool_use] Always call repo_file_list before repo_file_read to avoid stale path errors
        """
        lessons = self.get_lessons(agent_role, limit=limit)
        if not lessons:
            return ""

        lines = ["## Studio Lessons (learned from previous games)"]
        for entry in lessons:
            category = entry.get("category", "general")
            lesson_text = entry.get("lesson", "")
            lines.append(f"- [{category}] {lesson_text}")
        return "\n".join(lines)


cross_game_lesson_store = CrossGameLessonStore()
