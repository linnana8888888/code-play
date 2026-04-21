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
from src.database import init_studio_db, init_project_db, get_studio_db, get_project_db
from src.game_registry import list_games as _list_games, get_game as _get_game, get_active_version
from src.game_resolver import resolve_game_repo
from src.models.projects import Project, ProjectCreate
from src.models.tasks import TaskCreate, TaskStatus, TaskUpdate
from src.models.agents import AgentStatus
from src.orchestrator.agent_registry import registry
from src.orchestrator.task_queue import task_queue
from src.runtime.llm_router import router
from src.runtime.tool_executor import tool_executor
from src.runtime.agent_runtime import agent_runtime
from src.runtime.session_store import session_store
from src.runtime.task_validator import substitute_expected_outputs, validate_outputs
from src.runtime.skill_registry import skill_registry
from src.runtime.claude_bridge import discover as discover_claude_plugins
from src.runtime.mcp_bridge import mcp_bridge
from src.communication.message_bus import message_bus
from src.memory.project_memory import project_memory
from src.memory import criteria_store
from src.memory import project_docs
from src.memory import proposals_store
from src.iteration.bootstrap import ensure_goals_md, ensure_briefing_md, GoalsBootstrapError
from src.models.criteria import CriterionCreate, CriterionUpdate
from src.models.proposals import (
    AgentProposalCreate,
    BatchDecision,
    ProposalPhase,
    ProposalStatus,
    SingleDecision,
)
from src.iteration import cycle_state

# --- Failure classification -------------------------------------------------

# Retryable transient signals from LLM providers or the network. These map to
# `failure_category = "transient"` so the dashboard shows a plain retry button
# without extra input, and the automatic retry loop will try again.
_TRANSIENT_MARKERS = (
    "503", "502", "504", "429",
    "service unavailable", "bad gateway", "gateway timeout",
    "timeout", "timed out", "connection reset", "connection aborted",
    "temporarily unavailable", "rate limit", "try again",
)


def _classify_failure(err_text: str, *, terminated_for_budget: bool = False) -> str:
    """Return `budget_exhausted` | `transient` | `permanent` for a failure.

    Used by `_run_agent_task` and `_advance_pipeline` to tag `task.result`
    so the dashboard can render the right affordance (lift cap, retry,
    or "permanent — fix config").
    """
    if terminated_for_budget:
        return "budget_exhausted"
    low = (err_text or "").lower()
    for m in _TRANSIENT_MARKERS:
        if m in low:
            return "transient"
    return "permanent"


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

    _lint_pipeline_save_instructions()
    _lint_pipeline_agent_tools()

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
    if settings.environment == "test":
        logger.info("environment=test; skipping gh repo create for %r", name)
        return None, None
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
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else f"https://github.com/{settings.github_owner}/{slug}"
        return url, slug
    except Exception as exc:
        logger.warning("gh repo create exception: %s", exc)
        return None, None


def _publish_artifacts_to_repo(project_id: str, repo_name: str) -> tuple[bool, str]:
    """Initialize git in the project's artifact directory and push to the GitHub repo.

    Returns (success, message). Idempotent for an already-initialized artifact dir.
    Only runs when the directory has at least one file to avoid pushing empty repos.
    """
    if settings.environment == "test":
        return False, "environment=test; skipping publish"
    artifact_dir = Path(settings.projects_dir) / project_id
    if not artifact_dir.is_dir():
        return False, f"artifact dir missing: {artifact_dir}"
    has_content = any(p.is_file() for p in artifact_dir.rglob("*") if ".git" not in p.parts)
    if not has_content:
        return False, "no artifact files to push — publish blocked to prevent empty-repo leak"
    remote = f"https://github.com/{settings.github_owner}/{repo_name}.git"
    try:
        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, cwd=artifact_dir, capture_output=True, text=True, timeout=60)
        if not (artifact_dir / ".git").exists():
            run(["git", "init", "-b", "main"])
        run(["git", "remote", "remove", "origin"])  # ignore failure if missing
        r = run(["git", "remote", "add", "origin", remote])
        if r.returncode != 0 and "already exists" not in r.stderr:
            return False, f"remote add failed: {r.stderr.strip()}"
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", f"Publish {project_id} artifacts"])  # no-op if nothing to commit
        r = run(["git", "push", "-u", "origin", "main"])
        if r.returncode != 0:
            return False, f"push failed: {r.stderr.strip()}"
        return True, "pushed"
    except Exception as exc:
        return False, f"publish exception: {exc}"


# ── Game registry ──────────────────────────────────────────────────────

from dataclasses import asdict


@app.get("/api/games")
def list_games_api():
    return [asdict(g) for g in _list_games()]


@app.get("/api/games/{slug}")
def get_game_api(slug: str):
    game = _get_game(slug)
    if not game:
        raise HTTPException(404, f"Game '{slug}' not found in games/ registry")
    return asdict(game)


@app.post("/api/projects", response_model=Project)
async def create_project(body: ProjectCreate):
    project_id = f"proj-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    repo_url, repo_name = (None, None)
    game_slug = body.game_slug
    pipeline = body.pipeline
    auto_iterate = body.auto_iterate

    # ── Game-linked project: resolve repo, override defaults ──
    artifact_repo_path: str | None = None
    if game_slug:
        game = _get_game(game_slug)
        if not game:
            raise HTTPException(404, f"Game '{game_slug}' not found in games/ registry")
        try:
            local_path = await asyncio.to_thread(resolve_game_repo, game)
            artifact_repo_path = str(local_path.resolve())
        except Exception as exc:
            raise HTTPException(500, f"Failed to resolve game repo for '{game_slug}': {exc}")
        repo_url = game.source.repo or body.repo_url
        if not pipeline or pipeline == "phased-producer":
            pipeline = "iterate_artifact"
        auto_iterate = True

    if not repo_url and body.repo_url:
        repo_url = body.repo_url
    if body.create_repo and not repo_url:
        repo_url, repo_name = await asyncio.to_thread(_create_github_repo, body.name, body.description)

    with get_studio_db() as db:
        db.execute(
            "INSERT INTO projects (id, name, description, goal, tech_stack, repo_url, repo_name, require_roster_approval, auto_iterate, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, body.name, body.description, body.goal, body.tech_stack, repo_url, repo_name,
             1 if body.require_roster_approval else 0,
             1 if auto_iterate else 0,
             now, now),
        )

    # Init project memory DB
    init_project_db(project_id)

    # ── Seed memory for game-linked projects ──
    if game_slug and artifact_repo_path:
        project_memory.write(project_id, "artifact", "artifact_repo_path", artifact_repo_path, created_by="game_resolver")
        with get_studio_db() as db:
            db.execute("UPDATE projects SET iterate_enabled = 1 WHERE id = ?", (project_id,))

    project = Project(
        id=project_id,
        name=body.name,
        description=body.description,
        goal=body.goal,
        tech_stack=body.tech_stack,
        status="active",
        repo_url=repo_url,
        repo_name=repo_name,
        require_roster_approval=body.require_roster_approval,
        auto_iterate=auto_iterate,
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
    )

    await ws_manager.broadcast({"type": "project_created", "data": project.model_dump(mode="json")})

    # Auto-launch pipeline (producer drives the team from here)
    if pipeline:
        try:
            await run_pipeline(
                pipeline,
                PipelineRunBody(project_id=project_id, input_text=body.goal or body.description),
            )
            await ws_manager.broadcast({
                "type": "pipeline_auto_launched",
                "data": {"project_id": project_id, "pipeline": pipeline},
            })
            logger.info(f"[{project_id}] Auto-launched pipeline '{pipeline}'")
        except Exception as e:
            logger.warning(f"[{project_id}] Auto-launch pipeline '{pipeline}' failed: {e}")

    return project


def _project_row_to_dict(row) -> dict:
    d = dict(row)
    if "require_roster_approval" in d:
        d["require_roster_approval"] = bool(d["require_roster_approval"])
    if "auto_iterate" in d:
        d["auto_iterate"] = bool(d["auto_iterate"])
    return d


@app.post("/api/projects/{project_id}/publish")
async def publish_project(project_id: str):
    """Create a GitHub repo (if missing) and push current artifacts.

    Preferred over `create_repo=True` at project-create time — defers the side
    effect until there's something real to publish, preventing empty-repo leaks.
    """
    with get_studio_db() as db:
        row = db.execute("SELECT id, name, description, repo_url, repo_name FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")

    repo_url = row["repo_url"]
    repo_name = row["repo_name"]

    if not repo_name:
        repo_url, repo_name = await asyncio.to_thread(_create_github_repo, row["name"], row["description"])
        if not repo_name:
            raise HTTPException(502, "Failed to create GitHub repo — check gh auth and environment")
        with get_studio_db() as db:
            db.execute(
                "UPDATE projects SET repo_url = ?, repo_name = ?, updated_at = ? WHERE id = ?",
                (repo_url, repo_name, datetime.now(timezone.utc).isoformat(), project_id),
            )

    ok, msg = await asyncio.to_thread(_publish_artifacts_to_repo, project_id, repo_name)
    if not ok:
        raise HTTPException(409, f"Publish blocked: {msg}")
    return {"repo_url": repo_url, "repo_name": repo_name, "status": "published", "detail": msg}


