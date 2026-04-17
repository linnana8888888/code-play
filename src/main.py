"""Code PLAY — Multi-agent game studio platform.

FastAPI server with REST API, WebSocket feed, and agent orchestration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import yaml
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.settings import settings
from src.database import init_studio_db, init_project_db, get_studio_db
from src.models.projects import Project, ProjectCreate
from src.models.tasks import TaskCreate, TaskStatus, TaskUpdate
from src.models.agents import AgentStatus
from src.orchestrator.agent_registry import registry
from src.orchestrator.task_queue import task_queue
from src.runtime.llm_router import router
from src.runtime.tool_executor import tool_executor
from src.runtime.agent_runtime import agent_runtime
from src.runtime.session_store import session_store
from src.runtime.skill_registry import skill_registry
from src.runtime.claude_bridge import discover as discover_claude_plugins
from src.runtime.mcp_bridge import mcp_bridge
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

    # Ensure session store table exists
    session_store.ensure_table()

    # Load skills
    skill_registry.load_skills()
    skill_registry.load_governance()

    # Bridge Claude Code plugin surface: MCP servers + plugin/user skills.
    # Any MCP server or skill the user already enabled in Claude Code becomes
    # available to Code PLAY agents. Network calls to MCP servers happen
    # lazily on first use, but we list their tools upfront.
    try:
        disc = discover_claude_plugins()
        mcp_bridge.register_servers(disc.mcp_servers)
        added_skills = skill_registry.load_claude_plugin_skills(disc.skills)
        logger.info(
            "Claude plugin surface: %d enabled plugins, %d MCP servers, +%d skills",
            len(disc.enabled_plugins), len(disc.mcp_servers), added_skills,
        )
        # Discover tools in background so startup stays fast even with 40+ MCPs.
        asyncio.create_task(mcp_bridge.discover_tools())
    except Exception as exc:
        logger.warning("Claude plugin bridge failed: %s", exc)

    skill_count = len(skill_registry.list_skills())
    logger.info(f"Loaded {skill_count} skills")

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

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or f"game-{uuid.uuid4().hex[:6]}"


def _create_github_repo(name: str, description: str) -> tuple[str | None, str | None]:
    """Create a private GitHub repo under the authed user. Returns (repo_url, repo_name) or (None, None)."""
    if not shutil.which("gh"):
        logger.warning("gh CLI not available; skipping repo creation")
        return None, None
    slug = _slugify(name)
    desc = (description or "").replace("\n", " ")[:300]
    try:
        result = subprocess.run(
            ["gh", "repo", "create", slug, "--private", "--description", desc or "Published by Code PLAY studio"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("gh repo create failed: %s", result.stderr.strip())
            return None, None
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else f"https://github.com/linnana8888888/{slug}"
        return url, slug
    except Exception as exc:
        logger.warning("gh repo create exception: %s", exc)
        return None, None


@app.post("/api/projects", response_model=Project)
async def create_project(body: ProjectCreate):
    project_id = f"proj-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    repo_url, repo_name = (None, None)
    if body.create_repo:
        repo_url, repo_name = await asyncio.to_thread(_create_github_repo, body.name, body.description)

    with get_studio_db() as db:
        db.execute(
            "INSERT INTO projects (id, name, description, goal, tech_stack, repo_url, repo_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, body.name, body.description, body.goal, body.tech_stack, repo_url, repo_name, now, now),
        )

    # Init project memory DB
    init_project_db(project_id)

    project = Project(
        id=project_id,
        name=body.name,
        description=body.description,
        goal=body.goal,
        tech_stack=body.tech_stack,
        status="active",
        repo_url=repo_url,
        repo_name=repo_name,
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


# Approved model set (mirrors header of config/agents.yaml).
# Cost figures are approximate per-1M input/output tokens (USD); 0 = free/local.
_AVAILABLE_MODELS: list[dict] = [
    {"id": "omlx/Qwen3.5-9B-MLX-4bit",                              "label": "Qwen3.5 9B (local)",       "provider": "omlx",       "input_per_1m": 0.0,  "output_per_1m": 0.0,  "notes": "Free local baseline"},
    {"id": "anthropic/anthropic.claude-haiku-4-5-20251001-v1:0",    "label": "Claude Haiku 4.5",         "provider": "anthropic",  "input_per_1m": 1.0,  "output_per_1m": 5.0,  "notes": "Cheap, fast"},
    {"id": "anthropic/anthropic.claude-sonnet-4-6",                 "label": "Claude Sonnet 4.6",        "provider": "anthropic",  "input_per_1m": 3.0,  "output_per_1m": 15.0, "notes": "Balanced default"},
    {"id": "anthropic/anthropic.claude-opus-4-7",                   "label": "Claude Opus 4.7",          "provider": "anthropic",  "input_per_1m": 15.0, "output_per_1m": 75.0, "notes": "Reasoning, $$$"},
    {"id": "openai/gpt-5-2025-08-07",                               "label": "GPT-5",                    "provider": "openai",     "input_per_1m": 5.0,  "output_per_1m": 15.0, "notes": "Reasoning, via LEGO proxy"},
    {"id": "openrouter/openrouter/elephant-alpha",                  "label": "Elephant Alpha (stealth)", "provider": "openrouter", "input_per_1m": 0.0,  "output_per_1m": 0.0,  "notes": "Cloaked free-tier"},
]


@app.get("/api/models/available")
async def list_available_models():
    return _AVAILABLE_MODELS


def _instance_dict(i):
    return {
        "id": i.id,
        "agent_type": i.agent_type,
        "project_id": i.project_id,
        "task_id": i.task_id,
        "status": i.status.value,
        "model": i.model,
        "provider": i.provider,
        "tokens_used": i.tokens_used,
        "cost_usd": i.cost_usd,
        "budget_max_tokens": i.budget_max_tokens,
        "budget_max_usd": i.budget_max_usd,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "created_at": i.started_at.isoformat() if i.started_at else None,
    }


@app.get("/api/agents/instances")
async def list_agent_instances(project_id: str = None, status: str = None):
    agent_status = AgentStatus(status) if status else None
    instances = registry.list_instances(project_id=project_id, status=agent_status)
    return [_instance_dict(i) for i in instances]


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

    return _instance_dict(instance)


@app.post("/api/agents/{instance_id}/terminate")
async def terminate_agent(instance_id: str):
    registry.terminate(instance_id)
    await ws_manager.broadcast({
        "type": "agent_terminated",
        "data": {"id": instance_id},
    })
    return {"status": "terminated"}


@app.post("/api/agents/{instance_id}/resume")
async def resume_agent(instance_id: str, task_prompt: str, session_id: str = None):
    """Resume an agent from a saved session."""
    instance = registry.get_instance(instance_id)
    if not instance:
        raise HTTPException(404, "Agent instance not found")

    # Find latest session if not specified
    if not session_id:
        sessions = session_store.list_sessions(instance_id=instance_id)
        if not sessions:
            raise HTTPException(404, "No saved sessions for this agent")
        session_id = sessions[0]["id"]

    # Re-run with session
    asyncio.create_task(_run_agent_task(instance, task_prompt, session_id=session_id))

    return {"instance_id": instance_id, "session_id": session_id, "status": "resuming"}


@app.get("/api/agents/{instance_id}/cost")
async def get_agent_cost(instance_id: str):
    """Get per-agent cost breakdown from cost_log."""
    instance = registry.get_instance(instance_id)
    if not instance:
        raise HTTPException(404, "Agent instance not found")

    with get_studio_db() as db:
        rows = db.execute(
            """SELECT provider, model, SUM(input_tokens) as input_tokens,
                      SUM(output_tokens) as output_tokens, SUM(cost_usd) as cost_usd,
                      COUNT(*) as calls
               FROM cost_log WHERE agent_instance_id = ? GROUP BY provider, model""",
            (instance_id,),
        ).fetchall()

    return {
        "instance_id": instance_id,
        "agent_type": instance.agent_type,
        "status": instance.status.value,
        "tokens_used": instance.tokens_used,
        "cost_usd": instance.cost_usd,
        "budget_max_tokens": instance.budget_max_tokens,
        "budget_max_usd": instance.budget_max_usd,
        "breakdown": [dict(r) for r in rows],
    }


async def _run_agent_task(instance, task_prompt: str, session_id: str = None):
    """Background task: run agent to completion, broadcasting turns."""
    final_content = ""
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

        async for turn in agent_runtime.run(instance, task_prompt, context_messages, session_id):
            if turn.role == "assistant" and turn.content:
                final_content = turn.content
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

        # Rescue: if the model emitted HTML inline but never called memory_write,
        # capture it to project memory so the pipeline can still advance.
        if instance.project_id and final_content and "<!DOCTYPE html>" in final_content:
            try:
                start = final_content.find("<!DOCTYPE html>")
                end_html = final_content.find("</html>", start)
                if end_html > 0:
                    html_blob = final_content[start:end_html + len("</html>")]
                    project_memory.write(
                        instance.project_id,
                        mem_type="artifact",
                        key="game_html_v1",
                        content=html_blob,
                        created_by=instance.id,
                    )
                    logger.info(f"Rescued HTML ({len(html_blob)} chars) to memory for {instance.project_id}")
            except Exception as exc:
                logger.warning(f"Failed to rescue HTML: {exc}")

        # Mark the task completed and try to advance the pipeline
        if instance.task_id:
            try:
                task_queue.update_status(
                    instance.task_id,
                    TaskStatus.COMPLETED,
                    result={"summary": final_content[:20000], "agent_instance_id": instance.id},
                )
                await ws_manager.broadcast({
                    "type": "task_completed",
                    "data": {"task_id": instance.task_id, "instance_id": instance.id},
                })
            except Exception as exc:
                logger.warning(f"Failed to mark task {instance.task_id} completed: {exc}")
        if instance.project_id:
            await _advance_pipeline(instance.project_id)
    except Exception as e:
        logger.error(f"Agent {instance.id} failed: {e}")
        if instance.task_id:
            try:
                task_queue.update_status(instance.task_id, TaskStatus.BLOCKED, result={"error": str(e)})
            except Exception:
                pass
        await ws_manager.broadcast({
            "type": "agent_error",
            "data": {"instance_id": instance.id, "error": str(e)},
        })


async def _advance_pipeline(project_id: str):
    """Spawn agents for any newly-ready pipeline tasks."""
    try:
        ready = task_queue.get_ready_tasks(project_id)
    except Exception as exc:
        logger.warning(f"get_ready_tasks failed: {exc}")
        return

    if not ready:
        return

    pipeline_specs = _load_pipelines_yaml().get("pipelines", {}) or {}

    for task in ready:
        if task.assigned_to:
            continue

        agent_type: str | None = None
        created_by = task.created_by or ""
        step = None
        pipeline_name = None

        if created_by.startswith("pipeline:"):
            pipeline_name = created_by.split(":", 1)[1]
            pipeline = pipeline_specs.get(pipeline_name)
            if not pipeline:
                continue

            step_id = task.title.replace(f"[{pipeline_name}] ", "").strip()
            step = next((s for s in pipeline.get("steps", []) if s.get("id") == step_id), None)
            if not step:
                continue
            if step.get("type") == "human-gate":
                # Surface the gate in the UI banner — the dashboard watches
                # for this event and raises a toast/CTA that opens GatesPanel.
                await ws_manager.broadcast({
                    "type": "gate_ready",
                    "data": {
                        "task_id": task.id,
                        "project_id": project_id,
                        "pipeline": pipeline_name,
                        "step_id": step_id,
                        "review_of": step.get("review_of"),
                        "title": task.title,
                    },
                })
                continue
            agent_type = step.get("agent")
        elif task.assignee_type:
            # Human- or agent-created task with an explicit agent-type hint
            agent_type = task.assignee_type

        if not agent_type:
            continue

        try:
            instance = registry.spawn(
                agent_type=agent_type,
                project_id=project_id,
                task_id=task.id,
                model_override=task.model_override,
            )
            task_queue.checkout(task.id, instance.id)
            asyncio.create_task(_run_agent_task(instance, task.description))
            logger.info(f"Advanced pipeline: spawned {agent_type} for task {task.id}")
        except ValueError as exc:
            logger.warning(f"Failed to spawn {agent_type} for task {task.id}: {exc}")


# ==================== Tasks ====================

@app.post("/api/pipelines/advance")
async def advance_pipeline_endpoint(project_id: str):
    """Manually trigger pipeline advancement for a project."""
    await _advance_pipeline(project_id)
    return {"status": "ok", "project_id": project_id}


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


@app.patch("/api/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskUpdate):
    task = task_queue.update(task_id, body)
    if not task:
        raise HTTPException(404, "Task not found")
    await ws_manager.broadcast({"type": "task_updated", "data": task.model_dump(mode="json")})
    return task.model_dump(mode="json")


@app.post("/api/tasks/{task_id}/assign")
async def assign_task(task_id: str, agent_instance_id: str):
    # Deprecated: this endpoint only flipped the DB row without booting a
    # runtime, which left tasks permanently orphaned. Use `/api/agents/spawn`
    # (with a task_prompt) or set `assignee_type` on task_create so
    # `_advance_pipeline` picks it up.
    raise HTTPException(
        410,
        "POST /api/tasks/{id}/assign is deprecated. Use /api/agents/spawn "
        "with a task_prompt, or create the task with assignee_type set so "
        "the pipeline advances it automatically.",
    )


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


@app.get("/api/governance/tools")
async def governance_tools():
    """Tool catalog: every known tool, its tier, and which agents hold it."""
    catalog = tool_executor.list_tool_catalog()
    # Map tool -> [agent_ids] so the UI can show who can invoke each.
    agents_by_tool: dict[str, list[str]] = {}
    for defn in registry.list_definitions():
        for tool in (defn.tools or []):
            agents_by_tool.setdefault(tool, []).append(defn.id)
    for entry in catalog:
        entry["agents"] = sorted(agents_by_tool.get(entry["name"], []))
    return catalog


# ==================== Skills ====================

@app.get("/api/skills")
async def list_skills():
    skills = skill_registry.list_skills()
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "is_builtin": skill_registry.is_builtin(s.id),
        }
        for s in skills
    ]


@app.get("/api/skills/{skill_id}")
async def get_skill(skill_id: str):
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "content": skill.content,
        "is_builtin": skill_registry.is_builtin(skill.id),
    }


@app.post("/api/skills/{skill_id}/approve")
async def approve_skill(skill_id: str, agent_type: str):
    """Approve an agent type to use a skill."""
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    skill_registry.approve(skill_id, agent_type, approved_by="human")
    return {"skill_id": skill_id, "agent_type": agent_type, "status": "approved"}


@app.post("/api/skills/{skill_id}/deny")
async def deny_skill(skill_id: str, agent_type: str):
    """Revoke an agent type's access to a skill."""
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    skill_registry.deny(skill_id, agent_type)
    return {"skill_id": skill_id, "agent_type": agent_type, "status": "denied"}


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

