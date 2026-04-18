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


@pytest.fixture(scope="module", autouse=True)
def _sweep_test_projects():
    """Record project IDs present before tests, sweep anything new after.

    Keeps local dev DBs tidy — tests that create projects won't leak them into
    the projects table and projects/ folder.
    """
    from src.database import get_studio_db

    before: set[str] = set()
    try:
        with get_studio_db() as db:
            before = {r["id"] for r in db.execute("SELECT id FROM projects").fetchall()}
    except Exception:
        pass
    yield
    try:
        with get_studio_db() as db:
            after = {r["id"] for r in db.execute("SELECT id FROM projects").fetchall()}
        leaked = after - before
    except Exception:
        leaked = set()
    for pid in leaked:
        try:
            client.delete(f"/api/projects/{pid}")
        except Exception:
            pass


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
    # concept, mechanics, laf, tech, qa
    assert len(gate_steps) == 5
    gate_ids = {s["id"] for s in gate_steps}
    assert gate_ids == {"gate-concept", "gate-mechanics", "gate-laf", "gate-tech", "gate-qa"}


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

    # All 5 gates are created even before their upstream steps finish
    gates = client.get(f"/api/projects/{project_id}/gates").json()
    step_ids = {g["step_id"] for g in gates}
    assert step_ids == {"gate-concept", "gate-mechanics", "gate-laf", "gate-tech", "gate-qa"}
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


# ==================== #1 Gate auto-surface (WebSocket broadcast) ====================


def test_gate_ready_broadcast_on_pipeline_advance(monkeypatch):
    """#1: when a pipeline step of type human-gate becomes ready, the server
    must broadcast a `gate_ready` event so the dashboard can auto-surface it."""
    import asyncio
    from src.main import _advance_pipeline, ws_manager
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus

    captured: list[dict] = []

    async def fake_broadcast(msg):
        captured.append(msg)

    monkeypatch.setattr(ws_manager, "broadcast", fake_broadcast)

    project = client.post("/api/projects", json={
        "name": "Gate Broadcast Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    project_id = project["id"]

    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project_id,
        "input_text": "a rhythm game about bees",
    }).json()
    concept_id = launch["tasks"]["concept"]
    gate_concept_task_id = launch["tasks"]["gate-concept"]

    # Before concept finishes, gate-concept is blocked -> no broadcast.
    captured.clear()
    asyncio.get_event_loop().run_until_complete(_advance_pipeline(project_id))
    assert not any(m.get("type") == "gate_ready" for m in captured), \
        "gate_ready fired before upstream completed"

    # Complete concept, then advance — gate_ready should now fire.
    task_queue.update_status(concept_id, TaskStatus.COMPLETED, result={"summary": "ok"})
    captured.clear()
    asyncio.get_event_loop().run_until_complete(_advance_pipeline(project_id))

    gate_events = [m for m in captured if m.get("type") == "gate_ready"]
    assert len(gate_events) >= 1, f"expected gate_ready broadcast, got {captured}"

    payload = gate_events[0]["data"]
    assert payload["task_id"] == gate_concept_task_id
    assert payload["project_id"] == project_id
    assert payload["pipeline"] == "phased-producer"
    assert payload["step_id"] == "gate-concept"
    assert "title" in payload
    assert "review_of" in payload  # may be None for concept gate, but key is present


# ==================== #2 Inline asset previews ====================


