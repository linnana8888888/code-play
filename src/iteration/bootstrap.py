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


_CODEBASE_TREE_CODE_EXTS = {".mjs", ".js", ".ts", ".tsx", ".cs", ".lua", ".py", ".html", ".css"}
_CODEBASE_TREE_EXCLUDE_DIRS = {"qa", "telemetry", "node_modules", ".git", "dist", "build", "__pycache__"}
_CODEBASE_TREE_MAX_DEPTH = 3
_CODEBASE_TREE_MAX_ENTRIES = 400


def ensure_codebase_tree(project_id: str) -> None:
    """Compile a codebase_tree_v1 snapshot of the artifact repo for implementer pre-read.

    Reads `artifact_repo_path` from memory, walks up to depth 3, excludes qa/telemetry,
    and writes a human-readable tree + per-file line counts for code files.
    Silently no-ops if artifact_repo_path is missing or invalid — new projects and
    freshly-created repos don't need a tree.

    Called at pipeline start so frontend-developer and gameplay-programmer agents
    can read the repo shape before writing code (per their MANDATORY Pre-Code
    Reading sections).
    """
    repo_raw = project_memory.read(project_id, "artifact", "artifact_repo_path")
    if not repo_raw or not repo_raw.strip():
        return

    repo_path = Path(repo_raw.strip()).expanduser()
    if not repo_path.is_dir():
        logger.warning("Bootstrap: artifact_repo_path %s is not a directory; skipping codebase_tree", repo_path)
        return

    lines: list[str] = [f"# codebase_tree_v1", f"# root: {repo_path}", ""]
    entries = 0
    truncated = False

    def _walk(path: Path, depth: int, prefix: str) -> None:
        nonlocal entries, truncated
        if depth > _CODEBASE_TREE_MAX_DEPTH or truncated:
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return
        children = [c for c in children if c.name not in _CODEBASE_TREE_EXCLUDE_DIRS and not c.name.startswith(".")]
        for i, child in enumerate(children):
            if entries >= _CODEBASE_TREE_MAX_ENTRIES:
                lines.append(f"{prefix}... (truncated at {_CODEBASE_TREE_MAX_ENTRIES} entries)")
                truncated = True
                return
            is_last = i == len(children) - 1
            branch = "└── " if is_last else "├── "
            lines.append(f"{prefix}{branch}{child.name}{'/' if child.is_dir() else ''}")
            entries += 1
            if child.is_dir():
                _walk(child, depth + 1, prefix + ("    " if is_last else "│   "))

    _walk(repo_path, 0, "")

    lines.append("")
    lines.append("## code file line counts")
    line_count_entries: list[tuple[str, int]] = []
    for path in repo_path.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _CODEBASE_TREE_CODE_EXTS:
            continue
        if any(part in _CODEBASE_TREE_EXCLUDE_DIRS or part.startswith(".") for part in path.relative_to(repo_path).parts):
            continue
        try:
            count = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        line_count_entries.append((str(path.relative_to(repo_path)), count))

    line_count_entries.sort(key=lambda x: -x[1])
    for rel, count in line_count_entries[:50]:
        lines.append(f"  {count:>5}  {rel}")
    if len(line_count_entries) > 50:
        lines.append(f"  ... ({len(line_count_entries) - 50} more files)")

    content = "\n".join(lines)
    project_memory.write(
        project_id, "artifact", "codebase_tree_v1", content, created_by="bootstrap"
    )
    logger.info("Bootstrap: compiled codebase_tree_v1 for %s (%d entries, %d code files)",
                project_id, entries, len(line_count_entries))