def _load_pipelines_yaml():
    pipelines_path = f"{settings.config_dir}/pipelines.yaml"
    try:
        with open(pipelines_path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


@app.get("/api/pipelines")
async def list_pipelines():
    data = _load_pipelines_yaml()
    pipelines = data.get("pipelines", {}) or {}
    return [
        {
            "id": key,
            "name": p.get("name", key),
            "description": p.get("description", ""),
            "steps": [
                {"id": s.get("id"), "agent": s.get("agent"), "type": s.get("type", "agent")}
                for s in p.get("steps", [])
            ],
        }
        for key, p in pipelines.items()
    ]


class PipelineRunBody(BaseModel):
    project_id: str
    input_text: str = ""


@app.post("/api/pipelines/{pipeline_name}/run")
async def run_pipeline(pipeline_name: str, body: PipelineRunBody):
    """Launch a predefined pipeline for a project."""
    project_id = body.project_id
    input_text = body.input_text
    data = _load_pipelines_yaml()
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
                        model_override=task.model_override,
                    )
                    task_queue.checkout(task.id, instance.id)
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


# ==================== Human gates ====================

def _gate_context(task) -> dict:
    """Look up the pipeline spec for a gate task and pull in the preceding step's result."""
    created_by = task.created_by or ""
    if not created_by.startswith("pipeline:"):
        return {}
    pipeline_name = created_by.split(":", 1)[1]
    pipeline = _load_pipelines_yaml().get("pipelines", {}).get(pipeline_name)
    if not pipeline:
        return {}
    step_id = task.title.replace(f"[{pipeline_name}] ", "").strip()
    step = next((s for s in pipeline.get("steps", []) if s.get("id") == step_id), None)
    if not step or step.get("type") != "human-gate":
        return {}

    review_of = step.get("review_of")
    preceding_result = None
    preceding_agent = None
    if review_of:
        # Find the most recent sibling task for the review_of step in the same pipeline run
        siblings = task_queue.list_tasks(project_id=task.project_id)
        target_title = f"[{pipeline_name}] {review_of}"
        candidates = [t for t in siblings if t.title == target_title]
        if candidates:
            # Pick the latest one (iteration revisions get newer timestamps)
            candidates.sort(key=lambda t: t.updated_at or t.created_at or "", reverse=True)
            top = candidates[0]
            preceding_result = top.result
            review_step = next((s for s in pipeline.get("steps", []) if s.get("id") == review_of), None)
            if review_step:
                preceding_agent = review_step.get("agent")
    return {
        "pipeline": pipeline_name,
        "pipeline_label": pipeline.get("name", pipeline_name),
        "step_id": step_id,
        "review_of": review_of,
        "review_of_agent": preceding_agent,
        "prompt": step.get("task", ""),
        "preceding_result": preceding_result,
    }