@app.get("/api/projects")
async def list_projects():
    with get_studio_db() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [_project_row_to_dict(r) for r in rows]


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    with get_studio_db() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return _project_row_to_dict(row)


def _delete_project_cascade(project_id: str) -> dict:
    """Remove a project's DB rows across every studio table, then nuke the
    projects/{id}/ directory. Idempotent — missing rows/files are not errors."""
    import shutil
    deleted = {"project_id": project_id}
    with get_studio_db() as db:
        row = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        deleted["existed"] = bool(row)
        # Clean document_revisions for this project first (no FK in schema)
        doc_ids = [r["id"] for r in db.execute(
            "SELECT id FROM documents WHERE project_id = ?", (project_id,)
        ).fetchall()]
        for did in doc_ids:
            db.execute("DELETE FROM document_revisions WHERE document_id = ?", (did,))
        for table in (
            "cost_log", "messages", "agent_instances", "tasks",
            "success_criteria", "documents", "agent_proposals",
        ):
            cur = db.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
            deleted[table] = cur.rowcount
        cur = db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        deleted["projects"] = cur.rowcount

    project_dir = Path(settings.projects_dir) / project_id
    if project_dir.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)
        deleted["fs_removed"] = True
    else:
        deleted["fs_removed"] = False
    return deleted


