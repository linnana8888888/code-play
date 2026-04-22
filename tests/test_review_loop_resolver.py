"""Integration tests for src.main._maybe_resolve_review_loops.

Exercises the three resolution paths end-to-end against real TaskQueue +
ProjectMemory state, so a regression in the orchestrator primitive fails a
cheap unit test rather than a slow pipeline run.

  - APPROVE  → task metadata flagged approved, round counter reset
  - REVISE   → fix task + next-round review task spawned, dependents rewired
  - CAP HIT  → human-gate-review-cap task spawned, dependents rewired to gate

Every test uses a fresh project row + per-project memory db (nuked on teardown)
so round_n starts at 0.
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone

import pytest

from src.database import _db_dir, get_studio_db
from src.iteration import review_state
from src.main import _maybe_resolve_review_loops
from src.memory.project_memory import project_memory
from src.models.tasks import TaskCreate, TaskStatus
from src.orchestrator.task_queue import task_queue


@pytest.fixture
def project_row(request, monkeypatch):
    pid = f"test-rl-{request.node.name.replace('[', '-').replace(']', '')}"
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
            (pid, pid, "review-loop test", "", "html5", None, None, 0, now, now),
        )

    # Stub ws_manager.broadcast — the resolver broadcasts events and we don't
    # want a network/event-loop dep in unit tests.
    import src.main as main_mod

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(main_mod.ws_manager, "broadcast", _noop)

    yield pid

    with get_studio_db() as db:
        db.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


def _pipeline_spec(step_id: str = "review"):
    """Minimal pipeline spec matching the review_loop shape in pipelines.yaml."""
    return {
        "test-pipe": {
            "steps": [
                {
                    "id": step_id,
                    "agent": "code-reviewer",
                    "type": "review_loop",
                    "task": "review v{{cycle_n}} round {{review_round_n}}",
                    "expected_outputs": [
                        {
                            "kind": "memory_key",
                            "type": "artifact",
                            "key": "code_review_v{{cycle_n}}_r{{review_round_n}}",
                        }
                    ],
                    "review_loop": {
                        "max_rounds": 3,
                        "verdict_artifact_key": "code_review_v{{cycle_n}}_r{{review_round_n}}",
                        "fix_agent": "frontend-developer",
                        "fix_task": "fix round {{review_round_n}} for v{{cycle_n}}",
                        "fix_expected_outputs": [
                            {"kind": "memory_key", "type": "artifact",
                             "key": "game_html_v{{cycle_n}}", "min_bytes": 1},
                        ],
                        "next_review_task": "re-review round {{review_round_n}} v{{cycle_n}}",
                    },
                }
            ]
        }
    }


def _mk_review_task(pid: str, cycle_n: int = 1, round_n: int = 1, deps=None):
    return task_queue.create(
        TaskCreate(
            project_id=pid,
            title="[test-pipe] review",
            description=f"review v{cycle_n} round {round_n}",
            depends_on=deps or [],
            created_by="test",
            metadata={"cycle_n": cycle_n, "review_round_n": round_n, "loop_role": "review"},
            expected_outputs=[
                {"kind": "memory_key", "type": "artifact",
                 "key": f"code_review_v{cycle_n}_r{round_n}"},
            ],
        )
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


@pytest.mark.asyncio
async def test_approve_marks_resolved_and_resets_round(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    project_memory.write(project_row, "artifact", "code_review_v1_r1",
                         "all good\n\nVERDICT: APPROVE", created_by="test")
    # Simulate that bump_round was called when the task was created.
    review_state.bump_round(project_row)
    assert review_state.get_round_n(project_row) == 1

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    updated = task_queue.get(review.id)
    assert (updated.metadata or {}).get("review_resolution") == "approved"
    assert (updated.metadata or {}).get("verdict") == "APPROVE"
    # Round counter reset on approve so next cycle/pipeline starts fresh.
    assert review_state.get_round_n(project_row) == 0


@pytest.mark.asyncio
async def test_approve_with_fixes_also_approves(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    project_memory.write(project_row, "artifact", "code_review_v1_r1",
                         "few nits\n\nVERDICT: APPROVE WITH FIXES", created_by="test")
    review_state.bump_round(project_row)

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    updated = task_queue.get(review.id)
    assert (updated.metadata or {}).get("review_resolution") == "approved"
    assert (updated.metadata or {}).get("verdict") == "APPROVE_WITH_FIXES"


@pytest.mark.asyncio
async def test_revise_spawns_fix_and_next_review_and_rewires_dependent(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    downstream = task_queue.create(TaskCreate(
        project_id=project_row,
        title="[test-pipe] downstream",
        description="waits on review",
        depends_on=[review.id],
        created_by="test",
    ))
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    project_memory.write(project_row, "artifact", "code_review_v1_r1",
                         "found 2 blockers\n\nVERDICT: REVISE", created_by="test")
    review_state.bump_round(project_row)  # round_n = 1
    assert review_state.get_round_n(project_row) == 1

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    updated_review = task_queue.get(review.id)
    md = updated_review.metadata or {}
    assert md.get("review_resolution") == "revise_spawned"
    assert md.get("verdict") == "REVISE"
    fix_id = md.get("fix_task_id")
    next_review_id = md.get("next_review_task_id")
    assert fix_id and next_review_id

    # Fix task wired correctly: depends on original review, assigned to fix_agent.
    fix_task = task_queue.get(fix_id)
    assert fix_task.depends_on == [review.id]
    assert fix_task.assignee_type == "frontend-developer"
    assert (fix_task.metadata or {}).get("loop_role") == "fix"
    assert (fix_task.metadata or {}).get("review_round_n") == 1

    # Next review depends on the fix task and carries round_n=2.
    next_review = task_queue.get(next_review_id)
    assert next_review.depends_on == [fix_id]
    assert next_review.title == "[test-pipe] review"  # same title, preserves DAG identity
    assert (next_review.metadata or {}).get("review_round_n") == 2

    # Round counter bumped to 2.
    assert review_state.get_round_n(project_row) == 2

    # Downstream rewired from old review → new review.
    downstream_after = task_queue.get(downstream.id)
    assert downstream_after.depends_on == [next_review_id]


@pytest.mark.asyncio
async def test_cap_hit_spawns_human_gate_and_rewires(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=3)
    downstream = task_queue.create(TaskCreate(
        project_id=project_row,
        title="[test-pipe] downstream",
        description="waits on review",
        depends_on=[review.id],
        created_by="test",
    ))
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    project_memory.write(project_row, "artifact", "code_review_v1_r3",
                         "still broken\n\nVERDICT: REVISE", created_by="test")
    # Exhaust the budget — 3 bumps = at cap, should_continue=False.
    review_state.bump_round(project_row)
    review_state.bump_round(project_row)
    review_state.bump_round(project_row)
    assert review_state.should_continue(project_row) is False

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    updated_review = task_queue.get(review.id)
    md = updated_review.metadata or {}
    assert md.get("review_resolution") == "cap_gated"
    gate_id = md.get("cap_gate_task_id")
    assert gate_id

    gate = task_queue.get(gate_id)
    assert "cap-gate" in gate.title
    assert gate.depends_on == [review.id]
    assert "Review round cap hit" in (gate.description or "")
    # Gate metadata preserves review_round_n for the human.
    assert (gate.metadata or {}).get("review_gate_kind") == "review_cap"

    # Downstream task now waits on the gate, not the old review.
    downstream_after = task_queue.get(downstream.id)
    assert downstream_after.depends_on == [gate_id]


@pytest.mark.asyncio
async def test_malformed_verdict_text_treated_as_revise(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    # No VERDICT line at all — parser falls back to REVISE.
    project_memory.write(project_row, "artifact", "code_review_v1_r1",
                         "review with no verdict line", created_by="test")
    review_state.bump_round(project_row)

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    md = (task_queue.get(review.id).metadata or {})
    assert md.get("review_resolution") == "revise_spawned"
    assert md.get("verdict") == "REVISE"


@pytest.mark.asyncio
async def test_resolver_is_idempotent(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    project_memory.write(project_row, "artifact", "code_review_v1_r1",
                         "VERDICT: APPROVE", created_by="test")
    review_state.bump_round(project_row)

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())
    first = dict((task_queue.get(review.id).metadata) or {})

    # Second pass must not alter state (review_resolution already set).
    await _maybe_resolve_review_loops(project_row, _pipeline_spec())
    second = dict((task_queue.get(review.id).metadata) or {})

    assert first == second


@pytest.mark.asyncio
async def test_missing_artifact_treated_as_revise(project_row):
    review = _mk_review_task(project_row, cycle_n=1, round_n=1)
    task_queue.update_status(review.id, TaskStatus.COMPLETED)
    # NO memory write — artifact absent. Resolver must not APPROVE by accident.
    review_state.bump_round(project_row)

    await _maybe_resolve_review_loops(project_row, _pipeline_spec())

    md = (task_queue.get(review.id).metadata or {})
    assert md.get("review_resolution") == "revise_spawned"
    assert md.get("verdict") == "REVISE"
