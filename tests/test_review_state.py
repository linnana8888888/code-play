"""Unit tests for per-project review-round state.

Mirrors the shape of `src/iteration/cycle_state.py`'s behavior tests.
Locks the contract used by the orchestrator's review↔implementer fix-loop:
- round_n starts at 0, bumps monotonically
- reset_round() zeros on fresh-loop entry
- should_continue() returns False once round_n hits budget OR halt is pinned
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

import pytest

from src.database import _db_dir, get_studio_db
from src.iteration import review_state
from src.memory.project_memory import project_memory


@pytest.fixture
def studio_project(request):
    pid = f"test-review-state-{request.node.name.replace('[', '-').replace(']', '')}"
    # Per-test memory.db — nuke any leftover from prior runs so round_n starts at 0.
    proj_dir = _db_dir() / pid
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    now = datetime.now(timezone.utc).isoformat()
    with get_studio_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, description, goal, tech_stack, repo_url, repo_name, "
            "require_roster_approval, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, pid, "review-state test", "", "html5", None, None, 0, now, now),
        )
    yield pid
    with get_studio_db() as db:
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


def test_round_n_defaults_to_zero(studio_project):
    assert review_state.get_round_n(studio_project) == 0


def test_bump_round_increments_monotonically(studio_project):
    assert review_state.bump_round(studio_project) == 1
    assert review_state.bump_round(studio_project) == 2
    assert review_state.bump_round(studio_project) == 3
    assert review_state.get_round_n(studio_project) == 3


def test_reset_round_zeros_counter(studio_project):
    review_state.bump_round(studio_project)
    review_state.bump_round(studio_project)
    assert review_state.get_round_n(studio_project) == 2
    review_state.reset_round(studio_project)
    assert review_state.get_round_n(studio_project) == 0


def test_budget_defaults_to_three(studio_project):
    assert review_state.get_budget(studio_project) == 3


def test_budget_is_overridable(studio_project):
    review_state.set_budget(studio_project, 5)
    assert review_state.get_budget(studio_project) == 5


def test_should_continue_true_when_under_budget(studio_project):
    review_state.bump_round(studio_project)  # r=1
    assert review_state.should_continue(studio_project) is True


def test_should_continue_false_at_budget(studio_project):
    review_state.bump_round(studio_project)  # r=1
    review_state.bump_round(studio_project)  # r=2
    review_state.bump_round(studio_project)  # r=3, = default budget
    assert review_state.should_continue(studio_project) is False


def test_should_continue_false_when_halted(studio_project):
    # Under budget but explicitly halted — caller (human-gate escape) pinned it.
    review_state.set_halt(studio_project, "rounds_exhausted")
    assert review_state.should_continue(studio_project) is False
    assert review_state.get_halt_reason(studio_project) == "rounds_exhausted"


def test_clear_halt_re_enables_loop(studio_project):
    review_state.set_halt(studio_project, "rounds_exhausted")
    assert review_state.should_continue(studio_project) is False
    review_state.clear_halt(studio_project)
    # After halt clears and with r=0 < budget=3, loop may continue.
    assert review_state.should_continue(studio_project) is True


def test_invalid_round_n_in_memory_treated_as_zero(studio_project):
    project_memory.write(studio_project, "review", "round_n", "not-an-int", created_by="test")
    assert review_state.get_round_n(studio_project) == 0


def test_invalid_budget_in_memory_falls_back_to_default(studio_project):
    project_memory.write(studio_project, "review", "budget", "garbage", created_by="test")
    assert review_state.get_budget(studio_project) == 3