@app.get("/api/projects/{project_id}/gates")
async def list_project_gates(project_id: str):
    """List pending human-gate tasks for a project, with the artifacts they're meant to review."""
    tasks = task_queue.list_tasks(project_id=project_id)
    pending_gates = []
    for t in tasks:
        if t.status != TaskStatus.PENDING:
            continue
        ctx = _gate_context(t)
        if not ctx:
            continue
        # Only surface once dependencies have actually resolved — otherwise the
        # gate is upstream of in-flight work and has nothing to show yet.
        ready = not t.depends_on or all(
            (dep := task_queue.get(dep_id)) and dep.status == TaskStatus.COMPLETED
            for dep_id in t.depends_on
        )
        pending_gates.append({
            "task_id": t.id,
            "title": t.title,
            "ready": ready,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            **ctx,
        })
    return pending_gates


class GateDecisionBody(BaseModel):
    feedback: str = ""


def _promote_pick(task, feedback: str) -> str | None:
    """If this is an A/B build pick gate, promote the chosen artifact.

    Looks for a `winner: a` or `winner: b` hint in the feedback (case-insensitive,
    also accepts standalone 'a'/'b'), reads `game_html_v1@<winner>` from project
    memory, and rewrites it as `game_html_v1` so downstream QA consumes the pick.
    Returns the winner letter on success, None otherwise.
    """
    ctx = _gate_context(task)
    if not ctx:
        return None
    step_id = ctx.get("step_id") or ""
    if "pick" not in step_id and "build-pick" not in step_id:
        return None

    hint = (feedback or "").strip().lower()
    winner = None
    for marker in ("winner:a", "winner: a", "pick:a", "pick: a", "build-a", "build a", " a ", "\na\n"):
        if marker in f"\n{hint}\n":
            winner = "a"
            break
    if not winner:
        for marker in ("winner:b", "winner: b", "pick:b", "pick: b", "build-b", "build b", " b ", "\nb\n"):
            if marker in f"\n{hint}\n":
                winner = "b"
                break
    if not winner and hint in ("a", "b"):
        winner = hint
    if not winner:
        return None

    source_key = f"game_html_v1@{winner}"
    html = project_memory.read(task.project_id, "artifact", source_key)
    if not html:
        logger.warning(f"Pick gate {task.id}: artifact {source_key} not in memory")
        return None
    project_memory.write(
        task.project_id,
        mem_type="artifact",
        key="game_html_v1",
        content=html,
        created_by=f"gate:{task.id}",
    )
    logger.info(f"Pick gate {task.id}: promoted {source_key} -> game_html_v1 ({len(html)} chars)")
    return winner


