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


@pytest.fixture(scope="module", autouse=True)
def setup():
    """Initialize DB and load agents before tests."""
    init_studio_db()
    registry.load_config()
    registry.load_agents()
    tool_executor.load_governance()


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


def test_ready_tasks():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]

    resp = client.get(f"/api/projects/{project_id}/tasks/ready")
    assert resp.status_code == 200
