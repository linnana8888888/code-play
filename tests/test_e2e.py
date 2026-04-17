"""End-to-end integration test for Code PLAY.

Tests the full stack without making actual LLM calls:
1. Boot the app
2. Create a project
3. Verify agent definitions loaded
4. Create a task
5. Spawn an agent
6. Post a channel message
7. Write and read project memory
8. Verify governance checks
9. Check stats
"""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.database import init_studio_db
from src.orchestrator.agent_registry import registry
from src.runtime.tool_executor import tool_executor
from src.runtime.session_store import session_store
from src.runtime.skill_registry import skill_registry


@pytest.fixture(scope="module", autouse=True)
def setup():
    """Initialize DB and load agents before tests."""
    init_studio_db()
    registry.load_config()
    registry.load_agents()
    tool_executor.load_governance()
    session_store.ensure_table()
    skill_registry.load_skills()
    skill_registry.load_governance()


client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agents_loaded"] >= 20


def test_list_agent_definitions():
    resp = client.get("/api/agents/definitions")
    assert resp.status_code == 200
    defs = resp.json()
    assert len(defs) >= 20

    # Verify game designer exists
    names = [d["id"] for d in defs]
    assert "game-designer" in names


def test_list_categories():
    resp = client.get("/api/agents/categories")
    assert resp.status_code == 200
    cats = resp.json()
    assert "game-development" in cats


def test_create_project():
    resp = client.post("/api/projects", json={
        "name": "Test Puzzle Game",
        "description": "A simple puzzle game for testing",
        "tech_stack": "threejs",
    })
    assert resp.status_code == 200
    project = resp.json()
    assert project["name"] == "Test Puzzle Game"
    assert project["id"].startswith("proj-")
    return project["id"]


def test_list_projects():
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) >= 1


def test_create_and_list_tasks():
    # Get a project first
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    resp = client.post("/api/tasks", json={
        "project_id": project_id,
        "title": "Create Game Design Document",
        "description": "Design a simple puzzle game with Three.js",
        "priority": 10,
    })
    assert resp.status_code == 200
    task = resp.json()
    assert task["title"] == "Create Game Design Document"
    assert task["status"] == "pending"

    # List tasks
    resp = client.get(f"/api/tasks?project_id={project_id}")
    assert resp.status_code == 200
    tasks = resp.json()
    assert len(tasks) >= 1


def test_spawn_agent():
    resp = client.post("/api/agents/spawn", params={
        "agent_type": "game-designer",
    })
    assert resp.status_code == 200
    instance = resp.json()
    assert instance["agent_type"] == "game-designer"
    assert instance["status"] == "assigned"
    assert instance["id"].startswith("game-designer-")


def test_list_instances():
    resp = client.get("/api/agents/instances")
    assert resp.status_code == 200
    instances = resp.json()
    assert len(instances) >= 1


def test_spawn_unknown_agent_fails():
    resp = client.post("/api/agents/spawn", params={
        "agent_type": "nonexistent-agent",
    })
    assert resp.status_code == 400


def test_post_and_read_messages():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    resp = client.post("/api/messages", params={
        "project_id": project_id,
        "channel": "general",
        "sender": "game-designer-test",
        "content": "Starting work on the GDD",
    })
    assert resp.status_code == 200

    resp = client.get(f"/api/messages?project_id={project_id}&channel=general")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) >= 1
    assert messages[-1]["content"] == "Starting work on the GDD"


def test_list_channels():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    resp = client.get(f"/api/messages/channels?project_id={project_id}")
    assert resp.status_code == 200
    channels = resp.json()
    assert "general" in channels


def test_project_memory():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    # Write
    resp = client.post(f"/api/projects/{project_id}/memory", params={
        "mem_type": "decision",
        "key": "game-genre",
        "content": "Puzzle game with tile-matching mechanic",
        "created_by": "game-designer",
    })
    assert resp.status_code == 200

    # Read
    resp = client.get(f"/api/projects/{project_id}/memory", params={
        "mem_type": "decision",
        "key": "game-genre",
    })
    assert resp.status_code == 200
    assert resp.json()["content"] == "Puzzle game with tile-matching mechanic"

    # Search
    resp = client.get(f"/api/projects/{project_id}/memory/search", params={
        "query": "puzzle",
    })
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1


def test_governance_log():
    resp = client.get("/api/governance/log")
    assert resp.status_code == 200


def test_governance_approvals():
    resp = client.get("/api/governance/approvals")
    assert resp.status_code == 200