def _project_is_empty(db, project_id: str) -> bool:
    """A project is 'empty' if it has no tasks AND no memory rows.

    Uses `get_project_db` so we hit the exact same path project_memory wrote to,
    rather than reconstructing it from `settings.projects_dir`."""
    task_count = db.execute(
        "SELECT COUNT(*) as c FROM tasks WHERE project_id = ?", (project_id,)
    ).fetchone()["c"]
    if task_count > 0:
        return False
    try:
        with get_project_db(project_id) as pdb:
            mem_count = pdb.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
    except Exception:
        mem_count = 0
    return mem_count == 0


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Hard-delete a single project and everything it owns (tasks, memory,
    messages, worktrees, assets). Idempotent — deleting a missing id 404s."""
    with get_studio_db() as db:
        row = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    result = _delete_project_cascade(project_id)
    await ws_manager.broadcast({"type": "project_deleted", "data": {"project_id": project_id}})
    return {"status": "deleted", **result}


@app.post("/api/projects/cleanup")
async def cleanup_projects(
    dry_run: bool = True,
    only_empty: bool = True,
    older_than_days: int | None = None,
    keep_ids: str = "",
):
    """Bulk-delete self-generated junk projects.

    Defaults are safe (`dry_run=True`, `only_empty=True`) so humans can preview
    what would be deleted. Set `dry_run=false` to actually delete.

    - only_empty: only sweep projects that have no tasks and no memory artifacts
    - older_than_days: skip projects newer than N days (None = no age filter)
    - keep_ids: comma-separated allow-list of project ids to never delete
    """
    from datetime import datetime, timezone, timedelta
    keep = {s.strip() for s in keep_ids.split(",") if s.strip()}

    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    with get_studio_db() as db:
        rows = db.execute("SELECT id, name, created_at FROM projects").fetchall()
        candidates: list[dict] = []
        for r in rows:
            pid = r["id"]
            if pid in keep:
                continue
            if cutoff is not None:
                try:
                    created = datetime.fromisoformat(r["created_at"])
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created > cutoff:
                        continue
                except Exception:
                    pass  # unparseable → fall through and consider it
            if only_empty and not _project_is_empty(db, pid):
                continue
            candidates.append({"id": pid, "name": r["name"], "created_at": r["created_at"]})

    if dry_run:
        return {"dry_run": True, "would_delete": candidates, "count": len(candidates)}

    deleted: list[dict] = []
    for c in candidates:
        deleted.append(_delete_project_cascade(c["id"]))
    await ws_manager.broadcast({
        "type": "projects_cleaned",
        "data": {"count": len(deleted), "ids": [d["project_id"] for d in deleted]},
    })
    return {"dry_run": False, "deleted": deleted, "count": len(deleted)}


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


def _project_requires_roster_approval(project_id: str | None) -> bool:
    if not project_id:
        return False
    try:
        with get_studio_db() as db:
            row = db.execute(
                "SELECT require_roster_approval FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return bool(row and row["require_roster_approval"])
    except Exception:
        return False


async def _spawn_from_approved_proposal(proposal_id: str, task_prompt: str | None = None):
    """Spawn an agent for an approved proposal and start it.

    Returns the spawned AgentInstance, or None if the proposal isn't approved.
    """
    p = proposals_store.get(proposal_id)
    if not p or p.status.value != "approved":
        return None
    try:
        instance = registry.spawn(
            agent_type=p.agent_type,
            project_id=p.project_id,
            task_id=p.task_id,
            model_override=p.model_override,
        )
    except ValueError:
        return None

    proposals_store.mark_spawned(proposal_id, instance.id)
    await ws_manager.broadcast({
        "type": "agent_spawned",
        "data": {
            "id": instance.id,
            "agent_type": p.agent_type,
            "model": instance.model,
            "project_id": p.project_id,
            "from_proposal": proposal_id,
        },
    })

    prompt = task_prompt
    if p.task_id and not prompt:
        t = task_queue.get(p.task_id)
        if t:
            task_queue.checkout(p.task_id, instance.id)
            prompt = t.description or t.title
    if prompt:
        asyncio.create_task(_run_agent_task(instance, prompt))
    return instance


@app.post("/api/agents/spawn")
async def spawn_agent(
    agent_type: str,
    project_id: str = None,
    task_prompt: str = None,
    model_override: str = None,
):
    """Spawn an agent instance and optionally start it on a task.

    When the project has `require_roster_approval=1`, this creates an
    in-flight proposal instead of spawning immediately.
    """
    if _project_requires_roster_approval(project_id):
        p = proposals_store.create(AgentProposalCreate(
            project_id=project_id,
            agent_type=agent_type,
            rationale="Direct spawn request via API",
            proposer="human",
            phase=ProposalPhase.IN_FLIGHT,
            model_override=model_override,
        ))
        await ws_manager.broadcast({
            "type": "proposal_created",
            "data": {"id": p.id, "project_id": project_id, "batch_id": p.batch_id, "phase": p.phase.value},
        })
        return {"status": "pending_approval", "proposal_id": p.id, "batch_id": p.batch_id}

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


@app.delete("/api/agents/instances/sweep")
async def sweep_finished_instances(project_id: str = None):
    """Remove terminated/completed/failed agent instances."""
    removed = registry.sweep_finished(project_id=project_id)
    return {"removed": removed}


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
            briefing = project_memory.read(instance.project_id, "artifact", "briefing_md")
            if briefing:
                context_messages.append({
                    "role": "user",
                    "content": f"[Project Briefing]\n{briefing}",
                })
            # Inject agent-type lessons (behavioral memory from past failures)
            from src.memory.agent_lessons import agent_lessons
            lessons_prompt = agent_lessons.format_for_prompt(
                instance.project_id, instance.agent_type or "unknown"
            )
            if lessons_prompt:
                context_messages.append({
                    "role": "user",
                    "content": f"[Agent Lessons — READ CAREFULLY]\n{lessons_prompt}",
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

        # Detect budget-exhausted termination — the runtime emits a final
        # "[TERMINATED] Budget exceeded" assistant turn and flips the agent
        # instance to TERMINATED. Surface this as a BLOCKED task with a
        # `budget_exhausted` category so the dashboard can prompt the human
        # to lift the cap and retry instead of silently marking success.
        terminated_for_budget = (
            instance.status == AgentStatus.TERMINATED
            and isinstance(final_content, str)
            and final_content.startswith("[TERMINATED] Budget exceeded")
        )

        if instance.task_id:
            if terminated_for_budget:
                # Before blocking, check if the agent already produced its
                # deliverables before the budget killed it (zombie-task rescue).
                outputs_present = False
                try:
                    current_task = task_queue.get(instance.task_id)
                    if current_task and current_task.expected_outputs:
                        repo_dir = None
                        if instance.project_id:
                            candidate = Path(settings.projects_dir) / instance.project_id
                            if candidate.exists():
                                repo_dir = candidate
                        missing = validate_outputs(current_task, project_memory, repo_dir)
                        outputs_present = len(missing) == 0
                except Exception as exc:
                    logger.warning(f"Zombie-task rescue check failed for {instance.task_id}: {exc}")

                if outputs_present:
                    logger.info(
                        f"[{instance.task_id}] Budget exceeded but outputs already present — "
                        f"completing task instead of blocking (zombie-task rescue)"
                    )
                    try:
                        task_queue.update_status(
                            instance.task_id,
                            TaskStatus.COMPLETED,
                            result={
                                "summary": final_content[:20000],
                                "agent_instance_id": instance.id,
                                "rescued": True,
                                "rescue_reason": "budget_exceeded_but_outputs_present",
                            },
                        )
                        await ws_manager.broadcast({
                            "type": "task_completed",
                            "data": {
                                "task_id": instance.task_id,
                                "instance_id": instance.id,
                                "rescued": True,
                            },
                        })
                    except Exception as exc:
                        logger.warning(f"Zombie-task rescue failed for {instance.task_id}: {exc}")
                    # Advance the pipeline — the work is done.
                    if instance.project_id:
                        await _advance_pipeline(instance.project_id)
                    return

                prev_cap = instance.budget_max_tokens or 0
                suggested_cap = max(prev_cap * 2, prev_cap + 100_000) if prev_cap else 300_000
                result = {
                    "failure_category": "budget_exhausted",
                    "error": final_content[:400],
                    "tokens_used": instance.tokens_used,
                    "prev_cap": prev_cap,
                    "suggested_cap": suggested_cap,
                    "agent_instance_id": instance.id,
                }
                try:
                    task_queue.update_status(instance.task_id, TaskStatus.BLOCKED, result=result)
                except Exception as exc:
                    logger.warning(f"Failed to mark task {instance.task_id} blocked-for-budget: {exc}")
                await ws_manager.broadcast({
                    "type": "task_stalled",
                    "data": {
                        "task_id": instance.task_id,
                        "project_id": instance.project_id,
                        "failure_category": "budget_exhausted",
                        "tokens_used": instance.tokens_used,
                        "prev_cap": prev_cap,
                        "suggested_cap": suggested_cap,
                        "hint": "Budget cap hit — open the task and Lift cap to retry, or close it if the agent spiralled.",
                    },
                })
                # Auto-extract lesson from budget failure
                try:
                    from src.memory.agent_lessons import agent_lessons
                    agent_lessons.extract_from_failure(
                        instance.project_id or "",
                        instance.agent_type or "unknown",
                        "budget_exhausted", [],
                        task_prompt[:500],
                    )
                except Exception:
                    pass
                # Do NOT advance the pipeline — the task is waiting on a human.
                return
            # Post-run output validation — catches silent-success runs where
            # the agent returns cleanly without producing the deliverables
            # declared in task.expected_outputs.
            missing: list[str] = []
            try:
                current_task = task_queue.get(instance.task_id)
                if current_task and current_task.expected_outputs:
                    repo_dir = None
                    if instance.project_id:
                        candidate = Path(settings.projects_dir) / instance.project_id
                        if candidate.exists():
                            repo_dir = candidate
                    missing = validate_outputs(current_task, project_memory, repo_dir)
            except Exception as exc:
                logger.warning(f"validate_outputs failed for {instance.task_id}: {exc}")

            if missing:
                # Auto-extract lesson from output validation failure
                try:
                    from src.memory.agent_lessons import agent_lessons
                    agent_lessons.extract_from_failure(
                        instance.project_id or "",
                        instance.agent_type or "unknown",
                        "no_output", missing,
                        task_prompt[:500],
                    )
                except Exception:
                    pass
                result = {
                    "failure_category": "no_output",
                    "error": f"Agent returned cleanly but expected outputs missing: {'; '.join(missing[:5])}",
                    "missing": missing,
                    "summary": final_content[:4000],
                    "agent_instance_id": instance.id,
                    "tokens_used": instance.tokens_used,
                    "hint": "Agent declared done without producing deliverables — retry from the task card or adjust expected_outputs.",
                }
                try:
                    task_queue.update_status(instance.task_id, TaskStatus.BLOCKED, result=result)
                except Exception as exc:
                    logger.warning(f"Failed to mark task {instance.task_id} blocked-for-no-output: {exc}")
                await ws_manager.broadcast({
                    "type": "task_stalled",
                    "data": {
                        "task_id": instance.task_id,
                        "project_id": instance.project_id,
                        "failure_category": "no_output",
                        "missing": missing,
                        "tokens_used": instance.tokens_used,
                        "hint": result["hint"],
                    },
                })
                return
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
        err_text = str(e)
        category = _classify_failure(err_text)
        logger.error(f"Agent {instance.id} failed ({category}): {err_text}")
        if instance.task_id:
            try:
                task_queue.update_status(
                    instance.task_id,
                    TaskStatus.BLOCKED,
                    result={"error": err_text, "failure_category": category},
                )
            except Exception:
                pass
            await ws_manager.broadcast({
                "type": "task_stalled",
                "data": {
                    "task_id": instance.task_id,
                    "project_id": instance.project_id,
                    "failure_category": category,
                    "error": err_text[:400],
                    "hint": (
                        "Transient provider error — safe to retry from the task card."
                        if category == "transient"
                        else "Permanent agent crash — inspect logs before retrying."
                    ),
                },
            })
        await ws_manager.broadcast({
            "type": "agent_error",
            "data": {
                "instance_id": instance.id,
                "error": err_text,
                "failure_category": category,
            },
        })


async def _maybe_relaunch_cyclic(project_id: str, pipeline_specs: dict) -> None:
    """For each cyclic pipeline whose terminal_step has just completed,
    re-enqueue the first step for cycle n+1. Subject to the cycle_state
    budget and halt_reason — if either trips, the loop silently stops.
    """
    all_tasks = task_queue.list_tasks(project_id=project_id)
    for pname, pspec in pipeline_specs.items():
        if not pspec.get("cyclic"):
            continue
        terminal_id = pspec.get("terminal_step")
        steps = pspec.get("steps", []) or []
        if not terminal_id or not steps:
            continue
        first_step = steps[0]
        terminal_title = f"[{pname}] {terminal_id}"
        first_title = f"[{pname}] {first_step['id']}"

        completed_terminals = [
            t for t in all_tasks
            if t.title == terminal_title and t.status == TaskStatus.COMPLETED
        ]
        if not completed_terminals:
            continue
        latest = max(
            completed_terminals,
            key=lambda t: t.updated_at or t.created_at or datetime.min,
        )
        cycle_n = int((latest.metadata or {}).get("cycle_n") or 0)
        if cycle_n <= 0:
            cycle_n = cycle_state.get_cycle_n(project_id)
        next_n = cycle_n + 1

        already = any(
            t.title == first_title
            and int((t.metadata or {}).get("cycle_n") or 0) == next_n
            for t in all_tasks
        )
        if already:
            continue
        if not cycle_state.should_relaunch(project_id):
            continue

        cycle_state.bump_cycle(project_id, next_n)
        tag = f"v{next_n}"
        metadata = {"iteration_tag": tag, "cycle_n": next_n}

        # Mirror run_pipeline: scaffold every step for the new cycle with its
        # depends_on wired by name→task_id. Without this, prep-brief /
        # implement / budget_gate only ever existed for cycle 1 and had to be
        # hand-injected on every subsequent cycle.
        created_tasks: dict[str, str] = {}
        first_task_id: str | None = None
        for step in steps:
            step_id = step["id"]
            task_desc = (
                step.get("task", "")
                .replace("{{iteration_tag}}", tag)
                .replace("{{cycle_n}}", str(next_n))
            )
            deps = [
                created_tasks[dep_name]
                for dep_name in step.get("depends_on", [])
                if dep_name in created_tasks
            ]
            step_expected = substitute_expected_outputs(
                step.get("expected_outputs"),
                iteration_tag=tag,
                cycle_n=next_n,
            )
            new_task = task_queue.create(TaskCreate(
                project_id=project_id,
                title=f"[{pname}] {step_id}",
                description=task_desc,
                depends_on=deps,
                created_by=f"pipeline:{pname}",
                metadata=metadata,
                expected_outputs=step_expected,
            ))
            created_tasks[step_id] = new_task.id
            if first_task_id is None:
                first_task_id = new_task.id

        logger.info(
            f"Relaunched cyclic pipeline '{pname}' for {project_id} cycle {next_n} "
            f"({len(created_tasks)} tasks scaffolded)"
        )
        await ws_manager.broadcast({
            "type": "cycle_relaunched",
            "data": {
                "project_id": project_id,
                "pipeline": pname,
                "cycle_n": next_n,
                "task_id": first_task_id,
                "task_count": len(created_tasks),
            },
        })


async def _maybe_auto_iterate(project_id: str):
    """Notify the human when phased-producer completes, prompting V1 review.

    If auto_iterate is enabled on the project AND goals exist, auto-launch
    iterate_artifact. Otherwise, broadcast a v1_review_ready event so the
    human can review, set goals, and manually trigger iteration.
    """
    with get_studio_db() as db:
        row = db.execute(
            "SELECT auto_iterate, iterate_enabled FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    if not row or row["iterate_enabled"]:
        return

    all_tasks = task_queue.list_tasks(project_id=project_id)
    if not all_tasks:
        return
    if not all(t.status == TaskStatus.COMPLETED for t in all_tasks):
        return

    has_phased = any(
        (t.created_by or "").startswith("pipeline:phased-producer") for t in all_tasks
    )
    if not has_phased:
        return

    # Auto-iterate only if the human opted in AND goals are already set
    if row["auto_iterate"]:
        try:
            ensure_goals_md(project_id)
            ensure_briefing_md(project_id)
            logger.info(f"[{project_id}] phased-producer complete + goals set — auto-launching iterate_artifact")
            await run_pipeline(
                "iterate_artifact",
                PipelineRunBody(project_id=project_id, input_text=""),
            )
            await ws_manager.broadcast({
                "type": "pipeline_auto_launched",
                "data": {"project_id": project_id, "pipeline": "iterate_artifact"},
            })
            return
        except GoalsBootstrapError:
            pass  # Fall through to v1_review_ready — goals not set yet

    # Default: notify human that V1 is ready for review + goals setup
    logger.info(f"[{project_id}] phased-producer complete — V1 ready for human review")
    await ws_manager.broadcast({
        "type": "v1_review_ready",
        "data": {
            "project_id": project_id,
            "message": "V1 build complete. Review the game, then set GOALS.md and trigger iteration.",
            "actions": {
                "review": f"/api/projects/{project_id}",
                "set_goals": f"Write GOALS.md with iteration targets before starting iterate_artifact",
                "iterate": f"/api/pipelines/advance?project_id={project_id}&force_phase=iterate_artifact",
            },
        },
    })


async def _advance_pipeline(project_id: str):
    """Spawn agents for any newly-ready pipeline tasks."""
    pipeline_specs = _load_pipelines_yaml().get("pipelines", {}) or {}

    # Cyclic pipelines relaunch their first step once their terminal step
    # completes — do this BEFORE resolving ready tasks so the new first-step
    # task lands in the same sweep.
    try:
        await _maybe_relaunch_cyclic(project_id, pipeline_specs)
    except Exception as exc:
        logger.warning(f"cyclic relaunch check failed for {project_id}: {exc}")

    try:
        ready = task_queue.get_ready_tasks(project_id)
    except Exception as exc:
        logger.warning(f"get_ready_tasks failed: {exc}")
        return

    if not ready:
        # No ready tasks — check if phased-producer just completed and auto-iterate is on
        await _maybe_auto_iterate(project_id)
        return

    async def _stall(task, reason: str, hint: str | None = None):
        """One-shot stall: block the task + broadcast so the UI can prompt."""
        task_queue.stall_task(task.id, reason, hint=hint)
        await ws_manager.broadcast({
            "type": "task_stalled",
            "data": {
                "task_id": task.id,
                "project_id": task.project_id,
                "failure_category": "permanent",
                "stall_reason": reason,
                "hint": hint,
            },
        })

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
                await _stall(
                    task,
                    f"Pipeline '{pipeline_name}' referenced by task.created_by not found in pipelines.yaml.",
                    "Check pipelines.yaml — the pipeline may have been renamed or removed.",
                )
                continue

            step_id = task.title.replace(f"[{pipeline_name}] ", "").strip()
            step = next((s for s in pipeline.get("steps", []) if s.get("id") == step_id), None)
            if step is None:
                # Dynamic fan-out sub-tasks (e.g. implement-engineer-eng-1)
                # carry `pipeline:` provenance but aren't in the yaml. Fall
                # back to the task's assignee_type so they still spawn.
                if task.assignee_type:
                    agent_type = task.assignee_type
                else:
                    await _stall(
                        task,
                        f"No yaml step '{step_id}' in pipeline '{pipeline_name}' and task has no assignee_type.",
                        "Either add the step to pipelines.yaml or set assignee_type on the task.",
                    )
                    continue
            else:
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
            await _stall(
                task,
                "Task is ready but has no agent_type to spawn (no pipeline step, no assignee_type).",
                "Set assignee_type on the task, or attach it to a pipeline with an `agent:` field.",
            )
            continue

        budget_override = None
        if task.metadata and isinstance(task.metadata, dict):
            raw = task.metadata.get("budget_max_tokens_override")
            try:
                if raw is not None:
                    budget_override = int(raw)
            except (TypeError, ValueError):
                budget_override = None

        # Let a yaml step pin a specific model (e.g. Haiku for the cheap
        # estimator). Task-level override always wins when set.
        effective_model_override = task.model_override
        if not effective_model_override and step and step.get("model_override"):
            effective_model_override = step.get("model_override")

        try:
            instance = registry.spawn(
                agent_type=agent_type,
                project_id=project_id,
                task_id=task.id,
                model_override=effective_model_override,
                budget_max_tokens_override=budget_override,
            )
            task_queue.checkout(task.id, instance.id)
            asyncio.create_task(_run_agent_task(instance, task.description))
            logger.info(f"Advanced pipeline: spawned {agent_type} for task {task.id}")
        except ValueError as exc:
            err = str(exc)
            count, blocked = task_queue.record_spawn_failure(task.id, err)
            if blocked:
                logger.error(
                    f"Task {task.id} BLOCKED after {count} failed spawns of "
                    f"'{agent_type}': {err}"
                )
                await ws_manager.broadcast({
                    "type": "spawn_failed",
                    "data": {
                        "task_id": task.id,
                        "project_id": project_id,
                        "agent_type": agent_type,
                        "error": err,
                        "failures": count,
                        "hint": "Check pipelines.yaml agent reference against agents.yaml registry.",
                    },
                })
            else:
                logger.warning(
                    f"Failed to spawn {agent_type} for task {task.id} "
                    f"(attempt {count}/3): {err}"
                )


class TaskRetryBody(BaseModel):
    """POST body for /api/tasks/{id}/retry.

    `budget_max_tokens_override` is the only dial exposed today. For
    `budget_exhausted` blocks the dashboard pre-fills it with the
    estimator's `suggested_cap` (2× previous cap). For other categories
    the field can be omitted and the task is reset with its existing
    metadata.
    """
    budget_max_tokens_override: int | None = None


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str, body: TaskRetryBody | None = None):
    """Reset a blocked/failed task to pending and advance the pipeline.

    Dashboard calls this from the "Retry" / "Lift cap and retry" buttons
    on blocked tasks. Permanent `stall_reason` blocks are still retriable
    — the button lets the human force a retry once they've fixed the
    underlying config — so the endpoint doesn't gate by category.
    """
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in (TaskStatus.BLOCKED, TaskStatus.FAILED):
        raise HTTPException(
            400,
            f"Task {task_id} is {task.status.value}; retry only valid for blocked/failed.",
        )
    cap = body.budget_max_tokens_override if body else None
    if cap is not None and cap > 0:
        task_queue.merge_metadata(task_id, {"budget_max_tokens_override": int(cap)})
    reset = task_queue.reset_for_retry(task_id)
    if not reset:
        raise HTTPException(500, "Reset failed")
    await ws_manager.broadcast({
        "type": "task_updated",
        "data": reset.model_dump(mode="json"),
    })
    if task.project_id:
        await _advance_pipeline(task.project_id)
    return {"status": "ok", "task_id": task_id, "new_cap": cap}


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a blocked/failed/pending task — marks it failed with cancelled flag."""
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(400, f"Task {task_id} is already completed.")
    cancelled = task_queue.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(500, "Cancel failed")
    await ws_manager.broadcast({
        "type": "task_updated",
        "data": cancelled.model_dump(mode="json"),
    })
    return {"status": "ok", "task_id": task_id}