def test_asset_previews_empty_for_new_project(tmp_path, monkeypatch):
    """List endpoint returns [] when no assets/ dir exists."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    project = client.post("/api/projects", json={
        "name": "Asset Empty Project",
        "description": "",
        "tech_stack": "web",
    }).json()

    resp = client.get(f"/api/projects/{project['id']}/assets/previews")
    assert resp.status_code == 200
    assert resp.json() == []


def test_asset_previews_lists_downloaded_images(tmp_path, monkeypatch):
    """Images placed in projects/{id}/assets/ are surfaced with url + bytes."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    project = client.post("/api/projects", json={
        "name": "Asset List Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    assets = tmp_path / pid / "assets" / "refs"
    assets.mkdir(parents=True)
    (assets / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    (assets / "palette.svg").write_text("<svg/>")
    (assets / "notes.txt").write_text("ignore me")  # non-image, should be filtered

    resp = client.get(f"/api/projects/{pid}/assets/previews")
    assert resp.status_code == 200
    items = resp.json()
    paths = {i["path"] for i in items}
    assert paths == {"refs/hero.png", "refs/palette.svg"}
    for item in items:
        assert item["bytes"] > 0
        assert item["url"].startswith(f"/api/projects/{pid}/assets/file/")


def test_asset_file_streams_content_and_blocks_traversal(tmp_path, monkeypatch):
    """Per-file endpoint returns bytes for valid paths and 404s on traversal."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    project = client.post("/api/projects", json={
        "name": "Asset Stream Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    assets = tmp_path / pid / "assets"
    assets.mkdir(parents=True)
    (assets / "ok.png").write_bytes(b"PNGBYTES")

    # Also place a sibling outside the assets dir the endpoint should NOT serve.
    secret = tmp_path / pid / "secret.txt"
    secret.write_text("top secret")

    resp = client.get(f"/api/projects/{pid}/assets/file/ok.png")
    assert resp.status_code == 200
    assert resp.content == b"PNGBYTES"

    # Path traversal attempt must be rejected.
    resp = client.get(f"/api/projects/{pid}/assets/file/../secret.txt")
    assert resp.status_code == 404


# ==================== #3 tech-plan step ====================


def test_tech_plan_step_and_agent_registered():
    """#3: phased-producer must include a tech-plan step followed by gate-tech,
    and the tech-lead agent must be declared in agents.yaml."""
    # Pipeline shape
    pipelines = client.get("/api/pipelines").json()
    pp = next(p for p in pipelines if p["id"] == "phased-producer")
    step_ids = [s["id"] for s in pp["steps"]]
    assert "tech-plan" in step_ids
    assert "gate-tech" in step_ids
    # gate-tech must come after tech-plan, and build must come after gate-tech
    assert step_ids.index("tech-plan") < step_ids.index("gate-tech")
    assert step_ids.index("gate-tech") < step_ids.index("build")

    tech_plan_step = next(s for s in pp["steps"] if s["id"] == "tech-plan")
    assert tech_plan_step.get("agent") == "tech-lead"

    gate_tech = next(s for s in pp["steps"] if s["id"] == "gate-tech")
    assert gate_tech.get("type") == "human-gate"

    # Agent definition exists
    defs = client.get("/api/agents/definitions").json()
    ids = {d["id"] for d in defs}
    assert "tech-lead" in ids


def test_tech_plan_tasks_created_and_wired_in_launch():
    """Launching phased-producer must materialize a tech-plan task and wire
    gate-tech to depend on it (so the gate surfaces only after tech-plan done)."""
    from src.orchestrator.task_queue import task_queue

    project = client.post("/api/projects", json={
        "name": "Tech Plan Wiring",
        "description": "",
        "tech_stack": "web",
    }).json()

    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project["id"],
        "input_text": "bullet heaven roguelike",
    }).json()
    tasks_by_step = launch["tasks"]

    assert "tech-plan" in tasks_by_step
    assert "gate-tech" in tasks_by_step

    tech_plan_task = task_queue.get(tasks_by_step["tech-plan"])
    gate_tech_task = task_queue.get(tasks_by_step["gate-tech"])
    build_task = task_queue.get(tasks_by_step["build"])

    assert tech_plan_task is not None
    assert gate_tech_task is not None
    assert build_task is not None

    # gate-tech depends on the tech-plan task
    assert tech_plan_task.id in gate_tech_task.depends_on
    # build depends on gate-tech
    assert gate_tech_task.id in build_task.depends_on


# ==================== #4 A/B race + winner promotion ====================


def test_phased_producer_race_pipeline_shape():
    """#4: phased-producer-race exposes parallel build-a/build-b + gate-build-pick + qa."""
    pipelines = client.get("/api/pipelines").json()
    ids = {p["id"] for p in pipelines}
    assert "phased-producer-race" in ids

    race = next(p for p in pipelines if p["id"] == "phased-producer-race")
    step_ids = [s["id"] for s in race["steps"]]
    for sid in ("build-a", "build-b", "gate-build-pick", "qa-playtest"):
        assert sid in step_ids

    pick = next(s for s in race["steps"] if s["id"] == "gate-build-pick")
    assert pick.get("type") == "human-gate"


def test_ab_pick_gate_promotes_winner_a_to_game_html_v1():
    """Approving a pick gate with 'winner: a' feedback must copy
    game_html_v1@a into game_html_v1."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus
    from src.memory.project_memory import project_memory

    project = client.post("/api/projects", json={
        "name": "AB Race A Winner",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    # Seed A/B artifacts directly
    project_memory.write(pid, mem_type="artifact", key="game_html_v1@a",
                         content="<html>A WINS</html>", created_by="test")
    project_memory.write(pid, mem_type="artifact", key="game_html_v1@b",
                         content="<html>B LOSES</html>", created_by="test")

    launch = client.post("/api/pipelines/phased-producer-race/run", json={
        "project_id": pid,
        "input_text": "pick-winner test",
    }).json()
    pick_task_id = launch["tasks"]["gate-build-pick"]

    # Force the pick gate ready by completing its upstream build tasks.
    for step in ("build-a", "build-b"):
        task_queue.update_status(launch["tasks"][step], TaskStatus.COMPLETED,
                                 result={"summary": f"{step} shipped"})

    resp = client.post(f"/api/gates/{pick_task_id}/approve",
                       json={"feedback": "winner: a — cleaner movement"})
    assert resp.status_code == 200
    assert resp.json().get("pick_winner") == "a"

    promoted = project_memory.read(pid, "artifact", "game_html_v1")
    assert promoted == "<html>A WINS</html>"


def test_ab_pick_gate_promotes_winner_b_to_game_html_v1():
    """Same as above but with 'winner: b'."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus
    from src.memory.project_memory import project_memory

    project = client.post("/api/projects", json={
        "name": "AB Race B Winner",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    project_memory.write(pid, mem_type="artifact", key="game_html_v1@a",
                         content="<html>A LOSES</html>", created_by="test")
    project_memory.write(pid, mem_type="artifact", key="game_html_v1@b",
                         content="<html>B WINS</html>", created_by="test")

    launch = client.post("/api/pipelines/phased-producer-race/run", json={
        "project_id": pid,
        "input_text": "b-winner test",
    }).json()
    pick_task_id = launch["tasks"]["gate-build-pick"]

    for step in ("build-a", "build-b"):
        task_queue.update_status(launch["tasks"][step], TaskStatus.COMPLETED,
                                 result={"summary": f"{step} shipped"})

    resp = client.post(f"/api/gates/{pick_task_id}/approve",
                       json={"feedback": "pick: b, the physics feels better"})
    assert resp.status_code == 200
    assert resp.json().get("pick_winner") == "b"
    assert project_memory.read(pid, "artifact", "game_html_v1") == "<html>B WINS</html>"


def test_non_pick_gate_approval_does_not_touch_game_html():
    """Approving a regular gate (not a pick gate) must not mutate game_html_v1."""
    from src.orchestrator.task_queue import task_queue
    from src.models.tasks import TaskStatus
    from src.memory.project_memory import project_memory

    project = client.post("/api/projects", json={
        "name": "No Promote Guard",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    # Seed an existing game_html_v1 that must NOT be overwritten.
    project_memory.write(pid, mem_type="artifact", key="game_html_v1",
                         content="<html>ORIGINAL</html>", created_by="test")

    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": pid,
        "input_text": "non-pick guard",
    }).json()
    concept_id = launch["tasks"]["concept"]
    concept_gate_id = launch["tasks"]["gate-concept"]
    task_queue.update_status(concept_id, TaskStatus.COMPLETED, result={"summary": "ok"})

    resp = client.post(f"/api/gates/{concept_gate_id}/approve",
                       json={"feedback": "winner: a"})  # the keyword must be ignored
    assert resp.status_code == 200
    assert resp.json().get("pick_winner") in (None,)

    assert project_memory.read(pid, "artifact", "game_html_v1") == "<html>ORIGINAL</html>"


# ==================== #5 QA playtest tool ====================


def test_playwright_browser_tool_registered():
    """#5: playwright_browser must be a callable tool in the executor registry."""
    assert "playwright_browser" in tool_executor._tool_registry
    handler = tool_executor._tool_registry["playwright_browser"]
    assert callable(handler)


def test_playwright_browser_tool_is_builtin_or_allowed():
    """playwright_browser must be callable without pending approval so the qa-engineer
    can use it during a pipeline run."""
    from src.models.governance import GovernanceDecision
    decision = tool_executor.check_permission("playwright_browser", "qa-engineer-test")
    assert decision == GovernanceDecision.ALLOWED


def test_qa_engineer_agent_registered():
    """The qa-engineer agent definition must be loaded and spawnable."""
    defs = client.get("/api/agents/definitions").json()
    ids = {d["id"] for d in defs}
    assert "qa-engineer" in ids

    # Must be spawnable (exposes the real bug we would've hit at runtime).
    inst = registry.spawn("qa-engineer", project_id="proj-test-qa", task_id="t-qa")
    assert inst.agent_type == "qa-engineer"


def test_phased_producer_has_qa_playtest_step():
    """Both phased pipelines must include a qa-playtest step assigned to qa-engineer."""
    pipelines = client.get("/api/pipelines").json()
    for pid in ("phased-producer", "phased-producer-race"):
        pl = next(p for p in pipelines if p["id"] == pid)
        step_ids = {s["id"]: s for s in pl["steps"]}
        assert "qa-playtest" in step_ids, f"{pid} missing qa-playtest"
        assert step_ids["qa-playtest"].get("agent") == "qa-engineer"


# ==================== #6 Play button + game preview endpoint ====================


def test_game_preview_404_when_no_artifact():
    """#6: preview endpoint returns 404 for a project with no build."""
    project = client.post("/api/projects", json={
        "name": "No Build Project",
        "description": "",
        "tech_stack": "web",
    }).json()

    resp = client.get(f"/api/projects/{project['id']}/game/preview")
    assert resp.status_code == 404
    assert "no build" in resp.text.lower()


def test_game_preview_serves_default_artifact():
    """Writing game_html_v1 into memory should make preview serve that HTML."""
    from src.memory.project_memory import project_memory

    project = client.post("/api/projects", json={
        "name": "Preview Default Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]
    html = "<!doctype html><html><body><canvas></canvas><script>window.__game={};</script></body></html>"
    project_memory.write(pid, mem_type="artifact", key="game_html_v1",
                         content=html, created_by="test")

    resp = client.get(f"/api/projects/{pid}/game/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == html


def test_game_preview_honors_key_param_for_ab_builds():
    """The ?key= param lets the dashboard preview A and B builds side-by-side
    before the pick gate has been resolved."""
    from src.memory.project_memory import project_memory

    project = client.post("/api/projects", json={
        "name": "Preview AB Project",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]
    project_memory.write(pid, mem_type="artifact", key="game_html_v1@a",
                         content="<html>A BUILD</html>", created_by="test")
    project_memory.write(pid, mem_type="artifact", key="game_html_v1@b",
                         content="<html>B BUILD</html>", created_by="test")

    resp_a = client.get(f"/api/projects/{pid}/game/preview?key=game_html_v1@a")
    assert resp_a.status_code == 200
    assert resp_a.text == "<html>A BUILD</html>"

    resp_b = client.get(f"/api/projects/{pid}/game/preview?key=game_html_v1@b")
    assert resp_b.status_code == 200
    assert resp_b.text == "<html>B BUILD</html>"

    # No default artifact yet, so the key-less call 404s.
    resp_default = client.get(f"/api/projects/{pid}/game/preview")
    assert resp_default.status_code == 404


# ==================== #7 style-research step ====================


def test_style_research_step_and_agent_registered():
    """#7: both phased pipelines must include a style-research step that feeds
    look-and-feel, and the style-researcher agent must be defined."""
    # Agent definition exists and is spawnable
    defs = client.get("/api/agents/definitions").json()
    ids = {d["id"] for d in defs}
    assert "style-researcher" in ids

    inst = registry.spawn("style-researcher", project_id="proj-style-test", task_id="t-style")
    assert inst.agent_type == "style-researcher"

    # Present in both phased pipelines, before look-and-feel
    pipelines = client.get("/api/pipelines").json()
    for pid in ("phased-producer", "phased-producer-race"):
        pl = next(p for p in pipelines if p["id"] == pid)
        step_ids = [s["id"] for s in pl["steps"]]
        assert "style-research" in step_ids, f"{pid} missing style-research"
        assert "look-and-feel" in step_ids, f"{pid} missing look-and-feel"
        assert step_ids.index("style-research") < step_ids.index("look-and-feel")

        sr_step = next(s for s in pl["steps"] if s["id"] == "style-research")
        assert sr_step.get("agent") == "style-researcher"


def test_style_research_wired_into_task_graph():
    """Launching the pipeline must create a style-research task, and look-and-feel
    must depend on it so the brief consumes the research artifact."""
    from src.orchestrator.task_queue import task_queue

    project = client.post("/api/projects", json={
        "name": "Style Research Wiring",
        "description": "",
        "tech_stack": "web",
    }).json()

    launch = client.post("/api/pipelines/phased-producer/run", json={
        "project_id": project["id"],
        "input_text": "bullet-hell bunny garden",
    }).json()
    tasks_by_step = launch["tasks"]

    assert "style-research" in tasks_by_step
    assert "look-and-feel" in tasks_by_step

    sr_task = task_queue.get(tasks_by_step["style-research"])
    laf_task = task_queue.get(tasks_by_step["look-and-feel"])
    assert sr_task is not None
    assert laf_task is not None
    # look-and-feel depends on style-research
    assert sr_task.id in laf_task.depends_on


def test_style_research_agent_category_is_research():
    """style-researcher lives in the research category so the dashboard sidebar
    can group it correctly."""
    defs = client.get("/api/agents/definitions").json()
    sr = next(d for d in defs if d["id"] == "style-researcher")
    assert sr.get("category") == "research"


# ==================== #8 cleanup self-generated projects ====================


def test_delete_project_cascades_db_and_filesystem(tmp_path, monkeypatch):
    """DELETE /api/projects/{id} removes the project row, its tasks, messages,
    memory, and nukes projects/{id}/ on disk."""
    from src.settings import settings
    from src.memory.project_memory import project_memory
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    project = client.post("/api/projects", json={
        "name": "Delete Cascade",
        "description": "",
        "tech_stack": "web",
    }).json()
    pid = project["id"]

    # Create some cascade surface: a task, a message, a memory artifact, a file.
    client.post("/api/tasks", json={"project_id": pid, "title": "ghost task"})
    client.post("/api/messages", params={
        "project_id": pid, "channel": "general",
        "sender": "test", "content": "hi",
    })
    project_memory.write(pid, mem_type="artifact", key="k",
                         content="x", created_by="test")
    (tmp_path / pid / "assets").mkdir(parents=True, exist_ok=True)
    (tmp_path / pid / "assets" / "file.txt").write_text("keep me? no.")

    # Sanity: it exists.
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert (tmp_path / pid).is_dir()

    resp = client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "deleted"
    assert body["projects"] == 1
    assert body["tasks"] >= 1
    assert body["messages"] >= 1
    assert body["fs_removed"] is True

    # After delete: 404, no tasks, no directory.
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert not (tmp_path / pid).exists()


def test_delete_project_404s_on_missing():
    resp = client.delete("/api/projects/proj-does-not-exist-xyz")
    assert resp.status_code == 404


def test_cleanup_dry_run_does_not_delete(tmp_path, monkeypatch):
    """POST /api/projects/cleanup?dry_run=true reports candidates but keeps them."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    empty = client.post("/api/projects", json={
        "name": "dry run empty", "description": "", "tech_stack": "web",
    }).json()

    # A separate project with a task — should NOT be in candidates.
    kept = client.post("/api/projects", json={
        "name": "dry run kept", "description": "", "tech_stack": "web",
    }).json()
    client.post("/api/tasks", json={"project_id": kept["id"], "title": "keep me"})

    resp = client.post("/api/projects/cleanup?dry_run=true&only_empty=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    ids = {c["id"] for c in data["would_delete"]}
    assert empty["id"] in ids
    assert kept["id"] not in ids

    # Both projects still exist after dry run.
    assert client.get(f"/api/projects/{empty['id']}").status_code == 200
    assert client.get(f"/api/projects/{kept['id']}").status_code == 200


def test_cleanup_actual_sweep_deletes_empty_only(tmp_path, monkeypatch):
    """dry_run=false with only_empty=true deletes empty projects and leaves
    projects with tasks/memory untouched."""
    from src.settings import settings
    from src.memory.project_memory import project_memory
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    empty = client.post("/api/projects", json={
        "name": "sweep empty", "description": "", "tech_stack": "web",
    }).json()
    with_task = client.post("/api/projects", json={
        "name": "sweep with task", "description": "", "tech_stack": "web",
    }).json()
    client.post("/api/tasks", json={"project_id": with_task["id"], "title": "real work"})
    with_mem = client.post("/api/projects", json={
        "name": "sweep with memory", "description": "", "tech_stack": "web",
    }).json()
    project_memory.write(with_mem["id"], mem_type="artifact", key="game_html_v1",
                         content="<html/>", created_by="test")

    resp = client.post("/api/projects/cleanup?dry_run=false&only_empty=true")
    assert resp.status_code == 200
    deleted_ids = {d["project_id"] for d in resp.json()["deleted"]}

    assert empty["id"] in deleted_ids
    assert with_task["id"] not in deleted_ids
    assert with_mem["id"] not in deleted_ids

    assert client.get(f"/api/projects/{empty['id']}").status_code == 404
    assert client.get(f"/api/projects/{with_task['id']}").status_code == 200
    assert client.get(f"/api/projects/{with_mem['id']}").status_code == 200


def test_cleanup_respects_keep_ids(tmp_path, monkeypatch):
    """keep_ids=a,b protects explicit projects even if they'd otherwise sweep."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    keep = client.post("/api/projects", json={
        "name": "keep me", "description": "", "tech_stack": "web",
    }).json()
    sweep = client.post("/api/projects", json={
        "name": "sweep me", "description": "", "tech_stack": "web",
    }).json()

    resp = client.post(
        f"/api/projects/cleanup?dry_run=false&only_empty=true&keep_ids={keep['id']}"
    )
    assert resp.status_code == 200
    deleted_ids = {d["project_id"] for d in resp.json()["deleted"]}
    assert keep["id"] not in deleted_ids
    assert sweep["id"] in deleted_ids


def test_cleanup_older_than_days_filters(tmp_path, monkeypatch):
    """older_than_days=7 skips projects created in the last week."""
    from src.settings import settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    fresh = client.post("/api/projects", json={
        "name": "fresh", "description": "", "tech_stack": "web",
    }).json()

    # Fresh project was just created → older_than_days=30 should NOT sweep it.
    resp = client.post("/api/projects/cleanup?dry_run=true&only_empty=true&older_than_days=30")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()["would_delete"]}
    assert fresh["id"] not in ids