def test_governance_check_builtin():
    """Builtin tools should be allowed."""
    decision = tool_executor.check_permission("file_read", "test-agent")
    from src.models.governance import GovernanceDecision
    assert decision == GovernanceDecision.ALLOWED


def test_governance_check_blocked():
    """Blocked tools should be denied."""
    decision = tool_executor.check_permission("rm_rf_outside_project", "test-agent")
    from src.models.governance import GovernanceDecision
    assert decision == GovernanceDecision.BLOCKED


def test_governance_check_restricted():
    """Restricted tools should need approval."""
    decision = tool_executor.check_permission("git_push", "test-agent")
    from src.models.governance import GovernanceDecision
    assert decision == GovernanceDecision.PENDING_APPROVAL


def test_governance_check_unknown():
    """Unknown tools should be treated as restricted."""
    decision = tool_executor.check_permission("totally_new_tool", "test-agent")
    from src.models.governance import GovernanceDecision
    assert decision == GovernanceDecision.PENDING_APPROVAL


def test_stats():
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["projects"] >= 1
    assert stats["agents"]["definitions"] >= 20


def test_terminate_agent():
    instances = client.get("/api/agents/instances").json()
    if instances:
        instance_id = instances[0]["id"]
        resp = client.post(f"/api/agents/{instance_id}/terminate")
        assert resp.status_code == 200


