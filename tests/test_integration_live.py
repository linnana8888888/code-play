"""Live integration tests against the running Code PLAY service.

Requires the service to be running at CODE_PLAY_URL (default: http://localhost:8081).
Run with:
    CODE_PLAY_URL=http://localhost:8081 python3 -m pytest tests/test_integration_live.py -v

These tests exercise the real HTTP stack (not FastAPI TestClient) and verify
Phase 1 features are wired end-to-end.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("CODE_PLAY_URL", "http://localhost:8081")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(path: str) -> str:
    return f"{BASE_URL}{path}"


def skip_if_unreachable():
    """Skip the whole module if the service isn't up."""
    try:
        r = requests.get(api("/api/health"), timeout=5)
        r.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Code PLAY service not reachable at {BASE_URL}: {exc}")


# Run reachability check at collection time so individual tests don't need it.
skip_if_unreachable()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_project():
    """Create a project for the integration test module, delete it after."""
    r = requests.post(api("/api/projects"), json={
        "name": "Live Integration Test Project",
        "description": "Created by test_integration_live.py",
        "tech_stack": "web",
        "pipeline": None,  # no auto-launch
        "require_roster_approval": False,
    })
    assert r.status_code == 200, f"Failed to create project: {r.text}"
    project = r.json()
    yield project
    # Cleanup
    requests.delete(api(f"/api/projects/{project['id']}"))


# ---------------------------------------------------------------------------
# Health & basic connectivity
# ---------------------------------------------------------------------------