@app.post("/api/tasks/cancel-blocked")
async def cancel_blocked_tasks(project_id: str | None = None):
    """Bulk-cancel all blocked tasks, optionally scoped to a project."""
    count = task_queue.cancel_all_blocked(project_id)
    await ws_manager.broadcast({
        "type": "tasks_bulk_cancelled",
        "data": {"count": count, "project_id": project_id},
    })
    return {"status": "ok", "cancelled": count}


# ==================== Tasks ====================

@app.post("/api/pipelines/advance")
async def advance_pipeline_endpoint(project_id: str, force_phase: str | None = None):
    """Manually trigger pipeline advancement for a project.

    When `force_phase` is supplied, boot that pipeline via `run_pipeline` —
    used by the dashboard's "Iterate" CTA to kick off iterate_artifact on a
    project that already finished its phased-producer run.
    """
    if force_phase:
        body = PipelineRunBody(project_id=project_id, input_text="")
        return await run_pipeline(force_phase, body)
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


# ==================== Agent Lessons ====================

@app.get("/api/projects/{project_id}/agent-lessons")
async def list_agent_lessons(project_id: str, agent_type: str = None):
    from src.memory.agent_lessons import agent_lessons
    if agent_type:
        return agent_lessons.get_lessons(project_id, agent_type)
    all_entries = project_memory.list_by_type(project_id, "agent_lesson")
    results = []
    for e in all_entries:
        try:
            data = json.loads(e["content"])
            data["_key"] = e["key"]
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return results


class AgentLessonBody(BaseModel):
    agent_type: str
    lesson: str
    severity: str = "warning"


@app.post("/api/projects/{project_id}/agent-lessons")
async def add_agent_lesson(project_id: str, body: AgentLessonBody):
    from src.memory.agent_lessons import agent_lessons
    key = agent_lessons.add_human_lesson(
        project_id, body.agent_type, body.lesson, body.severity
    )
    return {"status": "ok", "key": key}