def test_agent_cost_endpoint():
    instances = client.get("/api/agents/instances").json()
    if instances:
        instance_id = instances[0]["id"]
        resp = client.get(f"/api/agents/{instance_id}/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert "budget_max_tokens" in data
        assert "budget_max_usd" in data
        assert "breakdown" in data


def test_agent_cost_not_found():
    resp = client.get("/api/agents/nonexistent/cost")
    assert resp.status_code == 404


def test_atomic_task_checkout():
    """Two checkout attempts on the same task — only first succeeds."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskCreate

    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    task = task_queue.create(TaskCreate(
        project_id=project_id,
        title="Atomic checkout test",
        description="Should only be claimed once",
        created_by="test",
    ))

    # First checkout succeeds
    result1 = task_queue.checkout(task.id, "agent-1")
    assert result1 is not None
    assert result1.assigned_to == "agent-1"

    # Second checkout fails (already taken)
    result2 = task_queue.checkout(task.id, "agent-2")
    assert result2 is None


def test_budget_fields_on_spawn():
    """Spawned agent inherits budget limits from definition defaults."""
    resp = client.post("/api/agents/spawn", params={"agent_type": "game-designer"})
    assert resp.status_code == 200
    instance_id = resp.json()["id"]

    resp = client.get(f"/api/agents/{instance_id}/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_max_tokens"] == 200000
    assert data["budget_max_usd"] == 1.0


def test_goal_ancestry_in_project():
    """Project created with a goal field."""
    resp = client.post("/api/projects", json={
        "name": "Goal Test Game",
        "description": "Testing goal ancestry",
        "goal": "Build a tile-matching puzzle game",
        "tech_stack": "threejs",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["goal"] == "Build a tile-matching puzzle game"


def test_task_parent_hierarchy():
    """Tasks can have a parent_task_id for hierarchy."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskCreate

    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    parent = task_queue.create(TaskCreate(
        project_id=project_id,
        title="Parent: Design game systems",
        created_by="test",
    ))

    child = task_queue.create(TaskCreate(
        project_id=project_id,
        title="Child: Design combat mechanics",
        parent_task_id=parent.id,
        created_by="test",
    ))

    assert child.parent_task_id == parent.id
    fetched = task_queue.get(child.id)
    assert fetched.parent_task_id == parent.id


def test_session_store():
    """Session store can save and load conversations."""
    from src.runtime.session_store import session_store

    conversation = [
        {"role": "system", "content": "You are a game designer."},
        {"role": "user", "content": "Design a puzzle game."},
    ]

    session_id = session_store.save(
        instance_id="test-agent-123",
        conversation=conversation,
        tokens_used=500,
        iteration=2,
    )
    assert session_id.startswith("sess-")

    loaded = session_store.load(session_id)
    assert loaded is not None
    assert loaded["instance_id"] == "test-agent-123"
    assert len(loaded["conversation"]) == 2
    assert loaded["tokens_used"] == 500

    # Update
    conversation.append({"role": "assistant", "content": "Here's a puzzle game design..."})
    session_store.save(
        instance_id="test-agent-123",
        conversation=conversation,
        tokens_used=1000,
        iteration=3,
        session_id=session_id,
    )

    loaded2 = session_store.load(session_id)
    assert len(loaded2["conversation"]) == 3
    assert loaded2["tokens_used"] == 1000


def test_session_list():
    """Session store can list sessions."""
    from src.runtime.session_store import session_store

    sessions = session_store.list_sessions()
    assert len(sessions) >= 1


def test_skill_list():
    """Skills endpoint returns loaded skills."""
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()
    assert len(skills) >= 1
    assert any(s["id"] == "coding-standards" for s in skills)


def test_skill_get():
    """Can retrieve a specific skill."""
    resp = client.get("/api/skills/coding-standards")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Coding Standards"
    assert "content" in data


def test_skill_not_found():
    resp = client.get("/api/skills/nonexistent-skill")
    assert resp.status_code == 404


def test_skill_approve_and_check():
    """Skill approval flow: builtin auto-approved, non-builtin needs approval."""
    from src.runtime.skill_registry import skill_registry

    # Builtin skill is auto-approved
    assert skill_registry.is_approved("coding-standards", "game-designer") is True

    # Non-builtin needs explicit approval
    assert skill_registry.is_approved("some-new-skill", "game-designer") is False

    # Approve via API
    resp = client.post("/api/skills/coding-standards/approve", params={
        "agent_type": "frontend-developer",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_workspace_manager():
    """Workspace manager can create and find workspace paths."""
    from src.runtime.workspace import workspace_manager
    from pathlib import Path
    import shutil

    # Use a dedicated test project dir
    test_project_id = "proj-ws-test"
    test_dir = Path("projects") / test_project_id
    test_dir.mkdir(parents=True, exist_ok=True)
    # Put a file in it so copy has something to work with
    (test_dir / "README.md").write_text("test")

    try:
        # Before creation, no workspace
        assert workspace_manager.get_workspace_path(test_project_id, "test-agent-ws") is None

        # Create workspace (will use copy since project dir isn't a git repo)
        path = workspace_manager.create(test_project_id, "test-agent-ws")
        assert path.exists()

        # Now it exists
        found = workspace_manager.get_workspace_path(test_project_id, "test-agent-ws")
        assert found is not None

        # Cleanup
        workspace_manager.cleanup(test_project_id, "test-agent-ws")
        assert not path.exists()
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_resume_endpoint_no_sessions():
    """Resume endpoint returns 404 when no sessions exist for the agent."""
    # Spawn a fresh agent
    resp = client.post("/api/agents/spawn", params={"agent_type": "game-designer"})
    instance_id = resp.json()["id"]

    resp = client.post(f"/api/agents/{instance_id}/resume", params={
        "task_prompt": "Continue the design",
    })
    assert resp.status_code == 404


def test_ready_tasks():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    resp = client.get(f"/api/projects/{project_id}/tasks/ready")
    assert resp.status_code == 200


# ==================== Per-task LLM picker (#4) ====================


def test_available_models_endpoint():
    resp = client.get("/api/models/available")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) >= 5
    ids = {m["id"] for m in models}
    assert "omlx/Qwen3.5-9B-MLX-4bit" in ids
    assert any("claude" in m["id"] for m in models)
    # Each option carries pricing fields so the UI can surface cost
    for m in models:
        assert "input_per_1m" in m and "output_per_1m" in m


def test_task_model_override_roundtrip():
    project = client.post("/api/projects", json={
        "name": "Model Override Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    task = client.post("/api/tasks", json={
        "project_id": project["id"],
        "title": "Test override",
        "description": "dry run",
        "model_override": "anthropic/anthropic.claude-haiku-4-5-20251001-v1:0",
    }).json()
    assert task["model_override"].endswith("haiku-4-5-20251001-v1:0")

    # PATCH updates the override
    resp = client.patch(f"/api/tasks/{task['id']}", json={
        "model_override": "openai/gpt-5-2025-08-07",
    })
    assert resp.status_code == 200
    assert resp.json()["model_override"] == "openai/gpt-5-2025-08-07"

    # GET returns the updated value
    got = client.get(f"/api/tasks/{task['id']}").json()
    assert got["model_override"] == "openai/gpt-5-2025-08-07"


# ==================== Phased producer gates (#2) ====================


def test_phased_producer_pipeline_registered():
    pipelines = client.get("/api/pipelines").json()
    ids = {p["id"] for p in pipelines}
    assert "phased-producer" in ids
    pp = next(p for p in pipelines if p["id"] == "phased-producer")
    gate_steps = [s for s in pp["steps"] if s.get("type") == "human-gate"]
    assert len(gate_steps) == 3


def test_gate_list_approve_and_advance():
    """Launch the phased pipeline, approve a gate, verify downstream advances."""
    project = client.post("/api/projects", json={
        "name": "Gate Test Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    project_id = project["id"]

    resp = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project_id,
        "input_text": "a cozy farming game on a tiny asteroid",
    })
    assert resp.status_code == 200
    tasks_by_step = resp.json()["tasks"]
    assert "gate-concept" in tasks_by_step
    assert "gate-mechanics" in tasks_by_step

    # All 3 gates are created even before their upstream steps finish
    gates = client.get(f"/api/projects/{project_id}/gates").json()
    step_ids = {g["step_id"] for g in gates}
    assert step_ids == {"gate-concept", "gate-mechanics", "gate-laf"}
    # None are ready yet — upstream steps are still running/pending
    assert all(not g["ready"] for g in gates)

    # Simulate the concept agent completing so the first gate becomes ready
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus
    concept_id = tasks_by_step["concept"]
    task_queue.update_status(
        concept_id,
        TaskStatus.COMPLETED,
        result={"summary": "3 concept directions: (A)/(B)/(C)"},
    )

    gates = client.get(f"/api/projects/{project_id}/gates").json()
    concept_gate = next(g for g in gates if g["step_id"] == "gate-concept")
    assert concept_gate["ready"] is True
    assert concept_gate["preceding_result"]["summary"].startswith("3 concept")

    # Approve the concept gate
    resp = client.post(f"/api/gates/{concept_gate['task_id']}/approve", json={
        "feedback": "go with B",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    approved = client.get(f"/api/tasks/{concept_gate['task_id']}").json()
    assert approved["status"] == "completed"
    assert approved["result"]["decision"] == "approved"


def test_gate_revise_spawns_revision_and_rebinds():
    """Request changes on a gate → revision task + gate depends on it."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus

    project = client.post("/api/projects", json={
        "name": "Gate Revise Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    project_id = project["id"]

    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project_id,
        "input_text": "puzzle platformer",
    }).json()
    concept_id = launch["tasks"]["concept"]
    mechanics_id = launch["tasks"]["mechanics"]

    # Complete concept, approve its gate so mechanics becomes ready
    task_queue.update_status(concept_id, TaskStatus.COMPLETED, result={"summary": "ok"})
    gates = client.get(f"/api/projects/{project_id}/gates").json()
    concept_gate = next(g for g in gates if g["step_id"] == "gate-concept")
    client.post(f"/api/gates/{concept_gate['task_id']}/approve", json={})

    # Complete mechanics so gate-mechanics becomes ready
    task_queue.update_status(
        mechanics_id,
        TaskStatus.COMPLETED,
        result={"summary": "mechanics v1"},
    )
    gates = client.get(f"/api/projects/{project_id}/gates").json()
    mech_gate = next(g for g in gates if g["step_id"] == "gate-mechanics")
    assert mech_gate["ready"] is True

    # Request changes
    resp = client.post(f"/api/gates/{mech_gate['task_id']}/revise", json={
        "feedback": "please add a co-op mode",
    })
    assert resp.status_code == 200
    revision_id = resp.json()["revision_task_id"]

    # Revision task was created, assigned to the mechanics agent
    revision = client.get(f"/api/tasks/{revision_id}").json()
    assert revision["project_id"] == project_id
    assert "co-op" in revision["description"]

    # Gate is still pending, now depends on the revision task as well
    gate_task = client.get(f"/api/tasks/{mech_gate['task_id']}").json()
    assert gate_task["status"] == "pending"
    assert revision_id in gate_task["depends_on"]
    assert gate_task["result"]["decision"] == "changes_requested"


def test_gate_revise_requires_feedback():
    """Revise without feedback is rejected."""
    project = client.post("/api/projects", json={
        "name": "Gate Feedback Guard",
        "description": "",
        "tech_stack": "web",
    }).json()
    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project["id"],
        "input_text": "test",
    }).json()

    gate_id = launch["tasks"]["gate-concept"]
    resp = client.post(f"/api/gates/{gate_id}/revise", json={"feedback": "   "})
    assert resp.status_code == 400


def test_gate_endpoints_reject_non_gate_task():
    """approve/revise on a non-gate task 400s."""
    project = client.post("/api/projects", json={
        "name": "Non-gate guard",
        "description": "",
        "tech_stack": "web",
    }).json()
    task = client.post("/api/tasks", json={
        "project_id": project["id"],
        "title": "plain task",
    }).json()
    resp = client.post(f"/api/gates/{task['id']}/approve", json={})
    assert resp.status_code == 400
    resp = client.post(f"/api/gates/{task['id']}/revise", json={"feedback": "x"})
    assert resp.status_code == 400
