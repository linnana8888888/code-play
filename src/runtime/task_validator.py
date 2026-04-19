"""Post-run output validator — catches silent-success completions.

Agents occasionally exit cleanly without producing the promised deliverables
(iteration cap reached, long tool-loop ran out of budget, LLM declared itself
done after context-gathering without ever committing). The runtime used to
mark those tasks COMPLETED and advance the pipeline.

This module validates each task's `expected_outputs` contract against what the
agent actually produced, so the pipeline blocks instead of silently dropping
work. Each expected-output entry is one of:

    {"kind": "memory_key", "type": "artifact", "key": "engineer_result_eng-1_v2"}
    {"kind": "branch_commit", "branch": "iteration/eng-1-v2"}
    {"kind": "file_path", "path": "game.html", "min_bytes": 1024}

`validate_outputs` returns a list of human-readable missing-output descriptors.
Empty list → contract satisfied.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.models.tasks import Task
from src.memory.project_memory import ProjectMemory

_log = logging.getLogger(__name__)


def validate_outputs(
    task: Task,
    project_memory: ProjectMemory,
    project_repo_dir: Path | None = None,
) -> list[str]:
    """Return a list of missing-output descriptors. Empty == all present."""
    expected = task.expected_outputs or []
    if not expected:
        return []

    missing: list[str] = []
    for entry in expected:
        try:
            kind = str(entry.get("kind", "")).strip()
        except AttributeError:
            missing.append(f"malformed entry: {entry!r}")
            continue

        if kind == "memory_key":
            mem_type = str(entry.get("type", "artifact"))
            key = str(entry.get("key", ""))
            if not key:
                missing.append(f"memory_key entry missing 'key': {entry!r}")
                continue
            content = project_memory.read(task.project_id, mem_type, key)
            min_bytes = int(entry.get("min_bytes", 1))
            if content is None or len(content) < min_bytes:
                have = 0 if content is None else len(content)
                missing.append(
                    f"memory[{mem_type}/{key}] — have {have} bytes, need ≥{min_bytes}"
                )

        elif kind == "branch_commit":
            branch = str(entry.get("branch", ""))
            if not branch:
                missing.append(f"branch_commit entry missing 'branch': {entry!r}")
                continue
            if project_repo_dir is None or not project_repo_dir.exists():
                # No repo on disk → can't verify; skip rather than false-fail.
                continue
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", f"{branch}^{{commit}}"],
                    cwd=str(project_repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    missing.append(f"branch[{branch}] not found in {project_repo_dir.name}")
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                _log.warning("branch_commit check failed for %s: %s", branch, e)

        elif kind == "file_path":
            rel = str(entry.get("path", ""))
            if not rel:
                missing.append(f"file_path entry missing 'path': {entry!r}")
                continue
            min_bytes = int(entry.get("min_bytes", 1))
            base = project_repo_dir if project_repo_dir else Path.cwd()
            target = (base / rel).resolve()
            if not target.exists():
                missing.append(f"file[{rel}] not found")
                continue
            try:
                size = target.stat().st_size
            except OSError as e:
                missing.append(f"file[{rel}] stat failed: {e}")
                continue
            if size < min_bytes:
                missing.append(f"file[{rel}] — {size} bytes, need ≥{min_bytes}")

        else:
            missing.append(f"unknown expected_output kind: {kind!r}")

    return missing