@app.delete("/api/projects/{project_id}/agent-lessons/{lesson_key:path}")
async def delete_agent_lesson(project_id: str, lesson_key: str):
    from src.memory.agent_lessons import agent_lessons
    deleted = agent_lessons.delete_lesson(project_id, lesson_key)
    if not deleted:
        raise HTTPException(404, f"Lesson '{lesson_key}' not found")
    return {"status": "ok", "deleted": lesson_key}


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


def _lint_pipeline_save_instructions():
    """Warn at startup when a pipeline step expects a memory output but its
    task description never tells the agent to save to that key.

    Root cause of the cd-proposal-check stall: expected_outputs required
    cd_iterate_verdict_v1 but the prompt never said "save to memory".
    """
    data = _load_pipelines_yaml()
    for pname, pipeline in (data.get("pipelines") or {}).items():
        for step in pipeline.get("steps") or []:
            step_id = step.get("id", "?")
            task_text = (step.get("task") or "").lower()
            for eo in step.get("expected_outputs") or []:
                if eo.get("kind") != "memory_key":
                    continue
                key = eo.get("key", "")
                key_variants = {key.lower()}
                for tpl in ("{{iteration_tag}}", "{{cycle_n_plus_1}}", "{{cycle_n}}"):
                    key_variants |= {k.replace(tpl, "") for k in key_variants}
                key_variants.discard("")
                has_persist_verb = any(w in task_text for w in ("save", "write", "store"))
                key_mentioned = any(v in task_text for v in key_variants)
                if not has_persist_verb or not key_mentioned:
                    logger.warning(
                        "PIPELINE LINT [%s.%s]: expected_outputs requires memory key '%s' "
                        "but task description does not tell the agent to save it. "
                        "Agents will produce the output but not persist it.",
                        pname, step_id, key,
                    )


def _lint_pipeline_agent_tools():
    """Warn at startup when a pipeline agent lacks tools its step needs.

    Catches the class of bug where an agent is assigned to an iterate step
    that reads/writes repo files but doesn't have repo_file_read in its
    tool list — the agent stalls because it can't access game code.
    """
    REPO_TOOLS = {"repo_file_read", "repo_file_write", "repo_file_list"}
    REPO_HINT_PHRASES = (
        "repo_file_read", "repo_file_write", "repo_file_list",
        "repo_file", "artifact repo", "artifact_repo_path",
    )

    data = _load_pipelines_yaml()
    for pname, pipeline in (data.get("pipelines") or {}).items():
        for step in pipeline.get("steps") or []:
            step_id = step.get("id", "?")
            step_type = step.get("type", "agent")
            if step_type != "agent":
                continue
            agent_id = step.get("agent")
            if not agent_id:
                continue
            task_text = (step.get("task") or "").lower()
            needs_repo = any(phrase in task_text for phrase in REPO_HINT_PHRASES)
            if not needs_repo:
                continue
            defn = registry.get_definition(agent_id)
            if not defn:
                logger.warning(
                    "TOOL LINT [%s.%s]: agent '%s' not found in registry.",
                    pname, step_id, agent_id,
                )
                continue
            agent_tools = set(defn.tools or [])
            missing = REPO_TOOLS - agent_tools
            if missing:
                logger.warning(
                    "TOOL LINT [%s.%s]: task mentions repo_file tools but agent "
                    "'%s' is missing: %s. Agent will stall on file access.",
                    pname, step_id, agent_id, ", ".join(sorted(missing)),
                )


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
    """Launch a predefined pipeline for a project.

    When project.require_roster_approval is on, every agent-backed step
    becomes a kickoff proposal (one batch), and no agents spawn until the
    batch is approved via `/api/governance/proposals/batch/{bid}/approve`.
    """
    project_id = body.project_id
    input_text = body.input_text
    data = _load_pipelines_yaml()
    pipeline = data.get("pipelines", {}).get(pipeline_name)
    if not pipeline:
        raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")

    gated = _project_requires_roster_approval(project_id)
    batch_id = f"batch-{uuid.uuid4().hex[:10]}" if gated else None

    # Stamp the on-disk project_state.yaml as soon as we know a pipeline is
    # running. Other agents (producer persona, GPT, local Qwen) read this file
    # to answer "what phase is <slug>?" without hitting the studio DB.
    try:
        from src.runtime.project_state import (
            initial_state,
            read_state,
            resolve_state_path,
            write_state,
        )
        first_phase = "concept"
        steps_list = pipeline.get("steps") or []
        if steps_list and steps_list[0].get("id"):
            first_phase = steps_list[0]["id"]
        state_path = resolve_state_path(project_id)
        if read_state(state_path) is None:
            write_state(state_path, initial_state(project_id, pipeline_name, first_phase))
            logger.info(f"project_state.yaml stamped at {state_path}")
    except Exception as exc:  # never block kickoff on a state-file write
        logger.warning(f"project_state.yaml stamp failed for {project_id}: {exc}")

    cyclic = bool(pipeline.get("cyclic"))
    if cyclic:
        # Cyclic pipelines (iterate_artifact) cannot run without goals_md —
        # postmortem + proposers cite §2 metrics from it. Bootstrap from
        # <artifact_repo>/GOALS.md when memory is cold; fail loudly if neither
        # memory nor a GOALS.md file exists.
        try:
            ensure_goals_md(project_id)
        except GoalsBootstrapError as exc:
            raise HTTPException(exc.status_code, str(exc))

        ensure_briefing_md(project_id)

        # Flag the project as iterate-enabled and stamp cycle_n=1 in memory so
        # _maybe_relaunch_cyclic has a baseline to compare against.
        try:
            with get_studio_db() as db:
                db.execute(
                    "UPDATE projects SET iterate_enabled = 1, updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), project_id),
                )
        except Exception as exc:
            logger.warning(f"iterate_enabled flag update failed: {exc}")
        cycle_state.bump_cycle(project_id, 1)
        cycle_state.clear_halt(project_id)

    # Create tasks for each step
    created_tasks = {}
    pending_proposals: list[str] = []
    for idx, step in enumerate(pipeline["steps"]):
        step_id = step["id"]
        task_desc = step["task"].replace("{input}", input_text)
        task_metadata: dict | None = None
        if cyclic:
            task_desc = task_desc.replace("{{iteration_tag}}", "v1").replace("{{cycle_n}}", "1")
            # Only the first step gets the cycle metadata tag; downstream steps
            # in the same cycle inherit via dependency order — the relaunch
            # path writes the metadata afresh on the next cycle's first step.
            if idx == 0:
                task_metadata = {"iteration_tag": "v1", "cycle_n": 1}

        # Resolve dependencies to task IDs
        deps = []
        for dep_name in step.get("depends_on", []):
            if dep_name in created_tasks:
                deps.append(created_tasks[dep_name])

        step_expected = substitute_expected_outputs(
            step.get("expected_outputs"),
            iteration_tag="v1" if cyclic else None,
            cycle_n=1 if cyclic else None,
        )

        task = task_queue.create(TaskCreate(
            project_id=project_id,
            title=f"[{pipeline_name}] {step_id}",
            description=task_desc,
            depends_on=deps,
            created_by=f"pipeline:{pipeline_name}",
            metadata=task_metadata,
            expected_outputs=step_expected,
        ))
        created_tasks[step_id] = task.id

        agent_type = step.get("agent")
        if step.get("type") == "human-gate" or not agent_type:
            continue

        if gated:
            p = proposals_store.create(AgentProposalCreate(
                project_id=project_id,
                agent_type=agent_type,
                rationale=f"Kickoff step `{step_id}` for pipeline `{pipeline_name}`",
                proposer=f"pipeline:{pipeline_name}",
                phase=ProposalPhase.KICKOFF,
                batch_id=batch_id,
                task_id=task.id,
                model_override=task.model_override,
            ))
            pending_proposals.append(p.id)
            continue

        # Fast path: no gate, spawn immediately for ready tasks
        if not deps:
            try:
                instance = registry.spawn(
                    agent_type=agent_type,
                    project_id=project_id,
                    task_id=task.id,
                    model_override=task.model_override,
                )
                task_queue.checkout(task.id, instance.id)
                asyncio.create_task(_run_agent_task(instance, task_desc))
            except ValueError as exc:
                # First failure recorded here. _advance_pipeline handles
                # subsequent retries (up to 3) before blocking + paging.
                count, blocked = task_queue.record_spawn_failure(task.id, str(exc))
                if blocked:
                    logger.error(
                        f"Task {task.id} BLOCKED after {count} failed spawns of "
                        f"'{agent_type}': {exc}"
                    )
                    await ws_manager.broadcast({
                        "type": "spawn_failed",
                        "data": {
                            "task_id": task.id,
                            "project_id": project_id,
                            "agent_type": agent_type,
                            "error": str(exc),
                            "failures": count,
                            "hint": "Check pipelines.yaml agent reference against agents.yaml registry.",
                        },
                    })
                else:
                    logger.warning(
                        f"Agent type '{agent_type}' not found for task {task.id} "
                        f"(attempt {count}/3) — will retry via _advance_pipeline"
                    )

    if gated:
        await ws_manager.broadcast({
            "type": "roster_proposed",
            "data": {
                "pipeline": pipeline_name,
                "project_id": project_id,
                "batch_id": batch_id,
                "proposal_count": len(pending_proposals),
            },
        })
        return {
            "status": "pending_roster_approval",
            "pipeline": pipeline_name,
            "project_id": project_id,
            "batch_id": batch_id,
            "tasks": created_tasks,
            "proposals": pending_proposals,
        }

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

