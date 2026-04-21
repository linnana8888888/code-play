"""Bootstrap helpers for cyclic pipelines.

When a project enters `iterate_artifact` without going through `phased-producer`
first (Mode B — iterate on an existing game), the project's memory is cold —
no `goals_md`, `tech_plan_v1`, `laf_brief_v1`. Without GOALS.md, the postmortem
agent cannot cite §2 metrics and proposers drift to freeform suggestions.

This module enforces GOALS.md as a hard precondition and auto-seeds from the
artifact repo when possible. Called from `run_pipeline()` at cyclic-pipeline
start so the failure surfaces BEFORE any tasks spawn.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.memory.project_memory import project_memory

logger = logging.getLogger(__name__)


def _ensure_repo_fresh(repo_path: Path) -> None:
    """Pull latest if repo_path is a git checkout."""
    if not (repo_path / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        logger.info("Bootstrap: pulled latest for %s", repo_path)
    except Exception as exc:
        logger.warning("Bootstrap: git pull failed for %s: %s", repo_path, exc)


class GoalsBootstrapError(Exception):
    """Raised when goals_md cannot be found in memory or seeded from repo."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def ensure_goals_md(project_id: str) -> None:
    """Require goals_md in project memory before a cyclic pipeline runs.

    If goals_md is already in memory (phased-producer seeded it), proceed.
    Otherwise, read artifact_repo_path + seed from `<repo>/GOALS.md`. If
    neither source exists, raise GoalsBootstrapError — silently proceeding
    produces degraded postmortems that cite no goals.
    """
    existing = project_memory.read(project_id, "artifact", "goals_md")
    if existing and existing.strip():
        return

    repo_raw = project_memory.read(project_id, "artifact", "artifact_repo_path")
    if not repo_raw or not repo_raw.strip():
        raise GoalsBootstrapError(
            "iterate_artifact requires goals_md in memory. Seed "
            "memory['goals_md'] directly, or register "
            "memory['artifact_repo_path'] pointing at a repo containing "
            "GOALS.md so it can be auto-seeded.",
        )

    repo_path = Path(repo_raw.strip()).expanduser()
    _ensure_repo_fresh(repo_path)

    goals_file = repo_path / "GOALS.md"
    if not goals_file.is_file():
        raise GoalsBootstrapError(
            f"iterate_artifact requires GOALS.md — not in memory, and not "
            f"found at {goals_file}. Create it (see docs/iteration_contract.md "
            f"for required structure) or seed memory['goals_md'] manually.",
        )

    try:
        content = goals_file.read_text(encoding="utf-8")
    except Exception as exc:
        raise GoalsBootstrapError(
            f"Failed to read {goals_file}: {exc}", status_code=500
        )

    project_memory.write(
        project_id, "artifact", "goals_md", content, created_by="bootstrap"
    )
    logger.info(f"Bootstrap: seeded goals_md for {project_id} from {goals_file}")


def ensure_briefing_md(project_id: str) -> None:
    """Compile and store a fresh BRIEFING.md in project memory.

    Always succeeds — assembles from whatever data is available.
    Called at pipeline start so every agent in the cycle gets current context.
    """
    briefing = project_memory.compile_briefing(project_id)
    project_memory.write(
        project_id, "artifact", "briefing_md", briefing, created_by="bootstrap"
    )
    logger.info("Bootstrap: compiled briefing_md for %s (%d chars)", project_id, len(briefing))
