"""Unit tests for the cyclic-pipeline bootstrap gate.

Locks the contract that iterate_artifact refuses to run without goals_md:
  - If memory has goals_md → noop (phased-producer already seeded it).
  - If memory is cold but <artifact_repo>/GOALS.md exists → seed + proceed.
  - If neither → raise GoalsBootstrapError with a concrete fix-hint.

These paths were a silent-degrade hazard before PR-4: Mode-B projects that
skipped phased-producer produced postmortems saying "goals_md missing" and
proposers then drifted to freeform suggestions instead of §2-cited changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.database import get_studio_db
from src.iteration.bootstrap import GoalsBootstrapError, ensure_goals_md
from src.memory.project_memory import project_memory


@pytest.fixture
def studio_project(request):
    """Create a throwaway studio project row so project_memory can attach."""
    pid = f"test-bootstrap-{request.node.name.replace('[', '-').replace(']', '')}"
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "bootstrap test", "", "html5", None, None, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


def test_noop_when_goals_md_already_in_memory(studio_project):
    pid = studio_project
    project_memory.write(pid, "artifact", "goals_md", "## existing\n", created_by="test")

    ensure_goals_md(pid)  # must not raise

    # Content is unchanged — bootstrap did not overwrite.
    assert project_memory.read(pid, "artifact", "goals_md") == "## existing\n"


def test_seeds_from_artifact_repo_when_memory_cold(studio_project, tmp_path):
    pid = studio_project
    goals = tmp_path / "GOALS.md"
    goals.write_text(
        "# Goals for test\n\n## §2 Metrics\n- accuracy: target 0.6\n",
        encoding="utf-8",
    )
    project_memory.write(
        pid, "artifact", "artifact_repo_path", str(tmp_path), created_by="test"
    )

    ensure_goals_md(pid)

    seeded = project_memory.read(pid, "artifact", "goals_md")
    assert seeded is not None
    assert "accuracy: target 0.6" in seeded


def test_raises_when_no_memory_and_no_repo_path(studio_project):
    pid = studio_project
    # Nothing in memory — no goals_md, no artifact_repo_path.

    with pytest.raises(GoalsBootstrapError) as exc_info:
        ensure_goals_md(pid)

    msg = str(exc_info.value)
    assert "goals_md" in msg
    assert "artifact_repo_path" in msg
    assert exc_info.value.status_code == 400


def test_raises_when_repo_registered_but_no_goals_file(studio_project, tmp_path):
    pid = studio_project
    project_memory.write(
        pid, "artifact", "artifact_repo_path", str(tmp_path), created_by="test"
    )
    # No GOALS.md file in tmp_path.

    with pytest.raises(GoalsBootstrapError) as exc_info:
        ensure_goals_md(pid)

    msg = str(exc_info.value)
    assert "GOALS.md" in msg
    assert str(tmp_path) in msg
    assert exc_info.value.status_code == 400


def test_empty_goals_md_in_memory_triggers_seed(studio_project, tmp_path):
    """Whitespace-only goals_md in memory is treated as missing — falls through
    to the repo seed path. Prevents a garbled entry from blocking a real seed.
    """
    pid = studio_project
    project_memory.write(pid, "artifact", "goals_md", "   \n", created_by="test")
    goals = tmp_path / "GOALS.md"
    goals.write_text("# real goals\n", encoding="utf-8")
    project_memory.write(
        pid, "artifact", "artifact_repo_path", str(tmp_path), created_by="test"
    )

    ensure_goals_md(pid)

    assert project_memory.read(pid, "artifact", "goals_md") == "# real goals\n"


def test_path_expansion_on_tilde(studio_project, tmp_path, monkeypatch):
    """artifact_repo_path with a leading ~ is expanded before reading."""
    pid = studio_project
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "proj").mkdir()
    goals = tmp_path / "proj" / "GOALS.md"
    goals.write_text("# tilde ok\n", encoding="utf-8")
    project_memory.write(
        pid, "artifact", "artifact_repo_path", "~/proj", created_by="test"
    )

    ensure_goals_md(pid)

    assert project_memory.read(pid, "artifact", "goals_md") == "# tilde ok\n"