@app.post("/api/gates/{task_id}/approve")
async def approve_gate(task_id: str, body: GateDecisionBody | None = None):
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Gate task not found")
    ctx = _gate_context(task)
    if not ctx:
        raise HTTPException(400, "Task is not a human gate")
    feedback = (body.feedback if body else "") or "approved"
    winner = _promote_pick(task, feedback)
    result: dict = {"decision": "approved", "feedback": feedback}
    if winner:
        result["pick_winner"] = winner
    task_queue.update_status(task.id, TaskStatus.COMPLETED, result=result)
    await ws_manager.broadcast({"type": "gate_approved", "data": {"task_id": task.id, "pick_winner": winner}})
    await _advance_pipeline(task.project_id)
    return {"status": "approved", "task_id": task.id, "pick_winner": winner}


@app.post("/api/gates/{task_id}/revise")
async def revise_gate(task_id: str, body: GateDecisionBody):
    """Request changes on the preceding step: spawn a revision task, leave the gate pending."""
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Gate task not found")
    ctx = _gate_context(task)
    if not ctx:
        raise HTTPException(400, "Task is not a human gate")
    feedback = (body.feedback or "").strip()
    if not feedback:
        raise HTTPException(400, "Feedback required to request changes")

    agent_type = ctx.get("review_of_agent")
    if not agent_type:
        raise HTTPException(400, "Gate has no preceding agent step to revise")

    revise_desc = (
        f"Revise the previous {ctx.get('review_of')} output based on human feedback:\n\n"
        f"{feedback}\n\n"
        "Update the same memory artifact keys the original step wrote to."
    )
    revision = task_queue.create(TaskCreate(
        project_id=task.project_id,
        title=f"[{ctx['pipeline']}] {ctx['review_of']}-revision",
        description=revise_desc,
        assignee_type=agent_type,
        created_by=f"pipeline:{ctx['pipeline']}",
        model_override=task.model_override,
    ))
    # Make the gate wait on the new revision instead of the original step so it re-opens once revised.
    import json as _json
    from src.database import get_studio_db as _db
    new_deps = list(task.depends_on) + [revision.id]
    with _db() as db:
        db.execute("UPDATE tasks SET depends_on=?, result=? WHERE id=?",
                   (_json.dumps(new_deps), _json.dumps({"decision": "changes_requested", "feedback": feedback, "revision_task_id": revision.id}), task.id))

    # Kick the revision task running
    try:
        instance = registry.spawn(
            agent_type=agent_type,
            project_id=task.project_id,
            task_id=revision.id,
            model_override=revision.model_override,
        )
        task_queue.checkout(revision.id, instance.id)
        asyncio.create_task(_run_agent_task(instance, revise_desc))
    except ValueError as exc:
        logger.warning(f"Failed to spawn revision for gate {task.id}: {exc}")

    await ws_manager.broadcast({"type": "gate_revision", "data": {"task_id": task.id, "revision_task_id": revision.id}})
    return {"status": "revision_requested", "task_id": task.id, "revision_task_id": revision.id}