def _resolve_cycle_tag(task) -> tuple[int | None, str | None]:
    """Walk a task's dependency chain until we hit one with metadata.cycle_n.

    Only the first step of a cyclic pipeline gets stamped with
    {"cycle_n": n, "iteration_tag": "v{n}"} (main.py:1274 / :856). Downstream
    tasks in the same cycle inherit implicitly via `depends_on`. To answer
    "which cycle does THIS gate review?" we walk the dep graph up to the
    first-step task and read its metadata. Returns (cycle_n, iteration_tag)
    or (None, None) if no metadata is found within 10 hops.
    """
    seen: set[str] = set()
    cur = task
    for _ in range(10):
        md = cur.metadata or {}
        n = md.get("cycle_n")
        tag = md.get("iteration_tag")
        if n is not None or tag is not None:
            try:
                n_int = int(n) if n is not None else None
            except (TypeError, ValueError):
                n_int = None
            return n_int, tag or (f"v{n_int}" if n_int else None)
        if not cur.depends_on:
            return None, None
        parent_id = cur.depends_on[0]
        if parent_id in seen:
            return None, None
        seen.add(parent_id)
        parent = task_queue.get(parent_id)
        if not parent:
            return None, None
        cur = parent
    return None, None


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
        # Find the preceding step's task along this gate's own dep chain so we
        # don't pick up a sibling from a different cycle (the project can have
        # multiple parallel cycles queued — see _maybe_relaunch_cyclic).
        target_title = f"[{pipeline_name}] {review_of}"
        candidates = []
        for dep_id in task.depends_on or []:
            dep = task_queue.get(dep_id)
            if dep and dep.title == target_title:
                candidates.append(dep)
        if not candidates:
            # Fallback: sibling-by-title (legacy behaviour)
            siblings = task_queue.list_tasks(project_id=task.project_id)
            candidates = [t for t in siblings if t.title == target_title]
        if candidates:
            candidates.sort(key=lambda t: t.updated_at or t.created_at or "", reverse=True)
            top = candidates[0]
            preceding_result = top.result
            review_step = next((s for s in pipeline.get("steps", []) if s.get("id") == review_of), None)
            if review_step:
                preceding_agent = review_step.get("agent")

    cycle_n, iteration_tag = _resolve_cycle_tag(task)
    return {
        "pipeline": pipeline_name,
        "pipeline_label": pipeline.get("name", pipeline_name),
        "step_id": step_id,
        "review_of": review_of,
        "review_of_agent": preceding_agent,
        "prompt": step.get("task", ""),
        "preceding_result": preceding_result,
        "cycle_n": cycle_n,
        "iteration_tag": iteration_tag,
    }


def _engineer_task_prompt(
    engineer_id: str,
    idea_ids: list[str],
    primary_files: list[str],
    iteration_tag: str,
    cycle_n_plus_1: int,
) -> str:
    """Prompt given to each fan-out implement-engineer-{i} sub-task."""
    idea_list = ", ".join(idea_ids) or "(none — see scope card)"
    files_list = ", ".join(primary_files) or "(see scope card)"
    return (
        f"You are engineer {engineer_id} for cycle {cycle_n_plus_1}. "
        f"Your scope is ideas [{idea_list}] touching files [{files_list}]. "
        f"Read FIRST: "
        f"'implementation_brief_{iteration_tag}' (shared design doc + your scope card), "
        f"'selected_ideas_{iteration_tag}', "
        f"'game_html_v{cycle_n_plus_1 - 1}' (current build). "
        f"Work on branch 'eng-{engineer_id}-cycle{cycle_n_plus_1}' inside your own worktree. "
        f"Implement ONLY your scoped ideas. Stay inside your primary_files list; "
        f"if you must edit a file owned by another engineer, stop and write a "
        f"'conflict_note_{engineer_id}_{iteration_tag}' artifact instead. "
        f"When done, commit on your branch, and write "
        f"'engineer_result_{engineer_id}_{iteration_tag}' to memory with: "
        f"{{branch, commit_sha, ideas_implemented[], files_changed[], smoke_ran, notes}}. "
        f"Do NOT merge; the lead engineer does that in the terminal 'implement' step."
    )


def _agent_type_for_engineer(engineer_id: str, primary_files: list[str]) -> str:
    """Map an estimator-provided engineer_id (e.g. 'artist-1', 'telemetry-1',
    'eng-2') to a real implementer agent type.

    Routing hints (in priority order):
      - `artist-*` or any primary_file under `assets/` → technical-artist
        (pulls from 8 free pools via asset_search/asset_fetch + maintains the
         licensed asset_manifest)
      - `telemetry-*` or primary_file named `analytics.mjs` → telemetry-engineer
      - default → frontend-developer
    """
    eid = (engineer_id or "").lower()
    files_lc = [f.lower() for f in (primary_files or [])]
    if eid.startswith("artist") or any(
        f.startswith("assets/") or f.endswith((".png", ".jpg", ".glb", ".svg"))
        for f in files_lc
    ):
        return "technical-artist"
    if eid.startswith("telemetry") or any(
        f.endswith("analytics.mjs") or f.endswith("telemetry.mjs")
        for f in files_lc
    ):
        return "telemetry-engineer"
    return "frontend-developer"


async def _apply_budget_decision(gate_task, ctx: dict, decision: dict) -> dict:
    """Serialise the budget_gate decision and (for parallel mode) fan out engineers.

    Returns a dict merged into the gate task's result:
      - engineers_spawned: [task_ids]  (parallel mode only)
      - budget_cap: int                 (extend_cap mode only)
      - kept_ids: [str]                 (drop_ideas mode only)
    """
    import json as _json

    project_id = gate_task.project_id
    iteration_tag = ctx.get("iteration_tag") or (
        f"v{ctx['cycle_n']}" if ctx.get("cycle_n") else "v1"
    )
    cycle_n = ctx.get("cycle_n") or 1
    cycle_n_plus_1 = cycle_n + 1
    mode = (decision.get("mode") or "").strip().lower()
    pipeline_name = ctx.get("pipeline") or "iterate_artifact"

    # Always persist the decision so downstream steps can branch on it.
    project_memory.write(
        project_id,
        mem_type="artifact",
        key=f"budget_decision_{iteration_tag}",
        content=_json.dumps(
            {
                "mode": mode,
                "extended_cap": decision.get("extended_cap"),
                "kept_ids": decision.get("kept_ids") or [],
                "split": decision.get("split") or [],
                "reason": decision.get("reason") or "",
                "decided_at": datetime.utcnow().isoformat() + "Z",
                "gate_task_id": gate_task.id,
                "cycle_n_plus_1": cycle_n_plus_1,
            },
            indent=2,
        ),
        created_by=f"gate:{gate_task.id}",
    )

    # Locate the downstream implement task so we can patch its deps / metadata.
    siblings = task_queue.list_tasks(project_id=project_id)
    implement_title = f"[{pipeline_name}] implement"
    impl_candidates = [
        t for t in siblings
        if t.title == implement_title and t.status == TaskStatus.PENDING
    ]
    impl_task = None
    if impl_candidates:
        # Pick the impl task whose cycle aligns with this gate.
        for t in impl_candidates:
            t_cycle = (t.metadata or {}).get("cycle_n")
            if t_cycle == cycle_n or t_cycle is None:
                impl_task = t
                break
        if not impl_task:
            impl_task = impl_candidates[0]

    out: dict = {"mode": mode, "iteration_tag": iteration_tag}

    if mode == "extend_cap":
        cap_raw = decision.get("extended_cap")
        try:
            cap = int(cap_raw) if cap_raw is not None else 0
        except (TypeError, ValueError):
            cap = 0
        if cap <= 0:
            raise HTTPException(400, "extend_cap requires a positive 'extended_cap'")
        if impl_task:
            task_queue.merge_metadata(
                impl_task.id,
                {"budget_max_tokens_override": cap, "budget_mode": "extend_cap"},
            )
        out["budget_cap"] = cap

    elif mode == "drop_ideas":
        kept = list(decision.get("kept_ids") or [])
        if not kept:
            raise HTTPException(400, "drop_ideas requires a non-empty 'kept_ids'")
        if impl_task:
            task_queue.merge_metadata(
                impl_task.id,
                {"budget_mode": "drop_ideas", "kept_ids": kept},
            )
        out["kept_ids"] = kept

    elif mode == "parallel":
        split = list(decision.get("split") or [])
        if not split:
            raise HTTPException(400, "parallel requires a non-empty 'split'")

        # prep-brief is the shared design doc. Every engineer depends on it so
        # they don't race the lead, and the implement task then depends on
        # every engineer to act as merge coordinator.
        prep_title = f"[{pipeline_name}] prep-brief"
        prep_candidates = [t for t in siblings if t.title == prep_title]
        prep_task_id = prep_candidates[-1].id if prep_candidates else None
        eng_ids: list[str] = []
        for entry in split:
            engineer_id = str(entry.get("engineer_id") or f"eng-{len(eng_ids) + 1}")
            idea_ids = [str(x) for x in (entry.get("idea_ids") or [])]
            primary_files = [str(x) for x in (entry.get("primary_files") or [])]
            try:
                est_tokens = int(entry.get("est_tokens") or 0)
            except (TypeError, ValueError):
                est_tokens = 0

            agent_type = _agent_type_for_engineer(engineer_id, primary_files)
            metadata = {
                "iteration_tag": iteration_tag,
                "cycle_n": cycle_n,
                "cycle_n_plus_1": cycle_n_plus_1,
                "engineer_id": engineer_id,
                "idea_ids": idea_ids,
                "primary_files": primary_files,
                "est_tokens": est_tokens,
                "agent_type": agent_type,
            }
            # Declare the deliverable contract so validate_outputs can block
            # silent-success runs (see src/runtime/task_validator.py).
            expected_outputs = [
                {
                    "kind": "memory_key",
                    "type": "artifact",
                    "key": f"engineer_result_{engineer_id}_{iteration_tag}",
                    "min_bytes": 40,
                },
                {
                    "kind": "branch_commit",
                    "branch": f"eng-{engineer_id}-cycle{cycle_n_plus_1}",
                },
            ]
            sub = task_queue.create(TaskCreate(
                project_id=project_id,
                title=f"[{pipeline_name}] implement-engineer-{engineer_id}",
                description=_engineer_task_prompt(
                    engineer_id, idea_ids, primary_files, iteration_tag, cycle_n_plus_1
                ),
                assignee_type=agent_type,
                depends_on=[prep_task_id] if prep_task_id else [],
                created_by=f"pipeline:{pipeline_name}",
                metadata=metadata,
                expected_outputs=expected_outputs,
            ))
            eng_ids.append(sub.id)

        if impl_task and eng_ids:
            task_queue.add_dependencies(impl_task.id, eng_ids)
            task_queue.merge_metadata(
                impl_task.id,
                {"budget_mode": "parallel", "engineer_task_ids": eng_ids},
            )
        out["engineers_spawned"] = eng_ids

    else:
        raise HTTPException(400, f"Unknown budget_decision.mode: {mode!r}")

    return out


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
        # Flag gates whose upstream is blocked — the gate will never become
        # ready without human action on the upstream task. Dashboard shows
        # this as a "Upstream blocked" warning with a link to the offender.
        upstream_blocked_ids: list[str] = []
        if t.depends_on and not ready:
            for dep_id in t.depends_on:
                dep = task_queue.get(dep_id)
                if dep and dep.status in (TaskStatus.BLOCKED, TaskStatus.FAILED):
                    upstream_blocked_ids.append(dep_id)
        pending_gates.append({
            "task_id": t.id,
            "title": t.title,
            "ready": ready,
            "upstream_blocked": bool(upstream_blocked_ids),
            "upstream_blocked_ids": upstream_blocked_ids,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            **ctx,
        })
    return pending_gates


