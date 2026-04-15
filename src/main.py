"""Code PLAY — Multi-agent game studio platform.

FastAPI server with REST API, WebSocket feed, and agent orchestration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.settings import settings
from src.database import init_studio_db, init_project_db, get_studio_db
from src.models.projects import Project, ProjectCreate
from src.models.tasks import TaskCreate, TaskStatus
from src.models.agents import AgentStatus
from src.orchestrator.agent_registry import registry
from src.orchestrator.task_queue import task_queue
from src.runtime.llm_router import router
from src.runtime.tool_executor import tool_executor
from src.runtime.agent_runtime import agent_runtime
from src.communication.message_bus import message_bus
from src.memory.project_memory import project_memory

# --- Logging ---

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("code_play")


# --- WebSocket Manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WebSocket connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        logger.info(f"WebSocket disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: dict):
        """Broadcast JSON event to all connected dashboards."""
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


ws_manager = ConnectionManager()


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    # Init databases
    init_studio_db()
    logger.info("Studio database initialized")

    # Load agent definitions
    registry.load_config()
    registry.load_agents()
    agent_count = len(registry.list_definitions())
    logger.info(f"Loaded {agent_count} agent definitions")

    # Load governance config
    tool_executor.load_governance()
    logger.info("Governance config loaded")

    # Wire message bus to WebSocket
    message_bus.set_ws_broadcast(ws_manager.broadcast)

    logger.info(f"Code PLAY studio ready on {settings.host}:{settings.port}")
    yield

    # Shutdown
    await router.close()
    logger.info("Shutdown complete")


# --- FastAPI App ---

app = FastAPI(
    title="Code PLAY Studio",
    description="Multi-agent game studio platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== WebSocket ====================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; handle incoming commands from dashboard
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                await _handle_ws_command(msg)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


async def _handle_ws_command(msg: dict):
    """Handle commands from the dashboard via WebSocket."""
    cmd = msg.get("command")

    if cmd == "approve":
        request_id = msg.get("request_id")
        if request_id:
            tool_executor.resolve_approval(str(request_id), approved=True, decided_by="human")

    elif cmd == "deny":
        request_id = msg.get("request_id")
        if request_id:
            tool_executor.resolve_approval(str(request_id), approved=False, decided_by="human")

    elif cmd == "escalation_response":
        esc_id = msg.get("escalation_id")
        response = msg.get("response", "")
        if esc_id:
            message_bus.resolve_escalation(int(esc_id), response)


# ==================== Projects ====================

@app.post("/api/projects", response_model=Project)
async def create_project(body: ProjectCreate):
    project_id = f"proj-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    with get_studio_db() as db:
        db.execute(
            "INSERT INTO projects (id, name, description, tech_stack, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, body.name, body.description, body.tech_stack, now, now),
        )

    # Init project memory DB
    init_project_db(project_id)

    project = Project(
        id=project_id,
        name=body.name,
        description=body.description,
        tech_stack=body.tech_stack,
        status="active",
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
    )

    await ws_manager.broadcast({"type": "project_created", "data": project.model_dump(mode="json")})
    return project


@app.get("/api/projects")
async def list_projects():
    with get_studio_db() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    with get_studio_db() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


# ==================== Agents ====================

@app.get("/api/agents/definitions")
async def list_agent_definitions(category: str = None):
    defs = registry.list_definitions(category=category)
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "category": d.category,
            "emoji": d.emoji,
            "color": d.color,
            "default_model": d.default_model,
            "tools": d.tools,
        }
        for d in defs
    ]


@app.get("/api/agents/categories")
async def list_agent_categories():
    return registry.list_categories()


@app.get("/api/agents/instances")
async def list_agent_instances(project_id: str = None, status: str = None):
    agent_status = AgentStatus(status) if status else None
    instances = registry.list_instances(project_id=project_id, status=agent_status)
    return [
        {
            "id": i.id,
            "agent_type": i.agent_type,
            "project_id": i.project_id,
            "task_id": i.task_id,
            "status": i.status.value,
            "model": i.model,
            "provider": i.provider,
            "tokens_used": i.tokens_used,
            "cost_usd": i.cost_usd,
            "started_at": i.started_at.isoformat() if i.started_at else None,
            "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        }
        for i in instances
    ]


@app.post("/api/agents/spawn")
async def spawn_agent(
    agent_type: str,
    project_id: str = None,
    task_prompt: str = None,
    model_override: str = None,
):
    """Spawn an agent instance and optionally start it on a task."""
    try:
        instance = registry.spawn(
            agent_type=agent_type,
            project_id=project_id,
            model_override=model_override,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    await ws_manager.broadcast({
        "type": "agent_spawned",
        "data": {
            "id": instance.id,
            "agent_type": agent_type,
            "model": instance.model,
            "project_id": project_id,
        },
    })

    # If task_prompt provided, run the agent in background
    if task_prompt:
        asyncio.create_task(_run_agent_task(instance, task_prompt))

    return {
        "id": instance.id,
        "agent_type": instance.agent_type,
        "status": instance.status.value,
        "model": instance.model,
    }


@app.post("/api/agents/{instance_id}/terminate")
async def terminate_agent(instance_id: str):
    registry.terminate(instance_id)
    await ws_manager.broadcast({
        "type": "agent_terminated",
        "data": {"id": instance_id},
    })
    return {"status": "terminated"}


async def _run_agent_task(instance, task_prompt: str):
    """Background task: run agent to completion, broadcasting turns."""
    try:
        # Inject project memory context if available
        context_messages = []
        if instance.project_id:
            context_bundle = project_memory.get_context_bundle(instance.project_id)
            if context_bundle:
                context_messages.append({
                    "role": "user",
                    "content": f"[Project Context]\n{context_bundle}",
                })

        async for turn in agent_runtime.run(instance, task_prompt, context_messages):
            await ws_manager.broadcast({
                "type": "agent_turn",
                "data": {
                    "instance_id": instance.id,
                    "role": turn.role,
                    "content": turn.content,
                    "tool_calls": [
                        {"name": tc.name, "arguments": tc.arguments}
                        for tc in turn.tool_calls
                    ],
                    "tool_results": [
                        {"content": tr.content[:500], "is_error": tr.is_error}
                        for tr in turn.tool_results
                    ],
                    "timestamp": turn.timestamp.isoformat(),
                },
            })
    except Exception as e:
        logger.error(f"Agent {instance.id} failed: {e}")
        await ws_manager.broadcast({
            "type": "agent_error",
            "data": {"instance_id": instance.id, "error": str(e)},
        })


# ==================== Tasks ====================

@app.post("/api/tasks")
async def create_task(body: TaskCreate):
    task = task_queue.create(body)
    await ws_manager.broadcast({"type": "task_created", "data": task.model_dump(mode="json")})
    return task


@app.get("/api/tasks")
async def list_tasks(project_id: str = None, status: str = None):
    task_status = TaskStatus(status) if status else None
    tasks = task_queue.list_tasks(project_id=project_id, status=task_status)
    return [t.model_dump(mode="json") for t in tasks]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump(mode="json")


@app.post("/api/tasks/{task_id}/assign")
async def assign_task(task_id: str, agent_instance_id: str):
    task = task_queue.assign(task_id, agent_instance_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump(mode="json")


@app.get("/api/projects/{project_id}/tasks/ready")
async def get_ready_tasks(project_id: str):
    tasks = task_queue.get_ready_tasks(project_id)
    return [t.model_dump(mode="json") for t in tasks]


# ==================== Messages / Communication ====================

@app.post("/api/messages")
async def post_message(
    project_id: str,
    channel: str = "general",
    sender: str = "human",
    content: str = "",
    mentions: list[str] = None,
):
    msg = await message_bus.post(
        project_id=project_id,
        channel=channel,
        sender=sender,
        content=content,
        mentions=mentions or [],
    )
    return msg.model_dump(mode="json")


@app.get("/api/messages")
async def get_messages(project_id: str, channel: str = "general", limit: int = 50):
    messages = message_bus.get_messages(project_id, channel, limit)
    return [m.model_dump(mode="json") for m in messages]


@app.get("/api/messages/channels")
async def list_channels(project_id: str):
    return message_bus.list_channels(project_id)


# ==================== Governance ====================

@app.get("/api/governance/approvals")
async def list_approvals():
    return tool_executor.list_pending_approvals()


@app.post("/api/governance/approvals/{request_id}/approve")
async def approve_tool(request_id: str):
    tool_executor.resolve_approval(request_id, approved=True, decided_by="human")
    return {"status": "approved"}


@app.post("/api/governance/approvals/{request_id}/deny")
async def deny_tool(request_id: str):
    tool_executor.resolve_approval(request_id, approved=False, decided_by="human")
    return {"status": "denied"}


@app.get("/api/governance/log")
async def governance_log(limit: int = 50):
    with get_studio_db() as db:
        rows = db.execute(
            "SELECT * FROM governance_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ==================== Memory ====================

@app.get("/api/projects/{project_id}/memory")
async def read_memory(project_id: str, mem_type: str, key: str):
    content = project_memory.read(project_id, mem_type, key)
    if content is None:
        raise HTTPException(404, "Memory entry not found")
    return {"type": mem_type, "key": key, "content": content}


@app.post("/api/projects/{project_id}/memory")
async def write_memory(project_id: str, mem_type: str, key: str, content: str, created_by: str = "human"):
    row_id = project_memory.write(project_id, mem_type, key, content, created_by)
    return {"id": row_id, "type": mem_type, "key": key}


@app.get("/api/projects/{project_id}/memory/search")
async def search_memory(project_id: str, query: str, mem_type: str = None):
    results = project_memory.search(project_id, query, mem_type)
    return results


# ==================== Pipelines ====================

@app.post("/api/pipelines/{pipeline_name}/run")
async def run_pipeline(pipeline_name: str, project_id: str, input_text: str = ""):
    """Launch a predefined pipeline for a project."""
    # Load pipeline definition
    pipelines_path = f"{settings.config_dir}/pipelines.yaml"
    try:
        with open(pipelines_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise HTTPException(404, "Pipelines config not found")

    pipeline = data.get("pipelines", {}).get(pipeline_name)
    if not pipeline:
        raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")

    # Create tasks for each step
    created_tasks = {}
    for step in pipeline["steps"]:
        step_id = step["id"]
        task_desc = step["task"].replace("{input}", input_text)

        # Resolve dependencies to task IDs
        deps = []
        for dep_name in step.get("depends_on", []):
            if dep_name in created_tasks:
                deps.append(created_tasks[dep_name])

        task = task_queue.create(TaskCreate(
            project_id=project_id,
            title=f"[{pipeline_name}] {step_id}",
            description=task_desc,
            depends_on=deps,
            created_by=f"pipeline:{pipeline_name}",
        ))
        created_tasks[step_id] = task.id

        # If no dependencies, spawn agent immediately
        if not deps and step.get("type") != "human-gate":
            agent_type = step.get("agent")
            if agent_type:
                try:
                    instance = registry.spawn(
                        agent_type=agent_type,
                        project_id=project_id,
                        task_id=task.id,
                    )
                    task_queue.assign(task.id, instance.id)
                    asyncio.create_task(_run_agent_task(instance, task_desc))
                except ValueError:
                    logger.warning(f"Agent type '{agent_type}' not found, skipping")

    await ws_manager.broadcast({
        "type": "pipeline_started",
        "data": {
            "pipeline": pipeline_name,
            "project_id": project_id,
            "tasks": created_tasks,
        },
    })

    return {
        "pipeline": pipeline_name,
        "project_id": project_id,
        "tasks": created_tasks,
    }


# ==================== Health ====================

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "agents_loaded": len(registry.list_definitions()),
        "llm_providers": router.get_health(),
        "active_agents": len(registry.list_instances(status=AgentStatus.RUNNING)),
    }


@app.get("/api/health/providers")
async def provider_health():
    return router.get_health()


# ==================== Dashboard Stats ====================

@app.get("/api/stats")
async def get_stats():
    with get_studio_db() as db:
        project_count = db.execute("SELECT COUNT(*) as c FROM projects").fetchone()["c"]
        task_count = db.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
        tasks_completed = db.execute(
            "SELECT COUNT(*) as c FROM tasks WHERE status = 'completed'"
        ).fetchone()["c"]
        message_count = db.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
        total_cost = db.execute("SELECT COALESCE(SUM(cost_usd), 0) as c FROM cost_log").fetchone()["c"]

    return {
        "projects": project_count,
        "tasks": {"total": task_count, "completed": tasks_completed},
        "messages": message_count,
        "agents": {
            "definitions": len(registry.list_definitions()),
            "running": len(registry.list_instances(status=AgentStatus.RUNNING)),
        },
        "cost_usd": round(total_cost, 4),
    }