def test_live_health():
    """Service is up and reports ok."""
    r = requests.get(api("/api/health"), timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data.get("agents_loaded", 0) >= 20, "Expected at least 20 agents loaded"


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def test_live_create_project(live_project):
    """Project was created with expected fields."""
    p = live_project
    assert p["id"].startswith("proj-")
    assert p["name"] == "Live Integration Test Project"
    assert p["status"] == "active"


def test_live_list_projects(live_project):
    """Project list includes the test project."""
    r = requests.get(api("/api/projects"), timeout=10)
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert live_project["id"] in ids


def test_live_get_project(live_project):
    """Individual project GET returns correct data."""
    pid = live_project["id"]
    r = requests.get(api(f"/api/projects/{pid}"), timeout=10)
    assert r.status_code == 200
    assert r.json()["id"] == pid


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def test_live_agent_roster():
    """Agent definitions endpoint returns a populated roster."""
    r = requests.get(api("/api/agents/definitions"), timeout=10)
    assert r.status_code == 200
    defs = r.json()
    assert len(defs) >= 20
    ids = {d["id"] for d in defs}
    # Core agents expected in Phase 1
    assert "game-designer" in ids
    assert "creative-director" in ids
    assert "frontend-developer" in ids
    assert "qa-engineer" in ids


def test_live_kid_safety_reviewer_in_roster():
    """Phase 1 requirement: kid-safety-reviewer agent is registered."""
    r = requests.get(api("/api/agents/definitions"), timeout=10)
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert "kid-safety-reviewer" in ids, (
        "kid-safety-reviewer agent is missing from the roster — Phase 1 requirement"
    )


def test_live_style_researcher_in_roster():
    """Phase 1 requirement: style-researcher agent is registered."""
    r = requests.get(api("/api/agents/definitions"), timeout=10)
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert "style-researcher" in ids, (
        "style-researcher agent is missing from the roster — Phase 1 requirement"
    )


def test_live_tech_lead_in_roster():
    """Phase 1 requirement: tech-lead agent is registered."""
    r = requests.get(api("/api/agents/definitions"), timeout=10)
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert "tech-lead" in ids, (
        "tech-lead agent is missing from the roster — Phase 1 requirement"
    )


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def test_live_pipeline_list():
    """Pipelines endpoint returns registered pipelines."""
    r = requests.get(api("/api/pipelines"), timeout=10)
    assert r.status_code == 200
    pipelines = r.json()
    assert len(pipelines) >= 1
    ids = {p["id"] for p in pipelines}
    assert "phased-producer" in ids


def test_live_phased_producer_has_phase1_steps():
    """Phase 1 pipeline steps are present in phased-producer."""
    r = requests.get(api("/api/pipelines"), timeout=10)
    assert r.status_code == 200
    pp = next(p for p in r.json() if p["id"] == "phased-producer")
    step_ids = {s["id"] for s in pp["steps"]}

    # Phase 1 additions
    assert "kid-safety-laf" in step_ids or any(
        "kid" in sid for sid in step_ids
    ), f"No kid-safety step found in phased-producer steps: {step_ids}"
    assert "style-research" in step_ids, f"style-research step missing: {step_ids}"
    assert "tech-plan" in step_ids, f"tech-plan step missing: {step_ids}"
    assert "qa-playtest" in step_ids, f"qa-playtest step missing: {step_ids}"


def test_live_phased_producer_gate_steps():
    """phased-producer has exactly 6 human-gate steps."""
    r = requests.get(api("/api/pipelines"), timeout=10)
    assert r.status_code == 200
    pp = next(p for p in r.json() if p["id"] == "phased-producer")
    gate_steps = [s for s in pp["steps"] if s.get("type") == "human-gate"]
    gate_ids = {s["id"] for s in gate_steps}
    assert gate_ids == {
        "gate-concept", "gate-mechanics", "gate-laf", "gate-tech", "gate-qa", "gate-publish"
    }, f"Unexpected gate steps: {gate_ids}"


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------

def test_live_governance_config():
    """Governance endpoint is reachable."""
    r = requests.get(api("/api/governance/log"), timeout=10)
    assert r.status_code == 200


def test_live_governance_approvals():
    """Governance approvals endpoint is reachable."""
    r = requests.get(api("/api/governance/approvals"), timeout=10)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def test_live_create_task(live_project):
    """Create a task and verify it appears in the task list."""
    pid = live_project["id"]
    r = requests.post(api("/api/tasks"), json={
        "project_id": pid,
        "title": "Live integration test task",
        "description": "Verify task creation works end-to-end",
        "priority": 5,
    }, timeout=10)
    assert r.status_code == 200, f"Task creation failed: {r.text}"
    task = r.json()
    assert task["title"] == "Live integration test task"
    assert task["status"] == "pending"
    assert task["id"].startswith("task-")

    # Verify it shows up in the list
    list_r = requests.get(api(f"/api/tasks?project_id={pid}"), timeout=10)
    assert list_r.status_code == 200
    task_ids = {t["id"] for t in list_r.json()}
    assert task["id"] in task_ids


def test_live_task_status_check(live_project):
    """Create a task and check its status via GET /api/tasks/{id}."""
    pid = live_project["id"]

    # Create task
    create_r = requests.post(api("/api/tasks"), json={
        "project_id": pid,
        "title": "Status check task",
        "description": "For status verification",
    }, timeout=10)
    assert create_r.status_code == 200
    task_id = create_r.json()["id"]

    # Fetch by ID
    r = requests.get(api(f"/api/tasks/{task_id}"), timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == task_id
    assert data["project_id"] == pid
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# Phase 1 pipeline wiring (via live pipeline run on a non-gated project)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipeline_project():
    """Create a clean project, run phased-producer, yield the launch result."""
    r = requests.post(api("/api/projects"), json={
        "name": "Pipeline Wiring Test",
        "description": "Phase 1 pipeline wiring verification",
        "tech_stack": "web",
        "pipeline": None,
        "require_roster_approval": False,
    })
    assert r.status_code == 200
    project = r.json()
    pid = project["id"]

    launch_r = requests.post(api(f"/api/pipelines/phased-producer/run"), json={
        "project_id": pid,
        "input_text": "a simple test game for integration tests",
    }, timeout=30)
    assert launch_r.status_code == 200, f"Pipeline launch failed: {launch_r.text}"
    launch = launch_r.json()

    yield {"project": project, "launch": launch}

    # Cleanup
    requests.delete(api(f"/api/projects/{pid}"))


def test_live_pipeline_launch_returns_tasks(pipeline_project):
    """Pipeline run returns a tasks dict with expected step keys."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert tasks, "Pipeline launch returned no tasks"
    assert "concept" in tasks
    assert "gate-concept" in tasks


def test_live_phase1_style_research_task_created(pipeline_project):
    """Phase 1: style-research task is created when pipeline runs."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert "style-research" in tasks, (
        f"style-research task not in pipeline tasks: {list(tasks.keys())}"
    )


def test_live_phase1_tech_plan_task_created(pipeline_project):
    """Phase 1: tech-plan task is created when pipeline runs."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert "tech-plan" in tasks, (
        f"tech-plan task not in pipeline tasks: {list(tasks.keys())}"
    )


def test_live_phase1_qa_playtest_task_created(pipeline_project):
    """Phase 1: qa-playtest task is created when pipeline runs."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert "qa-playtest" in tasks, (
        f"qa-playtest task not in pipeline tasks: {list(tasks.keys())}"
    )