class GateDecisionBody(BaseModel):
    feedback: str = ""
    # Synthesis-gate idea bundle: present when the human selects ideas on the
    # IdeaBoard instead of picking one monolithic proposal. Both lists use the
    # Idea schema from the proposer prompts (id/title/hypothesis/…). When
    # either list is non-empty the gate serialises them to
    # `selected_ideas_{iteration_tag}` memory; implement consumes that brief.
    selected: list[dict] | None = None
    custom: list[dict] | None = None
    # Budget-gate decision: {mode: "parallel"|"extend_cap"|"drop_ideas",
    #   extended_cap?: int, kept_ids?: list[str],
    #   split?: list[{engineer_id, idea_ids, est_tokens, primary_files}]}
    # Written to memory as `budget_decision_{iteration_tag}`; on "parallel" the
    # gate fans out N engineer tasks and patches implement's depends_on.
    budget_decision: dict | None = None


def _promote_pick(task, feedback: str) -> str | None:
    """If this is an A/B build pick gate, promote the chosen artifact."""
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

    # Budget gate: the human picks parallel / extend_cap / drop_ideas. We
    # serialise the decision, then dynamically fan out engineer sub-tasks
    # on "parallel" so the terminal `implement` step acts as merge coordinator.
    if (
        ctx.get("step_id") == "budget_gate"
        and body
        and body.budget_decision
    ):
        fanout = await _apply_budget_decision(task, ctx, body.budget_decision)
        result["budget_decision"] = body.budget_decision
        result.update(fanout)

    # Synthesis-gate idea bundle: serialise the human's selection so the
    # implement step has a deterministic brief. The proposer keys stay as-is
    # (they're historical record); selected_ideas_<tag> is the decision log.
    selected = (body.selected if body else None) or []
    custom = (body.custom if body else None) or []
    if selected or custom:
        import json as _json
        tag = ctx.get("iteration_tag") or (
            f"v{ctx['cycle_n']}" if ctx.get("cycle_n") else None
        )
        if tag:
            bundle = {
                "selected": selected,
                "custom": custom,
                "approved_at": datetime.utcnow().isoformat() + "Z",
                "gate_task_id": task.id,
                "feedback": feedback,
            }
            project_memory.write(
                task.project_id,
                mem_type="artifact",
                key=f"selected_ideas_{tag}",
                content=_json.dumps(bundle, indent=2),
                created_by=f"gate:{task.id}",
            )
            result["selected_count"] = len(selected)
            result["custom_count"] = len(custom)
            logger.info(
                f"Gate {task.id}: wrote selected_ideas_{tag} "
                f"({len(selected)} picked + {len(custom)} custom)"
            )
        else:
            logger.warning(
                f"Gate {task.id}: idea bundle present but no iteration_tag — skipped memory write"
            )

    task_queue.update_status(task.id, TaskStatus.COMPLETED, result=result)
    await ws_manager.broadcast({"type": "gate_approved", "data": {"task_id": task.id, "pick_winner": winner}})
    await _advance_pipeline(task.project_id)
    return {"status": "approved", "task_id": task.id}


_SYNTHESIS_ROLE_AGENTS: list[tuple[str, str]] = [
    ("designer", "game-designer"),
    ("ux", "hud-designer"),
    ("artist", "technical-artist"),
    ("proto", "frontend-developer"),
]


@app.post("/api/gates/{task_id}/revise")
async def revise_gate(task_id: str, body: GateDecisionBody):
    """Request changes on the preceding step: spawn revision task(s), leave the gate pending.

    For the synthesis_gate we fan the feedback out to ALL 4 proposers so the
    human can ask for a fresh batch of ideas across every role — matching the
    IdeaBoard's "request changes (all roles)" button. For every other gate we
    revise only the single preceding step (ctx.review_of_agent).
    """
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Gate task not found")
    ctx = _gate_context(task)
    if not ctx:
        raise HTTPException(400, "Task is not a human gate")
    feedback = (body.feedback or "").strip()
    if not feedback:
        raise HTTPException(400, "Feedback required to request changes")

    is_synthesis = (
        ctx.get("step_id") == "synthesis_gate"
        or (ctx.get("review_of") or "").startswith("propose-")
    )
    tag = ctx.get("iteration_tag") or (
        f"v{ctx['cycle_n']}" if ctx.get("cycle_n") else None
    )

    if is_synthesis:
        targets = list(_SYNTHESIS_ROLE_AGENTS)
    else:
        agent_type = ctx.get("review_of_agent")
        if not agent_type:
            raise HTTPException(400, "Gate has no preceding agent step to revise")
        targets = [(ctx.get("review_of") or "previous", agent_type)]

    import json as _json
    from src.database import get_studio_db as _db

    revision_ids: list[str] = []
    new_deps = list(task.depends_on)

    # Look up the original pipeline step so the revision inherits the same
    # expected_outputs contract — otherwise the validator would no-op on
    # revisions and we'd re-introduce the silent-success bug.
    pipeline_cfg = _load_pipelines_yaml().get("pipelines", {}).get(ctx["pipeline"]) or {}
    steps_by_id = {s["id"]: s for s in pipeline_cfg.get("steps") or [] if s.get("id")}

    for role_or_name, agent_type in targets:
        if is_synthesis:
            revise_desc = (
                f"Revise your cycle-{ctx.get('cycle_n') or '?'} ideas for role "
                f"'{role_or_name}' based on human feedback:\n\n{feedback}\n\n"
                "Read 'postmortem_" + (tag or "{{iteration_tag}}") + "' + 'goals_md' "
                "again. Emit a fresh batch of 5-8 ideas in the JSON schema (see "
                "your original task prompt). Overwrite the same memory key "
                f"'proposal_{role_or_name}_{tag or '{{iteration_tag}}'}'."
            )
            title = f"[{ctx['pipeline']}] propose-{role_or_name}-revision"
            original_step_id = f"propose-{role_or_name}"
        else:
            revise_desc = (
                f"Revise the previous {ctx.get('review_of')} output based on human feedback:\n\n"
                f"{feedback}\n\n"
                "Update the same memory artifact keys the original step wrote to."
            )
            title = f"[{ctx['pipeline']}] {ctx.get('review_of')}-revision"
            original_step_id = ctx.get("review_of") or ""

        original_step = steps_by_id.get(original_step_id) or {}
        cycle_n_int = None
        if ctx.get("cycle_n") is not None:
            try:
                cycle_n_int = int(ctx["cycle_n"])
            except (TypeError, ValueError):
                cycle_n_int = None
        revision_expected = substitute_expected_outputs(
            original_step.get("expected_outputs"),
            iteration_tag=tag,
            cycle_n=cycle_n_int,
        )

        revision = task_queue.create(TaskCreate(
            project_id=task.project_id,
            title=title,
            description=revise_desc,
            assignee_type=agent_type,
            created_by=f"pipeline:{ctx['pipeline']}",
            model_override=task.model_override,
            expected_outputs=revision_expected,
        ))
        revision_ids.append(revision.id)
        new_deps.append(revision.id)

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
            logger.warning(f"Failed to spawn {role_or_name} revision for gate {task.id}: {exc}")

    # Gate waits on every spawned revision before re-opening.
    with _db() as db:
        db.execute(
            "UPDATE tasks SET depends_on=?, result=? WHERE id=?",
            (
                _json.dumps(new_deps),
                _json.dumps({
                    "decision": "changes_requested",
                    "feedback": feedback,
                    "revision_task_ids": revision_ids,
                    "fanout_roles": [r for r, _ in targets] if is_synthesis else None,
                }),
                task.id,
            ),
        )

    await ws_manager.broadcast({
        "type": "gate_revision",
        "data": {
            "task_id": task.id,
            "revision_task_ids": revision_ids,
            "fanout": is_synthesis,
        },
    })
    return {
        "status": "revision_requested",
        "task_id": task.id,
        "revision_task_ids": revision_ids,
        "revision_task_id": revision_ids[0] if revision_ids else None,
    }


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