# ==================== Game preview + asset previews ====================

@app.get("/api/projects/{project_id}/game/preview")
async def game_preview(project_id: str, key: str = "game_html_v1"):
    """Serve the current build HTML for in-dashboard playtest.

    Lets the human reviewer click "Play" at the QA/LAF gate and load the
    actual build in an iframe (or new tab) without leaving the project.
    """
    from fastapi.responses import HTMLResponse, PlainTextResponse
    html = project_memory.read(project_id, "artifact", key)
    if not html:
        return PlainTextResponse(f"No build in memory at artifact:{key}", status_code=404)
    return HTMLResponse(html)


@app.get("/api/projects/{project_id}/assets/previews")
async def list_asset_previews(project_id: str):
    """List downloaded preview images in the project's assets/ dir for the LAF gate."""
    from fastapi.responses import JSONResponse
    assets_root = Path(settings.projects_dir) / project_id / "assets"
    hits: list[dict] = []
    if assets_root.is_dir():
        for fp in sorted(assets_root.rglob("*")):
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
                continue
            rel = fp.relative_to(assets_root)
            hits.append({
                "path": str(rel),
                "url": f"/api/projects/{project_id}/assets/file/{rel}",
                "bytes": fp.stat().st_size,
            })
    return JSONResponse(hits)


@app.get("/api/projects/{project_id}/assets/file/{path:path}")
async def get_asset_file(project_id: str, path: str):
    """Stream a single asset file out of the project's workspace."""
    from fastapi.responses import FileResponse, PlainTextResponse
    base = (Path(settings.projects_dir) / project_id / "assets").resolve()
    fp = (base / path).resolve()
    if not str(fp).startswith(str(base)) or not fp.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(fp)


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
            "instances": len(registry.list_instances()),
            "running": len(registry.list_instances(status=AgentStatus.RUNNING)),
        },
        "cost_usd": round(total_cost, 4),
    }


# ==================== Dashboard Static Files ====================

_dashboard_dist = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
if _dashboard_dist.is_dir():
    # Serve index.html for SPA client-side routing
    from fastapi.responses import FileResponse

    @app.get("/app/{rest:path}")
    async def spa_fallback(rest: str):
        """Serve dashboard SPA — all non-API routes fall through to index.html."""
        file_path = _dashboard_dist / rest
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_dashboard_dist / "index.html")

    @app.get("/app")
    async def spa_root():
        return FileResponse(_dashboard_dist / "index.html")

    app.mount("/assets", StaticFiles(directory=str(_dashboard_dist / "assets")), name="dashboard-assets")