def test_live_phase1_kid_safety_tasks_created(pipeline_project):
    """Phase 1: at least one kid-safety task is created when pipeline runs."""
    tasks = pipeline_project["launch"].get("tasks", {})
    kid_safety_tasks = [k for k in tasks if "kid" in k]
    assert kid_safety_tasks, (
        f"No kid-safety tasks found in pipeline tasks: {list(tasks.keys())}"
    )


def test_live_phase1_gate_tasks_created(pipeline_project):
    """Phase 1: all 6 gate tasks are created at launch."""
    tasks = pipeline_project["launch"].get("tasks", {})
    expected_gates = {
        "gate-concept", "gate-mechanics", "gate-laf",
        "gate-tech", "gate-qa", "gate-publish",
    }
    missing = expected_gates - set(tasks.keys())
    assert not missing, f"Missing gate tasks: {missing}"


def test_live_phase1_gate_task_status(pipeline_project):
    """Phase 1: gate tasks start as pending (not ready until upstream completes)."""
    pid = pipeline_project["project"]["id"]
    r = requests.get(api(f"/api/projects/{pid}/gates"), timeout=10)
    assert r.status_code == 200
    gates = r.json()
    assert gates, "No gates returned for the project"
    # All gates should start as not-ready
    assert all(not g["ready"] for g in gates), (
        "Some gates are already ready before any upstream task completed"
    )


def test_live_phase1_style_research_before_laf(pipeline_project):
    """Phase 1: style-research task depends on concept (comes before look-and-feel)."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert "style-research" in tasks
    assert "look-and-feel" in tasks

    pid = pipeline_project["project"]["id"]
    sr_id = tasks["style-research"]
    laf_id = tasks["look-and-feel"]

    laf_r = requests.get(api(f"/api/tasks/{laf_id}"), timeout=10)
    assert laf_r.status_code == 200
    laf_task = laf_r.json()

    # look-and-feel must depend on style-research
    assert sr_id in laf_task.get("depends_on", []), (
        f"look-and-feel task does not depend on style-research. "
        f"depends_on={laf_task.get('depends_on')}"
    )


def test_live_phase1_tech_plan_before_gate_tech(pipeline_project):
    """Phase 1: gate-tech depends on tech-plan."""
    tasks = pipeline_project["launch"].get("tasks", {})
    assert "tech-plan" in tasks
    assert "gate-tech" in tasks

    pid = pipeline_project["project"]["id"]
    gate_tech_id = tasks["gate-tech"]
    tech_plan_id = tasks["tech-plan"]

    gt_r = requests.get(api(f"/api/tasks/{gate_tech_id}"), timeout=10)
    assert gt_r.status_code == 200
    gate_tech_task = gt_r.json()

    assert tech_plan_id in gate_tech_task.get("depends_on", []), (
        f"gate-tech does not depend on tech-plan. "
        f"depends_on={gate_tech_task.get('depends_on')}"
    )