# ==================== Success Criteria ====================

@app.get("/api/projects/{project_id}/criteria")
async def list_criteria(project_id: str):
    return [c.model_dump() for c in criteria_store.list_for_project(project_id)]


@app.post("/api/projects/{project_id}/criteria")
async def create_criterion(project_id: str, body: CriterionCreate, created_by: str = "human"):
    c = criteria_store.create(project_id, body, created_by=created_by)
    await ws_manager.broadcast({"type": "criterion_created", "data": c.model_dump(mode="json")})
    return c.model_dump()


@app.get("/api/criteria/{criterion_id}")
async def get_criterion(criterion_id: str):
    c = criteria_store.get(criterion_id)
    if not c:
        raise HTTPException(404, "Criterion not found")
    return c.model_dump()


@app.patch("/api/criteria/{criterion_id}")
async def update_criterion(criterion_id: str, body: CriterionUpdate):
    c = criteria_store.update(criterion_id, body)
    if not c:
        raise HTTPException(404, "Criterion not found")
    await ws_manager.broadcast({"type": "criterion_updated", "data": c.model_dump(mode="json")})
    return c.model_dump()


@app.delete("/api/criteria/{criterion_id}")
async def delete_criterion(criterion_id: str):
    ok = criteria_store.delete(criterion_id)
    if not ok:
        raise HTTPException(404, "Criterion not found")
    await ws_manager.broadcast({"type": "criterion_deleted", "data": {"id": criterion_id}})
    return {"status": "deleted"}


class LinkCriterionBody(BaseModel):
    criterion_id: str | None = None


@app.post("/api/tasks/{task_id}/link-criterion")
async def link_task_criterion(task_id: str, body: LinkCriterionBody):
    ok = criteria_store.link_task(task_id, body.criterion_id)
    if not ok:
        raise HTTPException(404, "Task not found")
    return {"status": "linked", "task_id": task_id, "criterion_id": body.criterion_id}


# ==================== Documents (revisioned) ====================

class DocumentCreateBody(BaseModel):
    category: str
    slug: str
    title: str
    content: str
    change_summary: str = ""


class DocumentReviseBody(BaseModel):
    content: str
    change_summary: str = ""
    title: str | None = None


class DocumentMetaBody(BaseModel):
    title: str | None = None
    status: str | None = None


@app.get("/api/projects/{project_id}/docs")
async def list_project_docs(project_id: str, category: str | None = None):
    return project_docs.list_docs(project_id, category=category)


@app.post("/api/projects/{project_id}/docs")
async def create_project_doc(project_id: str, body: DocumentCreateBody, created_by: str = "human"):
    try:
        doc_id, version = project_docs.write(
            project_id=project_id,
            category=body.category,
            slug=body.slug,
            title=body.title,
            content=body.content,
            change_summary=body.change_summary,
            created_by=created_by,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await ws_manager.broadcast({"type": "doc_written", "data": {"document_id": doc_id, "version": version, "project_id": project_id}})
    return {"document_id": doc_id, "version": version}


@app.post("/api/docs/{doc_id}/revisions")
async def revise_doc(doc_id: str, body: DocumentReviseBody, created_by: str = "human"):
    doc = project_docs.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    doc_id2, version = project_docs.write(
        project_id=doc["project_id"],
        category=doc["category"],
        slug=doc["slug"],
        title=body.title or doc["title"],
        content=body.content,
        change_summary=body.change_summary,
        created_by=created_by,
    )
    await ws_manager.broadcast({"type": "doc_revised", "data": {"document_id": doc_id2, "version": version}})
    return {"document_id": doc_id2, "version": version}


@app.get("/api/docs/{doc_id}")
async def get_doc_latest(doc_id: str):
    doc = project_docs.read_by_id(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@app.get("/api/docs/{doc_id}/revisions")
async def get_doc_history(doc_id: str):
    return project_docs.history(doc_id)


@app.get("/api/docs/{doc_id}/revisions/{version}")
async def get_doc_version(doc_id: str, version: int):
    doc = project_docs.read_by_id(doc_id, version=version)
    if not doc:
        raise HTTPException(404, "Document or version not found")
    return doc


@app.patch("/api/docs/{doc_id}")
async def patch_doc_meta(doc_id: str, body: DocumentMetaBody):
    doc = project_docs.update_meta(doc_id, title=body.title, status=body.status)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


# ==================== Agent Proposals (roster approval) ====================

@app.get("/api/governance/proposals")
async def list_proposals(project_id: str | None = None, batch_id: str | None = None, status: str | None = None):
    st = ProposalStatus(status) if status else None
    return [p.model_dump(mode="json") for p in proposals_store.list_proposals(
        project_id=project_id, batch_id=batch_id, status=st,
    )]


@app.post("/api/governance/proposals")
async def create_proposal(body: AgentProposalCreate):
    p = proposals_store.create(body)
    await ws_manager.broadcast({"type": "proposal_created", "data": p.model_dump(mode="json")})
    return p.model_dump(mode="json")


@app.post("/api/governance/proposals/batch/{batch_id}/approve")
async def approve_proposal_batch(batch_id: str, body: BatchDecision):
    approved = proposals_store.approve_batch(
        batch_id=batch_id,
        decided_by=body.decided_by,
        keep_proposal_ids=body.keep_proposal_ids,
    )
    spawned = []
    for p in approved:
        inst = await _spawn_from_approved_proposal(p.id)
        if inst:
            spawned.append(inst.id)
    await ws_manager.broadcast({
        "type": "roster_approved",
        "data": {"batch_id": batch_id, "approved": [p.id for p in approved], "spawned": spawned},
    })
    return {"status": "approved", "batch_id": batch_id, "approved": [p.id for p in approved], "spawned": spawned}


@app.post("/api/governance/proposals/batch/{batch_id}/reject")
async def reject_proposal_batch(batch_id: str, body: SingleDecision):
    rejected = proposals_store.reject_batch(batch_id=batch_id, decided_by=body.decided_by)
    await ws_manager.broadcast({
        "type": "roster_rejected",
        "data": {"batch_id": batch_id, "rejected": [p.id for p in rejected], "reason": body.reason},
    })
    return {"status": "rejected", "batch_id": batch_id, "rejected": [p.id for p in rejected]}


@app.post("/api/governance/proposals/{proposal_id}/approve")
async def approve_single_proposal(proposal_id: str, body: SingleDecision):
    p = proposals_store.approve(proposal_id, decided_by=body.decided_by)
    if not p:
        raise HTTPException(404, "Proposal not found or not pending")
    inst = await _spawn_from_approved_proposal(proposal_id)
    return {"status": "approved", "proposal_id": proposal_id, "spawned": inst.id if inst else None}


@app.post("/api/governance/proposals/{proposal_id}/reject")
async def reject_single_proposal(proposal_id: str, body: SingleDecision):
    p = proposals_store.reject(proposal_id, decided_by=body.decided_by)
    if not p:
        raise HTTPException(404, "Proposal not found or not pending")
    return {"status": "rejected", "proposal_id": proposal_id}


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
