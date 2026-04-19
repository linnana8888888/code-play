"""Scaffolder unit tests.

Verify that `scaffold_iteration_artifacts` writes the four-file kit into a
fresh repo, produces contract-clean GOALS.md, is idempotent, and records
paths in project memory. We do NOT spawn the node bot — the template render
is a pure string substitution and is covered here by checking substitutions
landed correctly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.database import get_studio_db
from src.iteration.contract import validate_goals_md
from src.iteration.scaffolder import scaffold_iteration_artifacts
from src.memory.project_memory import project_memory


@pytest.fixture
def studio_project(request):
    """Create a throwaway studio project row so project_memory can attach.

    Yields the project_id. Row is deleted on teardown to keep the studio db
    lean across tests.
    """
    pid = f"test-scaffold-{request.node.name}"
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects (id, name, description, goal, tech_stack, repo_url, repo_name, require_roster_approval, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "scaffolder test", "", "html5", None, None, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))


def test_scaffolder_writes_full_kit(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    written = scaffold_iteration_artifacts(
        project_id,
        artifact,
        project_title="Dodge Meteors",
        game_url="http://localhost:9000/index.html",
    )

    # All expected files exist
    assert Path(written["iteration_contract_path"]).is_file()
    assert Path(written["goals_path"]).is_file()
    assert Path(written["playtest_bot_path"]).is_file()
    assert Path(written["telemetry_dir"]).is_dir()
    assert Path(written["codeplay_config_path"]).is_file()

    # Substitutions landed
    contract = Path(written["iteration_contract_path"]).read_text()
    assert "Dodge Meteors" in contract
    assert str(artifact.resolve()) in contract

    bot = Path(written["playtest_bot_path"]).read_text()
    assert "http://localhost:9000/index.html" in bot
    assert str(artifact.resolve()) in bot
    # GAME_HOOK default was substituted — no raw placeholder remains
    assert "{{GAME_HOOK}}" not in bot
    assert "{{GAME_URL}}" not in bot
    assert "{{REPO_PATH}}" not in bot


def test_scaffolded_goals_passes_contract(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    written = scaffold_iteration_artifacts(project_id, artifact)
    goals = Path(written["goals_path"]).read_text()
    issues = validate_goals_md(goals)
    assert issues == [], f"template GOALS.md fails contract lint: {issues}"


def test_scaffolder_is_idempotent(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    scaffold_iteration_artifacts(project_id, artifact)

    goals_path = artifact / "GOALS.md"
    goals_path.write_text("# user edited\nmedian(score) >= 50\n")

    scaffold_iteration_artifacts(project_id, artifact)  # second call
    assert goals_path.read_text().startswith("# user edited"), \
        "scaffolder clobbered existing GOALS.md without overwrite=True"


def test_scaffolder_overwrite_flag(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    scaffold_iteration_artifacts(project_id, artifact)

    goals_path = artifact / "GOALS.md"
    goals_path.write_text("# user edited\n")

    scaffold_iteration_artifacts(project_id, artifact, overwrite=True)
    assert "user edited" not in goals_path.read_text()


def test_scaffolder_registers_paths_in_memory(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    scaffold_iteration_artifacts(project_id, artifact)

    for key in ("iteration_contract_path", "goals_path", "playtest_bot_path"):
        val = project_memory.read(project_id, mem_type="iteration", key=key)
        assert val, f"missing memory entry: {key}"
        assert Path(val).is_file()

    stamp = project_memory.read(project_id, mem_type="iteration", key="scaffolded_at")
    assert stamp and "T" in stamp  # ISO-8601


def test_custom_game_hook(tmp_path, studio_project):
    project_id = studio_project
    artifact = tmp_path / "artifact"
    hook = "// my custom hook\nawait page.click('#play');"
    written = scaffold_iteration_artifacts(
        project_id, artifact, game_hook=hook
    )
    bot = Path(written["playtest_bot_path"]).read_text()
    assert "// my custom hook" in bot
    assert "#play" in bot
