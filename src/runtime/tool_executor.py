"""Tool Executor — shared tool pool with governance enforcement."""
from __future__ import annotations

import asyncio
import json
import subprocess
import re
import yaml
from pathlib import Path
from datetime import datetime, timezone

from src.models.governance import GovernanceDecision, ToolPermission, ApprovalRequest
from src.models.llm import ToolResult
from src.database import get_studio_db
from src.settings import settings


class ToolExecutor:
    def __init__(self):
        self._governance: dict[str, ToolPermission] = {}
        self._pre_approved_prefixes: list[str] = []  # e.g. "mcp__" -> auto-approved
        self._tool_registry: dict[str, callable] = {}
        self._tool_schemas: dict[str, dict] = {}
        self._pending_approvals: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, bool] = {}
        self._register_builtin_tools()

    def load_governance(self, config_path: str = None):
        """Load tool governance tiers from governance.yaml."""
        path = Path(config_path or f"{settings.config_dir}/governance.yaml")
        if not path.exists():
            return

        with open(path) as f:
            data = yaml.safe_load(f)

        for tool_name in data.get("builtin", []):
            self._governance[tool_name] = ToolPermission.BUILTIN
        for tool_name in data.get("pre_approved", []):
            self._governance[tool_name] = ToolPermission.PRE_APPROVED
        for tool_name in data.get("restricted", []):
            self._governance[tool_name] = ToolPermission.RESTRICTED
        for tool_name in data.get("blocked", []):
            self._governance[tool_name] = ToolPermission.BLOCKED

        # Prefix-based auto-approval (Claude Code plugin surface)
        self._pre_approved_prefixes = list(data.get("claude_plugins_prefixes", []))

    # --- Governance ---

    def check_permission(
        self, tool_name: str, agent_instance_id: str, params: dict = None
    ) -> GovernanceDecision:
        """Check if a tool call is allowed, needs approval, or is blocked."""
        tier = self._governance.get(tool_name)

        if tier is None:
            # Prefix-based auto-approval (e.g. mcp__*) — user already enabled
            # these plugins in Claude Code so we don't prompt again.
            for prefix in self._pre_approved_prefixes:
                if tool_name.startswith(prefix):
                    tier = ToolPermission.PRE_APPROVED
                    break

        if tier is None:
            # Unknown tool — treat as restricted
            tier = ToolPermission.RESTRICTED

        if tier == ToolPermission.BLOCKED:
            self._log_governance(agent_instance_id, tool_name, params, "blocked", "Tool is blocked")
            return GovernanceDecision.BLOCKED

        if tier in (ToolPermission.BUILTIN, ToolPermission.PRE_APPROVED):
            self._log_governance(agent_instance_id, tool_name, params, "allowed", f"Tier: {tier.value}")
            return GovernanceDecision.ALLOWED

        if tier == ToolPermission.RESTRICTED:
            self._log_governance(
                agent_instance_id, tool_name, params, "pending_approval", "Restricted tool"
            )
            return GovernanceDecision.PENDING_APPROVAL

        return GovernanceDecision.DENIED

    async def request_approval(
        self, agent_instance_id: str, tool_name: str, params: dict = None
    ) -> bool:
        """Submit an approval request and wait for human decision."""
        with get_studio_db() as db:
            cursor = db.execute(
                """INSERT INTO approval_queue (agent_instance_id, tool_name, params, status)
                   VALUES (?, ?, ?, 'pending')""",
                (agent_instance_id, tool_name, json.dumps(params or {})),
            )
            request_id = str(cursor.lastrowid)

        # Create an event for this approval
        event = asyncio.Event()
        self._pending_approvals[request_id] = event

        # Wait for human decision (via dashboard API)
        try:
            await asyncio.wait_for(event.wait(), timeout=300.0)  # 5 min timeout
            return self._approval_results.get(request_id, False)
        except asyncio.TimeoutError:
            # Auto-deny on timeout
            self.resolve_approval(request_id, approved=False, decided_by="system-timeout")
            return False

    def resolve_approval(self, request_id: str, approved: bool, decided_by: str = "human"):
        """Resolve a pending approval (called by dashboard API)."""
        status = "approved" if approved else "denied"
        with get_studio_db() as db:
            db.execute(
                """UPDATE approval_queue SET status = ?, decided_by = ?, decided_at = ?
                   WHERE id = ?""",
                (status, decided_by, datetime.now(timezone.utc).isoformat(), request_id),
            )

        self._approval_results[request_id] = approved
        event = self._pending_approvals.pop(request_id, None)
        if event:
            event.set()

    def list_pending_approvals(self) -> list[dict]:
        """List all pending approval requests."""
        with get_studio_db() as db:
            rows = db.execute(
                "SELECT * FROM approval_queue WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Tool Execution ---

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        agent_instance_id: str,
        project_id: str = None,
    ) -> ToolResult:
        """Execute a tool with governance checks."""
        # Check permission
        decision = self.check_permission(tool_name, agent_instance_id, arguments)

        if decision == GovernanceDecision.BLOCKED:
            return ToolResult(
                tool_call_id="",
                content=f"Tool '{tool_name}' is blocked by governance policy.",
                is_error=True,
            )

        if decision == GovernanceDecision.PENDING_APPROVAL:
            approved = await self.request_approval(agent_instance_id, tool_name, arguments)
            if not approved:
                return ToolResult(
                    tool_call_id="",
                    content=f"Tool '{tool_name}' was denied by human reviewer.",
                    is_error=True,
                )

        # MCP bridge handles tools named mcp__<server>__<tool>.
        if tool_name.startswith("mcp__"):
            from src.runtime.mcp_bridge import mcp_bridge
            try:
                content = await mcp_bridge.call_tool(tool_name, arguments)
            except Exception as e:
                return ToolResult(tool_call_id="", content=f"MCP error: {e}", is_error=True)
            is_err = content.startswith("ERROR:") or content.startswith("MCP call error")
            return ToolResult(tool_call_id="", content=content, is_error=is_err)

        # Execute the tool
        handler = self._tool_registry.get(tool_name)
        if not handler:
            return ToolResult(
                tool_call_id="",
                content=f"Tool '{tool_name}' is not registered.",
                is_error=True,
            )

        try:
            result = await handler(
                arguments, project_id=project_id, agent_instance_id=agent_instance_id,
            )
            return ToolResult(tool_call_id="", content=str(result), is_error=False)
        except Exception as e:
            return ToolResult(tool_call_id="", content=f"Tool error: {e}", is_error=True)

    def get_tool_schemas(self, tool_names: list[str] = None) -> list[dict]:
        """Get tool schemas for LLM prompt injection. Optionally filter by name list."""
        if tool_names:
            return [self._tool_schemas[n] for n in tool_names if n in self._tool_schemas]
        return list(self._tool_schemas.values())

    def list_tool_catalog(self) -> list[dict]:
        """All known tools with their governance tier and schema, for the dashboard.

        Includes native Code PLAY tools plus MCP tools discovered from Claude Code
        plugins (via mcp_bridge). MCP tools get the pre_approved tier because the
        user explicitly enabled them in Claude Code.
        """
        tiers = set(self._governance.keys()) | set(self._tool_schemas.keys())
        catalog = []
        for name in sorted(tiers):
            tier = self._governance.get(name)
            schema = self._tool_schemas.get(name, {})
            catalog.append({
                "name": name,
                "tier": tier.value if tier else "unconfigured",
                "description": schema.get("description", ""),
                "has_handler": name in self._tool_registry,
                "parameters": schema.get("parameters", {}),
                "source": "native",
            })
        # MCP tools (discovered from Claude Code plugins)
        try:
            from src.runtime.mcp_bridge import mcp_bridge
            for entry in mcp_bridge.catalog_entries():
                # claude_plugins renders as 'pre_approved' in the UI tier logic;
                # keep the distinct tag too so the dashboard can group by origin.
                entry = {**entry, "tier": "pre_approved"}
                catalog.append(entry)
        except Exception:
            pass
        return catalog

    # --- Builtin Tool Implementations ---

    def _register_builtin_tools(self):
        """Register all builtin tool handlers and their schemas."""

        # file_read
        self._register("file_read", self._tool_file_read, {
            "name": "file_read",
            "description": "Read the contents of a file relative to the project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to read"},
                },
                "required": ["path"],
            },
        })

        # file_write
        self._register("file_write", self._tool_file_write, {
            "name": "file_write",
            "description": "Write content to a file relative to the project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to write"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        })

        # bash_execute
        self._register("bash_execute", self._tool_bash_execute, {
            "name": "bash_execute",
            "description": "Execute a shell command in the project directory. Use for builds, tests, installs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)", "default": 60},
                },
                "required": ["command"],
            },
        })

        # git_status
        self._register("git_status", self._tool_git_status, {
            "name": "git_status",
            "description": "Show the git status of the project.",
            "parameters": {"type": "object", "properties": {}},
        })

        # git_add
        self._register("git_add", self._tool_git_add, {
            "name": "git_add",
            "description": "Stage files for git commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Files to stage"},
                },
                "required": ["paths"],
            },
        })

        # git_commit
        self._register("git_commit", self._tool_git_commit, {
            "name": "git_commit",
            "description": "Create a git commit with a message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                },
                "required": ["message"],
            },
        })

        # git_diff
        self._register("git_diff", self._tool_git_diff, {
            "name": "git_diff",
            "description": "Show git diff of current changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "Show staged changes", "default": False},
                },
            },
        })

        # web_search — classic keyword search via DuckDuckGo HTML (no key needed)
        self._register("web_search", self._tool_web_search, {
            "name": "web_search",
            "description": (
                "Classic web search. Returns a list of result URLs + titles + snippets "
                "via DuckDuckGo HTML (no key needed). Good when you want to pick which "
                "pages to read yourself. For synthesized answers with citations use "
                "`perplexity_research` instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (keywords or natural language)"},
                    "limit": {"type": "integer", "description": "Max results (default 8, max 20)"},
                },
                "required": ["query"],
            },
        })

        # perplexity_research — synthesized answer + citations via Perplexity Sonar
        self._register("perplexity_research", self._tool_perplexity_research, {
            "name": "perplexity_research",
            "description": (
                "Deep research via Perplexity Sonar. Returns a synthesized answer "
                "with citation URLs. Best for multi-source questions like 'what are "
                "top Roblox obbies by traction?' Requires PERPLEXITY_API_KEY."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language research question"},
                    "depth": {
                        "type": "string",
                        "enum": ["quick", "standard", "deep"],
                        "description": "quick=sonar, standard=sonar-pro, deep=sonar-reasoning",
                    },
                    "recency": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Bias toward recent content. Omit for unfiltered.",
                    },
                },
                "required": ["query"],
            },
        })

        # channel_post
        self._register("channel_post", self._tool_channel_post, {
            "name": "channel_post",
            "description": "Post a message to a project channel for other agents to see.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel name (general, review, decisions)"},
                    "content": {"type": "string", "description": "Message content"},
                    "mentions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to @-mention",
                    },
                },
                "required": ["channel", "content"],
            },
        })

        # channel_read
        self._register("channel_read", self._tool_channel_read, {
            "name": "channel_read",
            "description": "Read recent messages from a project channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel name"},
                    "limit": {"type": "integer", "description": "Max messages to return", "default": 20},
                },
                "required": ["channel"],
            },
        })

        # escalate
        self._register("escalate", self._tool_escalate, {
            "name": "escalate",
            "description": "Escalate a question or decision to the human operator. Blocks until answered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question for the human"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional choices",
                    },
                    "context": {"type": "string", "description": "Background context"},
                },
                "required": ["question"],
            },
        })

        # memory_read
        self._register("memory_read", self._tool_memory_read, {
            "name": "memory_read",
            "description": "Read from project memory by type and key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Memory type (decision, artifact, feedback, context)"},
                    "key": {"type": "string", "description": "Memory key to look up"},
                },
                "required": ["type", "key"],
            },
        })

        # memory_write
        self._register("memory_write", self._tool_memory_write, {
            "name": "memory_write",
            "description": "Write to project memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Memory type (decision, artifact, feedback, context)"},
                    "key": {"type": "string", "description": "Memory key"},
                    "content": {"type": "string", "description": "Content to store"},
                },
                "required": ["type", "key", "content"],
            },
        })

        # memory_search
        self._register("memory_search", self._tool_memory_search, {
            "name": "memory_search",
            "description": "Search project memory by keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "type": {"type": "string", "description": "Optional filter by memory type"},
                },
                "required": ["query"],
            },
        })

        # file_edit — exact string replacement in an existing file
        self._register("file_edit", self._tool_file_edit, {
            "name": "file_edit",
            "description": (
                "Edit a file by replacing an exact string. old_string must appear exactly once "
                "unless replace_all=true. Use for surgical edits instead of rewriting a file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path to edit"},
                    "old_string": {"type": "string", "description": "Exact text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        })

        # grep — regex search across project files (via ripgrep if available)
        self._register("grep", self._tool_grep, {
            "name": "grep",
            "description": "Search file contents with a regex. Returns matching lines with file:line prefixes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "Subdirectory to search (default: project root)"},
                    "glob": {"type": "string", "description": "Optional filename filter (e.g. '*.py')"},
                    "case_insensitive": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 100},
                },
                "required": ["pattern"],
            },
        })

        # glob — find files by glob pattern
        self._register("glob", self._tool_glob, {
            "name": "glob",
            "description": "Find files matching a glob pattern (e.g. '**/*.ts'). Returns paths sorted by modified time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.html'"},
                    "path": {"type": "string", "description": "Subdirectory (default: project root)"},
                },
                "required": ["pattern"],
            },
        })

        # web_fetch — download a URL and return text content
        self._register("web_fetch", self._tool_web_fetch, {
            "name": "web_fetch",
            "description": "Fetch a URL and return its body as text. Use for downloading documentation, asset manifests, or small reference pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Absolute URL (http/https)"},
                    "max_bytes": {"type": "integer", "description": "Truncate body to this many bytes", "default": 200000},
                },
                "required": ["url"],
            },
        })

        # skill_invoke — read a Claude Code skill's markdown body
        self._register("skill_invoke", self._tool_skill_invoke, {
            "name": "skill_invoke",
            "description": (
                "Retrieve a Claude Code skill's full instructions by id (e.g. 'superpowers:brainstorming' "
                "or 'email-digest'). Returns the skill markdown body. Use before starting a task that "
                "matches a skill's description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "Skill id from the skill catalog"},
                },
                "required": ["skill_id"],
            },
        })

        # task_create — agent-to-agent task delegation
        self._register("task_create", self._tool_task_create, {
            "name": "task_create",
            "description": (
                "Create a follow-up task for another agent to pick up. Use this to delegate work, "
                "file bugs, or queue QA/review steps. The task appears on the kanban board tagged as "
                "agent-created. Depends_on lets you chain work (task runs only after listed tasks complete)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title (imperative, e.g. 'Run QA on game.html')"},
                    "description": {"type": "string", "description": "Full task description with context and acceptance criteria"},
                    "priority": {"type": "integer", "description": "0 = normal, higher = more urgent", "default": 0},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task IDs that must complete before this one runs",
                    },
                    "parent_task_id": {"type": "string", "description": "Optional parent task ID (for subtasks)"},
                    "assignee_type": {
                        "type": "string",
                        "description": (
                            "Optional agent-type hint (e.g. 'qa-engineer', 'frontend-developer'). "
                            "If set, the orchestrator auto-spawns that agent when the task is ready."
                        ),
                    },
                },
                "required": ["title"],
            },
        })

        # asset_search — search shared visual asset pools
        self._register("asset_search", self._tool_asset_search, {
            "name": "asset_search",
            "description": (
                "Search shared asset pools for game art, audio, textures, and 3D models. "
                "Pools: kenney (CC0 2D/audio), itch (mixed), polyhaven (CC0 HDRI/PBR/3D), "
                "ambientcg (CC0 PBR), quaternius (CC0 3D), pixabay (photos/video/music, free-key), "
                "freesound (SFX, free-key), oga (OpenGameArt CC0 filter). "
                "Returns {pool, asset_id, title, page_url, preview_url, license, content_type, tags}. "
                "'all' fans out across free/no-key pools. Always search BEFORE proposing a visual direction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords e.g. 'pixel platformer hero', 'low-poly forest'"},
                    "pool": {
                        "type": "string",
                        "enum": ["kenney", "itch", "polyhaven", "ambientcg", "quaternius",
                                 "pixabay", "freesound", "oga", "both", "all"],
                        "default": "both",
                    },
                    "limit": {"type": "integer", "description": "Max hits per pool (default 6)", "default": 6},
                    "kind": {
                        "type": "string",
                        "description": "polyhaven/pixabay filter: 'hdris'|'textures'|'models'|'image'|'video'|'music'",
                    },
                },
                "required": ["query"],
            },
        })

        # playwright_browser — headless browser driver for QA playtests
        self._register("playwright_browser", self._tool_playwright_browser, {
            "name": "playwright_browser",
            "description": (
                "Drive a headless Chromium session against a URL or project-relative HTML. "
                "Actions: open (returns {title, has_canvas, has_webgl, has_game_hook}), key "
                "(Playwright key e.g. 'KeyW', 'Space'), key_sequence (hold multiple keys for "
                "hold_ms), click ({x,y}), evaluate ({expr} → returns value), screenshot "
                "({path, full}), wait ({ms}). Use for QA: launch game_html_v1, assert "
                "window.__game exists, drive each verb in mechanics_v1, screenshot milestones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL or project-relative HTML path"},
                    "action": {
                        "type": "string",
                        "enum": ["open", "key", "key_sequence", "click", "evaluate", "screenshot", "wait"],
                        "default": "open",
                    },
                    "payload": {"type": "object", "description": "Action-specific payload"},
                    "timeout_ms": {"type": "integer", "default": 8000},
                },
                "required": ["action"],
            },
        })

        # update_criterion_status — qa/producer flip criteria as evidence accrues
        self._register("update_criterion_status", self._tool_update_criterion_status, {
            "name": "update_criterion_status",
            "description": (
                "Update a project success criterion's status. Use when evidence shows a criterion "
                "is met, in progress, or failed. Criterion ids come from the Goal Ancestry block."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "criterion_id": {"type": "string", "description": "Criterion id (e.g. 'crit-abc123def0')"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "met", "failed"]},
                    "note": {"type": "string", "description": "Optional evidence / reasoning"},
                },
                "required": ["criterion_id", "status"],
            },
        })

        # document_write — create or append a revision to a structured project doc
        self._register("document_write", self._tool_document_write, {
            "name": "document_write",
            "description": (
                "Write a structured project document (design/architecture/testing/analytics/notes). "
                "Creates version 1 on first write, appends a new revision otherwise. Content is mirrored "
                "to docs/{category}/{slug}.md inside the project workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["design", "architecture", "testing", "analytics", "notes"]},
                    "slug": {"type": "string", "description": "Stable filename stem, e.g. 'mvp-plan'"},
                    "title": {"type": "string", "description": "Human-readable title"},
                    "content": {"type": "string", "description": "Full markdown body"},
                    "change_summary": {"type": "string", "description": "Brief note describing this revision", "default": ""},
                },
                "required": ["category", "slug", "title", "content"],
            },
        })

        # document_read — fetch latest or specific version of a structured doc
        self._register("document_read", self._tool_document_read, {
            "name": "document_read",
            "description": "Read a project document by category + slug. Returns latest version by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["design", "architecture", "testing", "analytics", "notes"]},
                    "slug": {"type": "string"},
                    "version": {"type": "integer", "description": "Optional specific version"},
                },
                "required": ["category", "slug"],
            },
        })

        # propose_agent — lead/producer suggests adding an agent (human approves)
        self._register("propose_agent", self._tool_propose_agent, {
            "name": "propose_agent",
            "description": (
                "Propose adding an agent to this project. Creates an in-flight proposal that a human "
                "must approve before the agent spawns. Use when the current roster is missing a "
                "capability you need (e.g. 'sound designer for SFX pass')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_type": {"type": "string", "description": "Agent type id from the catalog"},
                    "rationale": {"type": "string", "description": "Why this agent is needed now"},
                    "model_override": {"type": "string", "description": "Optional non-default model"},
                },
                "required": ["agent_type", "rationale"],
            },
        })

        # iteration_runner — wraps run_playtest_batch for qa-engineer
        self._register("iteration_runner", self._tool_iteration_runner, {
            "name": "iteration_runner",
            "description": (
                "Run a headless playtest batch for one iteration cycle. Spawns "
                "`python3 -m http.server` rooted at the artifact repo, shells "
                "`node playtest_bot.mjs --runs N --tag v{cycle_n}` against it, "
                "aggregates telemetry JSONs whose iteration_tag matches, persists "
                "the rollup to project memory as artifact 'telemetry_v{cycle_n}', "
                "and returns the rollup + node exit info. Use this tool in the "
                "`playtest` step of iterate_artifact — do NOT shell python/node "
                "yourself; do NOT try to read src/iteration/iterate_runner.py."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the artifact repo (contains playtest_bot.mjs + telemetry/)"},
                    "cycle_n": {"type": "integer", "description": "Cycle number; tag becomes v{cycle_n}"},
                    "runs": {"type": "integer", "description": "Runs per batch (default 5)", "default": 5},
                    "seconds_per_run": {"type": "integer", "description": "Seconds per run (default 60)", "default": 60},
                    "game_entry": {"type": "string", "description": "HTML entry (default index.html)", "default": "index.html"},
                    "bot_script": {"type": "string", "description": "Bot script name (default playtest_bot.mjs)", "default": "playtest_bot.mjs"},
                },
                "required": ["repo_path", "cycle_n"],
            },
        })

        # external_repo_commit — write files into an external repo and commit (no push)
        self._register("external_repo_commit", self._tool_external_repo_commit, {
            "name": "external_repo_commit",
            "description": (
                "Write one or more files into an external git repository (outside "
                "the agent sandbox) and commit them. Use this in `implement` or "
                "`scaffold-iteration` steps that produce artifacts living in a "
                "project's game repo — e.g. writing game_html_v{n} to "
                "butt-shooting-game on its iteration branch, or scaffolding "
                "ITERATION_CONTRACT.md + GOALS.md + playtest_bot.mjs. Stages only "
                "the written files; optionally checks out a branch first; does "
                "NOT push. Returns the commit SHA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the external git repo"},
                    "files": {
                        "type": "array",
                        "description": "Files to write relative to repo_path",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                    "message": {"type": "string", "description": "Commit message"},
                    "branch": {"type": "string", "description": "Optional branch to check out before writing/committing (created if absent)"},
                    "allow_empty": {"type": "boolean", "description": "Allow empty commit (default false)", "default": False},
                },
                "required": ["repo_path", "files", "message"],
            },
        })

        # repo_file_read — read a file from the artifact repo (outside sandbox)
        self._register("repo_file_read", self._tool_repo_file_read, {
            "name": "repo_file_read",
            "description": (
                "Read a file from the project's artifact repository (outside the "
                "agent sandbox). Use memory key 'artifact_repo_path' for the repo "
                "root. Path is relative to repo root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the artifact repo root"},
                    "path": {"type": "string", "description": "Relative file path within the repo"},
                },
                "required": ["repo_path", "path"],
            },
        })

        # repo_file_write — write a file to the artifact repo (outside sandbox)
        self._register("repo_file_write", self._tool_repo_file_write, {
            "name": "repo_file_write",
            "description": (
                "Write a file to the project's artifact repository (outside the "
                "agent sandbox). Does NOT commit — use external_repo_commit after. "
                "Use memory key 'artifact_repo_path' for the repo root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the artifact repo root"},
                    "path": {"type": "string", "description": "Relative file path within the repo"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["repo_path", "path", "content"],
            },
        })

        # repo_file_list — list files in the artifact repo
        self._register("repo_file_list", self._tool_repo_file_list, {
            "name": "repo_file_list",
            "description": (
                "List files in the project's artifact repository. Returns file "
                "names and sizes. Use memory key 'artifact_repo_path' for the repo root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the artifact repo root"},
                    "subdir": {"type": "string", "description": "Optional subdirectory to list (default: repo root)"},
                },
                "required": ["repo_path"],
            },
        })

        # scaffold_iteration — write the 4-file iteration kit into an artifact repo
        self._register("scaffold_iteration", self._tool_scaffold_iteration, {
            "name": "scaffold_iteration",
            "description": (
                "Scaffold the iteration kit (ITERATION_CONTRACT.md, GOALS.md, "
                "playtest_bot.mjs, telemetry/.gitkeep, .codeplay/config.yaml) "
                "into a newly-built game's artifact repo. Use this in the "
                "`scaffold-iteration` tail step of phased-producer. Do NOT try "
                "to import src.iteration.scaffolder yourself — your sandbox is "
                "scoped to your worktree. This tool IS the binding. After it "
                "returns, the files exist on disk and paths are saved to "
                "project memory (iteration_contract_path, goals_path, "
                "playtest_bot_path). You still need to stage + commit them with "
                "`external_repo_commit` if you want them in the repo history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_dir": {"type": "string", "description": "Absolute path to artifact repo root"},
                    "project_title": {"type": "string", "description": "Human-readable title for GOALS.md preamble"},
                    "game_url": {"type": "string", "description": "Local game URL for the bot to drive (default http://localhost:8765/index.html)"},
                },
                "required": ["artifact_dir"],
            },
        })

        # generate_bot — QA engineer writes a game-specific playtest bot
        self._register("generate_bot", self._tool_generate_bot, {
            "name": "generate_bot",
            "description": (
                "Generate or update a game-specific playtest_bot.mjs in an "
                "artifact repo. The QA engineer calls this after analyzing the "
                "game's GameAPI shape to write a bot that can actually play the "
                "game (targeting enemies, handling pickers, matching the input "
                "scheme) instead of random-walking. Validates that the bot "
                "references GameAPI (not window.__game), syntax-checks with "
                "`node --check`, and commits the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the game's artifact repo"},
                    "game_analysis": {
                        "type": "string",
                        "description": (
                            "Brief analysis of the game: genre, input scheme, "
                            "GameAPI snapshot shape, win/lose conditions. Stored "
                            "alongside the bot for future reference."
                        ),
                    },
                    "bot_code": {"type": "string", "description": "Full content of playtest_bot.mjs"},
                    "message": {"type": "string", "description": "Commit message for the bot update"},
                },
                "required": ["repo_path", "bot_code", "message"],
            },
        })

        # itchio_publish — butler push
        self._register("itchio_publish", self._tool_itchio_publish, {
            "name": "itchio_publish",
            "description": (
                "Publish a flat HTML5 build to itch.io via butler. Requires butler "
                "on PATH (or at ~/.local/bin/butler) and BUTLER_API_KEY env or "
                "~/.config/itch/butler_creds. The itch.io game page must already "
                "exist — butler cannot create it. Returns manifest JSON with "
                "target_url + butler status output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "build_dir": {"type": "string", "description": "Absolute path to flat build dir (must contain index.html)"},
                    "target": {"type": "string", "description": "itch.io target 'user/slug:channel', e.g. dknanlin/butt-shooting-game:html"},
                    "version": {"type": "string", "description": "Optional --userversion string"},
                },
                "required": ["build_dir", "target"],
            },
        })

        # gh_pages_publish — commit build to gh-pages branch + push
        self._register("gh_pages_publish", self._tool_gh_pages_publish, {
            "name": "gh_pages_publish",
            "description": (
                "Publish a flat build to GitHub Pages by committing to the "
                "gh-pages branch under docs/<slug>/ and pushing to origin. "
                "Requires git + a remote named origin. Returns manifest JSON "
                "with the deduced target_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to the repo with (or willing to have) a gh-pages branch"},
                    "build_dir": {"type": "string", "description": "Absolute path to the flat build to publish"},
                    "slug": {"type": "string", "description": "Path segment under docs/ on gh-pages"},
                    "message": {"type": "string", "description": "Commit message (default 'Publish <slug>')"},
                },
                "required": ["repo_path", "build_dir", "slug"],
            },
        })

        # roblox_publish — Open Cloud PATCH a place
        self._register("roblox_publish", self._tool_roblox_publish, {
            "name": "roblox_publish",
            "description": (
                "Publish a .rbxl place file via Roblox Open Cloud. Requires "
                "ROBLOX_API_KEY with place-publish scope for the target "
                "universe. Returns versionNumber + target_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rbxl_path": {"type": "string", "description": "Absolute path to .rbxl file"},
                    "universe_id": {"type": "string", "description": "Roblox universe ID"},
                    "place_id": {"type": "string", "description": "Roblox place ID to publish over"},
                    "version_type": {"type": "string", "description": "Saved | Published (default Published)", "default": "Published"},
                },
                "required": ["rbxl_path", "universe_id", "place_id"],
            },
        })

        # asset_fetch — download an asset's preview or zip into the workspace
        self._register("asset_fetch", self._tool_asset_fetch, {
            "name": "asset_fetch",
            "description": (
                "Download an asset from a shared pool into the project workspace. "
                "asset_id format is '<pool>:<slug>' (from asset_search). "
                "kind='preview' grabs the thumbnail. kind='content' grabs the real asset "
                "(zip for packs, image/hdr for polyhaven, audio MP3 for freesound, etc.). "
                "Non-CC0 content requires accept_attribution=true; when set, a CREDITS.md line "
                "is appended automatically. Returns the saved relative path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "Asset id from asset_search, e.g. polyhaven:rocky_terrain"},
                    "kind": {"type": "string", "enum": ["preview", "zip", "content"], "default": "preview"},
                    "dest": {"type": "string", "description": "Destination directory relative to project root", "default": "assets/"},
                    "resolution": {"type": "string", "description": "polyhaven/ambientcg resolution (e.g. '1k', '2k', '4k')", "default": "1k"},
                    "format": {"type": "string", "description": "polyhaven/ambientcg format (jpg, png, hdr, exr)", "default": "jpg"},
                    "accept_attribution": {"type": "boolean",
                                           "description": "Acknowledge CC-BY / Pixabay attribution requirement; CREDITS.md will be appended.",
                                           "default": False},
                },
                "required": ["asset_id"],
            },
        })

    def _register(self, name: str, handler: callable, schema: dict):
        self._tool_registry[name] = handler
        self._tool_schemas[name] = schema

    # --- Tool implementations ---

    async def _tool_file_read(self, args: dict, **ctx) -> str:
        path = self._safe_path(args["path"], ctx.get("project_id"), ctx.get("agent_instance_id"))
        if not path.exists():
            raise FileNotFoundError(f"File not found: {args['path']}")
        return path.read_text(encoding="utf-8")

    async def _tool_file_write(self, args: dict, **ctx) -> str:
        path = self._safe_path(args["path"], ctx.get("project_id"), ctx.get("agent_instance_id"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"Wrote {len(args['content'])} chars to {args['path']}"

    async def _tool_bash_execute(self, args: dict, **ctx) -> str:
        command = args["command"]
        timeout = args.get("timeout", 60)
        cwd = self._project_dir(ctx.get("project_id"), ctx.get("agent_instance_id"))

        # Safety: block dangerous patterns
        dangerous = ["rm -rf /", "rm -rf /*", ":(){ :|:& };:", "dd if=/dev"]
        if any(d in command for d in dangerous):
            raise PermissionError(f"Blocked dangerous command pattern")

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"

        output = stdout.decode(errors="replace")
        if stderr:
            output += "\nSTDERR:\n" + stderr.decode(errors="replace")
        if proc.returncode != 0:
            output += f"\n(exit code {proc.returncode})"

        # Truncate very long output
        if len(output) > 10000:
            output = output[:10000] + f"\n... (truncated, total {len(output)} chars)"
        return output

    async def _tool_git_status(self, args: dict, **ctx) -> str:
        return await self._tool_bash_execute({"command": "git status --short"}, **ctx)

    async def _tool_git_add(self, args: dict, **ctx) -> str:
        paths = " ".join(f'"{p}"' for p in args["paths"])
        return await self._tool_bash_execute({"command": f"git add {paths}"}, **ctx)

    async def _tool_git_commit(self, args: dict, **ctx) -> str:
        msg = args["message"].replace('"', '\\"')
        return await self._tool_bash_execute({"command": f'git commit -m "{msg}"'}, **ctx)

    async def _tool_git_diff(self, args: dict, **ctx) -> str:
        flag = "--staged" if args.get("staged") else ""
        return await self._tool_bash_execute({"command": f"git diff {flag}"}, **ctx)

    async def _tool_web_search(self, args: dict, **ctx) -> str:
        """Classic web search via DuckDuckGo HTML (no key). Returns [{title,url,snippet}]."""
        import html as _html, re as _re
        import httpx as _httpx
        query = args["query"]
        limit = min(int(args.get("limit") or 8), 20)
        try:
            # DDG flags obvious bot UAs with a 202 "anomaly" interstitial.
            # Use a real Chrome UA; POST with form body returns the full
            # result__a/result__snippet markup our parser expects.
            async with _httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://duckduckgo.com/",
                },
            ) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query},
                )
                resp.raise_for_status()
                body = resp.text
                if "anomaly-modal" in body or "anomaly_id" in body:
                    return json.dumps({
                        "status": "rate_limited",
                        "query": query,
                        "hint": "DuckDuckGo flagged the request; retry later or use perplexity_research.",
                    })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "query": query,
            })

        # Parse the DuckDuckGo HTML result blocks.
        result_rx = _re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            _re.DOTALL,
        )
        def _strip(s: str) -> str:
            s = _re.sub(r"<[^>]+>", "", s)
            return _html.unescape(s).strip()

        def _unwrap(url: str) -> str:
            # DuckDuckGo wraps result URLs in /l/?uddg=<encoded>. Unwrap.
            m = _re.search(r"uddg=([^&]+)", url)
            if m:
                from urllib.parse import unquote
                return unquote(m.group(1))
            return url

        hits = []
        for m in result_rx.finditer(body):
            hits.append({
                "title": _strip(m.group(2)),
                "url": _unwrap(m.group(1)),
                "snippet": _strip(m.group(3)),
            })
            if len(hits) >= limit:
                break

        return json.dumps({
            "status": "ok",
            "query": query,
            "count": len(hits),
            "results": hits,
        })

    async def _tool_perplexity_research(self, args: dict, **ctx) -> str:
        """Perplexity Sonar-backed research. Returns synthesized answer + citations."""
        import os as _os
        key = _os.environ.get("PERPLEXITY_API_KEY")
        if not key:
            return json.dumps({
                "status": "error",
                "error": "PERPLEXITY_API_KEY not set — cannot run perplexity_research",
                "query": args.get("query"),
            })

        depth = (args.get("depth") or "standard").lower()
        model = {"quick": "sonar", "standard": "sonar-pro",
                 "deep": "sonar-reasoning"}.get(depth, "sonar-pro")

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "You are a concise research assistant. Answer in under 400 words "
                    "with clear citations. Prefer primary sources and recent data."
                )},
                {"role": "user", "content": args["query"]},
            ],
        }
        recency = args.get("recency")
        if recency:
            body["search_recency_filter"] = recency

        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json=body,
                )
                if resp.status_code >= 400:
                    return json.dumps({
                        "status": "error",
                        "error": f"Perplexity {resp.status_code}: {resp.text[:500]}",
                        "query": args.get("query"),
                    })
                data = resp.json()
        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "query": args.get("query"),
            })

        choice = (data.get("choices") or [{}])[0]
        answer = (choice.get("message") or {}).get("content", "")
        citations = data.get("citations") or data.get("search_results") or []
        cites_out = []
        for c in citations:
            if isinstance(c, str):
                cites_out.append({"url": c})
            elif isinstance(c, dict):
                cites_out.append({k: v for k, v in c.items() if k in ("url", "title")})
        return json.dumps({
            "status": "ok",
            "query": args.get("query"),
            "depth": depth,
            "model": model,
            "answer": answer,
            "citations": cites_out,
            "usage": data.get("usage"),
        })

    async def _tool_channel_post(self, args: dict, **ctx) -> str:
        project_id = ctx.get("project_id")
        if not project_id:
            return "No project context — cannot post to channel."

        mentions = json.dumps(args.get("mentions", []))
        sender = ctx.get("agent_instance_id", "unknown")

        with get_studio_db() as db:
            db.execute(
                """INSERT INTO messages (project_id, channel, sender, content, mentions)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, args["channel"], sender, args["content"], mentions),
            )
        return f"Posted to #{args['channel']}"

    async def _tool_channel_read(self, args: dict, **ctx) -> str:
        project_id = ctx.get("project_id")
        if not project_id:
            return "No project context."

        limit = args.get("limit", 20)
        with get_studio_db() as db:
            rows = db.execute(
                """SELECT sender, content, created_at FROM messages
                   WHERE project_id = ? AND channel = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (project_id, args["channel"], limit),
            ).fetchall()

        if not rows:
            return f"No messages in #{args['channel']}"

        lines = []
        for r in reversed(rows):
            lines.append(f"[{r['created_at']}] {r['sender']}: {r['content']}")
        return "\n".join(lines)

    async def _tool_escalate(self, args: dict, **ctx) -> str:
        # Post to escalation queue and return a placeholder
        # In production, this would block until human responds via dashboard
        project_id = ctx.get("project_id")
        agent_id = ctx.get("agent_instance_id", "unknown")

        with get_studio_db() as db:
            db.execute(
                """INSERT INTO messages (project_id, channel, sender, content, mentions)
                   VALUES (?, 'escalation', ?, ?, '["human"]')""",
                (project_id or "system", agent_id, json.dumps({
                    "question": args["question"],
                    "options": args.get("options", []),
                    "context": args.get("context", ""),
                })),
            )
        return f"Escalation posted. Question: {args['question']}"

    async def _tool_memory_read(self, args: dict, **ctx) -> str:
        from src.database import get_project_db
        project_id = ctx.get("project_id")
        if not project_id:
            return "No project context."

        with get_project_db(project_id) as db:
            row = db.execute(
                "SELECT content, created_by, updated_at FROM memory WHERE type = ? AND key = ?",
                (args["type"], args["key"]),
            ).fetchone()

        if not row:
            return f"No memory found for {args['type']}/{args['key']}"
        return row["content"]

    async def _tool_memory_write(self, args: dict, **ctx) -> str:
        from src.database import get_project_db
        project_id = ctx.get("project_id")
        if not project_id:
            return "No project context."

        agent_id = ctx.get("agent_instance_id", "unknown")
        with get_project_db(project_id) as db:
            existing = db.execute(
                "SELECT id FROM memory WHERE type = ? AND key = ?",
                (args["type"], args["key"]),
            ).fetchone()

            if existing:
                db.execute(
                    """UPDATE memory SET content = ?, created_by = ?, updated_at = datetime('now')
                       WHERE type = ? AND key = ?""",
                    (args["content"], agent_id, args["type"], args["key"]),
                )
            else:
                db.execute(
                    "INSERT INTO memory (type, key, content, created_by) VALUES (?, ?, ?, ?)",
                    (args["type"], args["key"], args["content"], agent_id),
                )
        return f"Saved to memory: {args['type']}/{args['key']}"

    async def _tool_memory_search(self, args: dict, **ctx) -> str:
        from src.database import get_project_db
        project_id = ctx.get("project_id")
        if not project_id:
            return "No project context."

        query = f"%{args['query']}%"
        with get_project_db(project_id) as db:
            sql = "SELECT type, key, content FROM memory WHERE content LIKE ?"
            params = [query]
            if args.get("type"):
                sql += " AND type = ?"
                params.append(args["type"])
            sql += " ORDER BY updated_at DESC LIMIT 10"

            rows = db.execute(sql, params).fetchall()

        if not rows:
            return "No matching memories found."

        lines = []
        for r in rows:
            preview = r["content"][:200]
            lines.append(f"[{r['type']}/{r['key']}] {preview}")
        return "\n".join(lines)

    async def _tool_task_create(self, args: dict, **ctx) -> str:
        """Agent-to-agent task delegation. Creates a pending task on the board."""
        from src.orchestrator.task_queue import task_queue
        from src.models.tasks import TaskCreate

        project_id = ctx.get("project_id")
        if not project_id:
            return "Error: no project context — task_create requires a project_id."

        agent_id = ctx.get("agent_instance_id", "agent")
        title = (args.get("title") or "").strip()
        if not title:
            return "Error: 'title' is required."

        try:
            task = task_queue.create(TaskCreate(
                project_id=project_id,
                title=title[:200],
                description=args.get("description", ""),
                priority=int(args.get("priority", 0) or 0),
                depends_on=args.get("depends_on", []) or [],
                parent_task_id=args.get("parent_task_id"),
                assignee_type=args.get("assignee_type") or None,
                created_by=agent_id,
            ))
        except Exception as e:
            return f"Error creating task: {e}"

        # Broadcast so the live ActivityFeed + TaskBoard pick it up immediately.
        # Resolve ws_manager via sys.modules to avoid re-importing src.main (which boots a new app).
        try:
            import sys
            main_mod = sys.modules.get("src.main")
            ws_manager = getattr(main_mod, "ws_manager", None) if main_mod else None
            if ws_manager is not None:
                await ws_manager.broadcast({
                    "type": "task_created",
                    "data": task.model_dump(mode="json"),
                })
        except Exception:
            pass

        return (
            f"Created task {task.id}: \"{task.title}\" "
            f"(priority={task.priority}, depends_on={task.depends_on or 'none'})."
        )

    async def _tool_skill_invoke(self, args: dict, **ctx) -> str:
        from src.runtime.skill_registry import skill_registry
        skill_id = args["skill_id"]
        skill = skill_registry.get_skill(skill_id)
        if not skill:
            near = ", ".join(s.id for s in skill_registry.list_skills()[:10])
            return f"Skill '{skill_id}' not found. Sample available ids: {near}"
        header = f"# Skill: {skill.name}\n_{skill.description}_\n\n"
        return header + (skill.content or "")

    async def _tool_file_edit(self, args: dict, **ctx) -> str:
        path = self._safe_path(args["path"], ctx.get("project_id"), ctx.get("agent_instance_id"))
        if not path.exists():
            raise FileNotFoundError(f"File not found: {args['path']}")
        content = path.read_text(encoding="utf-8")
        old = args["old_string"]
        new = args["new_string"]
        if old not in content:
            raise ValueError(f"old_string not found in {args['path']}")
        if args.get("replace_all"):
            updated = content.replace(old, new)
            count = content.count(old)
        else:
            count = content.count(old)
            if count > 1:
                raise ValueError(
                    f"old_string appears {count} times in {args['path']} — "
                    "provide more context or set replace_all=true"
                )
            updated = content.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        return f"Edited {args['path']} — {count} replacement(s)"

    async def _tool_grep(self, args: dict, **ctx) -> str:
        import shutil
        base = self._project_dir(ctx.get("project_id"), ctx.get("agent_instance_id"))
        subdir = args.get("path") or ""
        search_root = (base / subdir).resolve()
        if not str(search_root).startswith(str(base.resolve())):
            raise PermissionError("path escapes project directory")
        pattern = args["pattern"]
        max_results = int(args.get("max_results", 100))

        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "--no-heading", "-n", f"-m{max_results}"]
            if args.get("case_insensitive"):
                cmd.append("-i")
            if args.get("glob"):
                cmd += ["--glob", args["glob"]]
            cmd += [pattern, str(search_root)]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            out = stdout.decode(errors="replace").strip()
            if not out:
                return "No matches."
            lines = out.splitlines()[:max_results]
            # Strip base prefix for readability
            prefix = str(base.resolve()) + "/"
            cleaned = [l.removeprefix(prefix) for l in lines]
            return "\n".join(cleaned)

        # Fallback: pure-Python regex walk
        flags = re.IGNORECASE if args.get("case_insensitive") else 0
        rx = re.compile(pattern, flags)
        glob_pat = args.get("glob")
        matches: list[str] = []
        for fp in search_root.rglob(glob_pat or "*"):
            if not fp.is_file():
                continue
            try:
                for i, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        rel = fp.relative_to(base)
                        matches.append(f"{rel}:{i}:{line}")
                        if len(matches) >= max_results:
                            return "\n".join(matches)
            except (OSError, UnicodeDecodeError):
                continue
        return "\n".join(matches) if matches else "No matches."

    async def _tool_glob(self, args: dict, **ctx) -> str:
        base = self._project_dir(ctx.get("project_id"), ctx.get("agent_instance_id"))
        subdir = args.get("path") or ""
        search_root = (base / subdir).resolve()
        if not str(search_root).startswith(str(base.resolve())):
            raise PermissionError("path escapes project directory")
        pattern = args["pattern"]
        hits = [p for p in search_root.glob(pattern) if p.is_file()]
        hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        rels = [str(p.relative_to(base)) for p in hits[:200]]
        return "\n".join(rels) if rels else "No files matched."

    async def _tool_asset_search(self, args: dict, **ctx) -> str:
        from src.runtime import asset_sources
        import httpx, json

        query = (args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        pool = args.get("pool", "both")
        limit = int(args.get("limit", 6))
        kind = args.get("kind")

        # "both" → kenney + itch (default, fast). "all" fans out across no-key pools.
        if pool == "both":
            pools = ("kenney", "itch")
        elif pool == "all":
            pools = ("kenney", "itch", "polyhaven", "ambientcg", "quaternius", "oga")
        else:
            pools = (pool,)

        hits: list = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            for p in pools:
                fn = getattr(asset_sources, f"search_{p}", None)
                if not fn:
                    hits.append({"error": f"unknown pool: {p}"})
                    continue
                try:
                    # Poly Haven + Pixabay accept a `kind` filter
                    if p == "polyhaven" and kind:
                        result = await fn(query, limit, kind=kind, client=client)
                    elif p == "pixabay" and kind:
                        result = await fn(query, limit, kind=kind, client=client)
                    else:
                        result = await fn(query, limit, client=client)
                    hits.extend(result)
                except Exception as e:
                    hits.append({"error": f"{p} search failed: {type(e).__name__}: {e}"})

        payload = [h.to_dict() if hasattr(h, "to_dict") else h for h in hits]
        return json.dumps({"query": query, "pool": pool, "hits": payload}, indent=2)

    async def _tool_asset_fetch(self, args: dict, **ctx) -> str:
        from src.runtime import asset_sources
        from src.runtime.asset_sources import download
        from pathlib import Path
        import httpx

        asset_id = (args.get("asset_id") or "").strip()
        if ":" not in asset_id:
            return json.dumps({"status": "error", "error": "asset_id must be '<pool>:<slug>'"})
        pool, ident = asset_id.split(":", 1)
        kind = args.get("kind", "preview")
        dest_rel = (args.get("dest") or "assets/").rstrip("/") + "/"
        accept_attribution = bool(args.get("accept_attribution", False))
        resolution = args.get("resolution", "1k")
        fmt = args.get("format", "jpg")

        safe_ident = re.sub(r"[^A-Za-z0-9_.-]", "_", ident)

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                resolved = await self._resolve_asset(
                    pool, ident, kind, resolution, fmt, client=client,
                )
                if "error" in resolved:
                    return json.dumps({"status": "error", "asset_id": asset_id, **resolved})

                # Quaternius etc. may return a human-in-the-loop download (Google Drive
                # folders, etc.). Surface the URL to the agent instead of trying to stream.
                if resolved.get("manual_download_required"):
                    return json.dumps({
                        "status": "manual_download_required",
                        "asset_id": asset_id,
                        "download_url": resolved["download_url"],
                        "note": resolved.get("note", ""),
                        "license": resolved.get("license") or {"spdx_id": "Unknown"},
                    })

                url = resolved["download_url"]
                ext = resolved.get("ext") or (Path(url.split("?", 1)[0]).suffix.lstrip(".") or "bin")
                lic = resolved.get("license") or {"spdx_id": "Unknown"}

                # Policy: block non-CC0 content downloads unless the agent accepts attribution.
                # Previews are always permitted because they're reference thumbnails.
                if kind != "preview" and lic.get("spdx_id") != "CC0-1.0" and not accept_attribution:
                    return json.dumps({
                        "status": "needs_approval",
                        "asset_id": asset_id,
                        "reason": f"License {lic.get('spdx_id')} requires attribution — pass accept_attribution=true",
                        "license": lic,
                    })

                dest = self._safe_path(
                    f"{dest_rel}{safe_ident}.{ext}",
                    ctx.get("project_id"), ctx.get("agent_instance_id"),
                )
                await download(url, dest, client=client)

                # Emit CREDITS.md line for any non-CC0 content we just saved.
                credits_line = None
                if kind != "preview" and lic.get("spdx_id") != "CC0-1.0":
                    credits_line = self._append_credits(
                        dest_rel, asset_id, lic,
                        ctx.get("project_id"), ctx.get("agent_instance_id"),
                    )

                return json.dumps({
                    "status": "ok",
                    "asset_id": asset_id,
                    "kind": kind,
                    "path": str(Path(dest_rel) / f"{safe_ident}.{ext}"),
                    "source_url": url,
                    "license": lic,
                    "credits_appended": credits_line,
                })
        except Exception as e:
            return json.dumps({
                "status": "error", "asset_id": asset_id, "kind": kind,
                "error": f"{type(e).__name__}: {e}",
            })

    async def _resolve_asset(self, pool: str, ident: str, kind: str,
                             resolution: str, fmt: str, *, client) -> dict:
        """Dispatch per-pool resolver. Returns {download_url, ext?, license?} or {error}."""
        from src.runtime import asset_sources
        from src.runtime.asset_sources import (
            resolve_kenney_zip, resolve_polyhaven, resolve_ambientcg,
            resolve_quaternius_download, resolve_oga,
        )

        # --- preview path: fall back to search result's preview_url ---
        if kind == "preview":
            search_fn = asset_sources.SEARCH_REGISTRY.get(pool)
            if not search_fn:
                return {"error": f"unknown pool: {pool}"}
            # For pools with JSON APIs, search-by-slug isn't the shape — we search with
            # the ident and pick the exact match; worst case we return the first hit.
            hits = await search_fn(ident, limit=8, client=client)
            match = None
            for h in hits:
                if hasattr(h, "asset_id") and h.asset_id == f"{pool}:{ident}":
                    match = h
                    break
            if not match and hits and hasattr(hits[0], "asset_id"):
                match = hits[0]
            if not match:
                return {"error": f"No preview resolved for {pool}:{ident}"}
            url = match.preview_url
            if not url:
                return {"error": f"Hit {match.asset_id} has no preview_url"}
            ext = Path(url.split("?", 1)[0]).suffix.lstrip(".") or "png"
            return {"download_url": url, "ext": ext, "license": match.license.to_dict()}

        # --- content path: per-pool resolver ---
        if pool == "kenney":
            url = await resolve_kenney_zip(ident, client=client)
            if not url:
                return {"error": f"No zip for kenney:{ident}"}
            return {"download_url": url, "ext": "zip",
                    "license": asset_sources.CC0.to_dict()}

        if pool == "polyhaven":
            info = await resolve_polyhaven(ident, resolution=resolution, fmt=fmt, client=client)
            return {**info, "license": asset_sources.CC0.to_dict()}

        if pool == "ambientcg":
            info = await resolve_ambientcg(ident, resolution=resolution.upper(), fmt=fmt, client=client)
            return {**info, "license": asset_sources.CC0.to_dict()}

        if pool == "quaternius":
            info = await resolve_quaternius_download(ident, client=client)
            if not info:
                return {"error": f"No download link for quaternius:{ident}"}
            if info.get("requires_manual"):
                return {
                    "manual_download_required": True,
                    "download_url": info["download_url"],
                    "note": info.get("note", ""),
                    "license": asset_sources.CC0.to_dict(),
                }
            return {"download_url": info["download_url"],
                    "ext": info.get("ext", "zip"),
                    "license": asset_sources.CC0.to_dict()}

        if pool == "oga":
            info = await resolve_oga(ident, client=client)
            if not info:
                return {"error": f"oga:{ident} not CC0 or no download — refusing"}
            return {**info, "license": asset_sources.CC0.to_dict()}

        if pool == "pixabay":
            # Pixabay: the search result already has download_url; re-search by id.
            hits = await asset_sources.search_pixabay(ident, limit=8, client=client)
            for h in hits:
                if hasattr(h, "asset_id") and h.asset_id == f"pixabay:{ident}":
                    return {"download_url": h.download_url,
                            "ext": Path(h.download_url.split("?", 1)[0]).suffix.lstrip(".") or "jpg",
                            "license": h.license.to_dict()}
            return {"error": f"pixabay:{ident} not found in search"}

        if pool == "freesound":
            hits = await asset_sources.search_freesound(ident, limit=8, cc0_only=False, client=client)
            for h in hits:
                if hasattr(h, "asset_id") and h.asset_id == f"freesound:{ident}":
                    return {"download_url": h.download_url, "ext": "mp3",
                            "license": h.license.to_dict()}
            return {"error": f"freesound:{ident} not found in search"}

        if pool == "itch":
            return {"error": "itch content downloads are not automated — "
                             "open the page manually and confirm license first"}

        return {"error": f"unknown pool: {pool}"}

    def _append_credits(self, dest_rel: str, asset_id: str, lic: dict,
                        project_id: str | None, agent_instance_id: str | None) -> str:
        """Append a CREDITS.md entry at the project root. Returns the line written."""
        line = (
            f"- {asset_id} — {lic.get('spdx_id', 'Unknown')}"
            + (f" — {lic.get('attribution_text')}" if lic.get("attribution_text") else "")
            + (f" — {lic.get('attribution_url')}" if lic.get("attribution_url") else "")
            + "\n"
        )
        try:
            credits_path = self._safe_path("CREDITS.md", project_id, agent_instance_id)
            if not credits_path.exists():
                credits_path.write_text("# Credits\n\n", encoding="utf-8")
            with credits_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            # Credits failure shouldn't break the fetch; return line for logs.
            pass
        return line.strip()

    async def _tool_playwright_browser(self, args: dict, **ctx) -> str:
        """Headless browser driver — small action set tuned for QA playtests.

        Actions:
          - open: load a URL (or file://.../path from the project), returns title + body excerpt.
          - key: dispatch keyboard events (e.g. 'KeyW', 'Space').
          - click: click at {x, y} (viewport px).
          - evaluate: run a JS expression and return its JSON-serialized result.
          - screenshot: save PNG to a project-relative path, returns that path.
          - close: release the shared context.

        The agent is expected to drive a sequence:
          open → evaluate(window.__game) → key('KeyW') → evaluate(player.x) → …

        Implementation uses the playwright node module already installed for the
        digest skill, invoked as a long-lived subprocess over a line-delimited
        JSON protocol. Each tool call is one script invocation (simpler + more
        robust than holding a persistent subprocess across awaits).
        """
        import json as _json
        import shlex
        url = (args.get("url") or "").strip()
        action = (args.get("action") or "open").strip()
        payload = args.get("payload") or {}
        timeout_ms = int(args.get("timeout_ms", 8000))

        script = r"""
const { chromium } = require('playwright');
(async () => {
  const input = JSON.parse(process.argv[2]);
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1024, height: 720 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  const out = { ok: true, action: input.action, console_errors: [] };
  try {
    if (input.url) await page.goto(input.url, { waitUntil: 'load', timeout: input.timeout_ms });
    if (input.action === 'open') {
      await page.waitForTimeout(500);
      out.title = await page.title();
      out.has_canvas = await page.evaluate(() => !!document.querySelector('canvas'));
      out.has_webgl = await page.evaluate(() => {
        const c = document.querySelector('canvas');
        if (!c) return false;
        return !!(c.getContext('webgl') || c.getContext('webgl2'));
      });
      out.has_game_hook = await page.evaluate(() => !!window.__game);
    } else if (input.action === 'evaluate') {
      out.value = await page.evaluate(input.payload.expr);
    } else if (input.action === 'key') {
      await page.keyboard.press(input.payload.key, { delay: 16 });
      if (input.payload.hold_ms) await page.waitForTimeout(input.payload.hold_ms);
    } else if (input.action === 'key_sequence') {
      for (const k of input.payload.keys || []) {
        await page.keyboard.down(k);
      }
      await page.waitForTimeout(input.payload.hold_ms || 200);
      for (const k of (input.payload.keys || []).slice().reverse()) {
        await page.keyboard.up(k);
      }
    } else if (input.action === 'click') {
      await page.mouse.click(input.payload.x || 512, input.payload.y || 360);
    } else if (input.action === 'screenshot') {
      await page.screenshot({ path: input.payload.path, fullPage: !!input.payload.full });
      out.path = input.payload.path;
    } else if (input.action === 'wait') {
      await page.waitForTimeout(input.payload.ms || 500);
    } else {
      out.ok = false; out.error = 'unknown action';
    }
    out.console_errors = consoleErrors.slice(0, 20);
  } catch (e) {
    out.ok = false; out.error = String(e && e.message || e);
    out.console_errors = consoleErrors.slice(0, 20);
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
})();
"""
        # Resolve playwright install (shared with digest skill).
        pw_paths = [
            "/Users/dknanlin/.claude/skills/digest/node_modules",
            "/Users/dknanlin/.claude/skills/email-digest/node_modules",
        ]
        node_path = ":".join(p for p in pw_paths if Path(p).is_dir())
        if not node_path:
            return json.dumps({"ok": False, "error": "playwright module not found locally"})

        # If an asset relative path was passed as url, resolve it to file://.
        base = self._project_dir(ctx.get("project_id"), ctx.get("agent_instance_id"))
        if url and not url.startswith(("http://", "https://", "file://")):
            local = (base / url).resolve()
            if str(local).startswith(str(base.resolve())) and local.exists():
                url = f"file://{local}"

        # screenshot path → resolve under project
        if action == "screenshot":
            rel = payload.get("path") or f"assets/qa/shot-{int(asyncio.get_event_loop().time()*1000)}.png"
            abs_path = self._safe_path(rel, ctx.get("project_id"), ctx.get("agent_instance_id"))
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {**payload, "path": str(abs_path)}

        driver_input = _json.dumps({
            "url": url or None,
            "action": action,
            "payload": payload,
            "timeout_ms": timeout_ms,
        })

        cmd = f"NODE_PATH={shlex.quote(node_path)} node -e {shlex.quote(script)} {shlex.quote(driver_input)}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000.0 + 30)
        except asyncio.TimeoutError:
            proc.kill()
            return json.dumps({"ok": False, "error": f"playwright timeout after {timeout_ms}ms"})
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if not out:
            return json.dumps({"ok": False, "error": err or "no output from playwright driver"})
        # Convert absolute screenshot path back to project-relative for downstream agents.
        try:
            parsed = _json.loads(out)
            if parsed.get("path"):
                try:
                    parsed["path"] = str(Path(parsed["path"]).relative_to(base.resolve()))
                except ValueError:
                    pass
            return _json.dumps(parsed)
        except Exception:
            return out

    async def _tool_web_fetch(self, args: dict, **ctx) -> str:
        import httpx
        url = args["url"]
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        max_bytes = int(args.get("max_bytes", 200_000))
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url, headers={"User-Agent": "code-play-agent/1.0"})
        body = resp.text
        header = f"HTTP {resp.status_code} {url}\n"
        if len(body) > max_bytes:
            body = body[:max_bytes] + f"\n... (truncated, total {len(body)} chars)"
        return header + body

    async def _tool_update_criterion_status(self, args: dict, **ctx) -> str:
        from src.memory import criteria_store
        from src.models.criteria import CriterionStatus, CriterionUpdate
        try:
            status = CriterionStatus(args["status"])
        except ValueError:
            return f"Error: invalid status '{args.get('status')}'"
        c = criteria_store.update(args["criterion_id"], CriterionUpdate(status=status))
        if not c:
            return f"Error: criterion '{args['criterion_id']}' not found"
        note = args.get("note", "")
        suffix = f" — note: {note}" if note else ""
        return f"Criterion '{c.title}' → {c.status.value}{suffix}"

    async def _tool_document_write(self, args: dict, **ctx) -> str:
        from src.memory import project_docs
        project_id = ctx.get("project_id")
        if not project_id:
            return "Error: no project context."
        try:
            doc_id, version = project_docs.write(
                project_id=project_id,
                category=args["category"],
                slug=args["slug"],
                title=args["title"],
                content=args["content"],
                change_summary=args.get("change_summary", ""),
                created_by=ctx.get("agent_instance_id", "agent"),
            )
        except ValueError as e:
            return f"Error: {e}"
        return f"Wrote {args['category']}/{args['slug']} v{version} (doc={doc_id})"

    async def _tool_document_read(self, args: dict, **ctx) -> str:
        from src.memory import project_docs
        project_id = ctx.get("project_id")
        if not project_id:
            return "Error: no project context."
        doc = project_docs.read(
            project_id=project_id,
            category=args["category"],
            slug=args["slug"],
            version=args.get("version"),
        )
        if not doc:
            return f"No document found at {args['category']}/{args['slug']}"
        header = f"# {doc['title']} (v{doc['version']})\n_category={doc['category']}, status={doc['status']}_\n\n"
        return header + (doc.get("content") or "")

    async def _tool_propose_agent(self, args: dict, **ctx) -> str:
        from src.memory import proposals_store
        from src.models.proposals import AgentProposalCreate, ProposalPhase
        project_id = ctx.get("project_id")
        if not project_id:
            return "Error: no project context."
        p = proposals_store.create(AgentProposalCreate(
            project_id=project_id,
            agent_type=args["agent_type"],
            rationale=args.get("rationale", ""),
            proposer=ctx.get("agent_instance_id", "agent"),
            phase=ProposalPhase.IN_FLIGHT,
            model_override=args.get("model_override"),
        ))
        # Broadcast if main app is up (non-fatal)
        try:
            import sys
            main_mod = sys.modules.get("src.main")
            ws_manager = getattr(main_mod, "ws_manager", None) if main_mod else None
            if ws_manager is not None:
                await ws_manager.broadcast({"type": "proposal_created", "data": p.model_dump(mode="json")})
        except Exception:
            pass
        return f"Proposed agent '{p.agent_type}' (proposal={p.id}) — awaiting human approval."

    # --- Iteration + cross-repo + publishing tools ---

    async def _tool_iteration_runner(self, args: dict, **ctx) -> str:
        from src.iteration.iterate_runner import run_playtest_batch
        project_id = ctx.get("project_id")
        if not project_id:
            raise ValueError("iteration_runner requires a project context")
        repo_path = args["repo_path"]
        cycle_n = int(args["cycle_n"])
        runs = int(args.get("runs", 5))
        seconds_per_run = int(args.get("seconds_per_run", 60))
        game_entry = args.get("game_entry", "index.html")
        bot_script = args.get("bot_script", "playtest_bot.mjs")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_playtest_batch(
                project_id=project_id,
                repo_path=repo_path,
                cycle_n=cycle_n,
                runs=runs,
                seconds_per_run=seconds_per_run,
                game_entry=game_entry,
                bot_script=bot_script,
            ),
        )

        try:
            import sys as _sys
            main_mod = _sys.modules.get("src.main")
            ws_manager = getattr(main_mod, "ws_manager", None) if main_mod else None
            if ws_manager is not None:
                await ws_manager.broadcast({
                    "type": "playtest_batch_complete",
                    "data": {
                        "project_id": project_id,
                        "cycle_n": result.cycle_n,
                        "iteration_tag": result.iteration_tag,
                        "n_runs": result.rollup.get("n_runs"),
                        "n_valid": result.rollup.get("n_valid"),
                    },
                })
        except Exception:
            pass

        return json.dumps({
            "status": "ok" if result.node_exit_code == 0 else "bot_nonzero_exit",
            "cycle_n": result.cycle_n,
            "iteration_tag": result.iteration_tag,
            "rollup": result.rollup,
            "files": result.files,
            "node_exit_code": result.node_exit_code,
            "stdout_tail": result.stdout_tail[-2000:],
        })

    def _safe_repo_path(self, repo_path_str: str, relative: str) -> Path:
        """Resolve a relative path within an artifact repo, preventing traversal."""
        repo = Path(repo_path_str).resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"Repo not found: {repo}")
        resolved = (repo / relative).resolve()
        if not str(resolved).startswith(str(repo)):
            raise PermissionError(f"Path traversal blocked: {relative}")
        return resolved

    async def _tool_repo_file_read(self, args: dict, **ctx) -> str:
        path = self._safe_repo_path(args["repo_path"], args["path"])
        if not path.exists():
            raise FileNotFoundError(f"File not found: {args['path']} in {args['repo_path']}")
        content = path.read_text(encoding="utf-8")
        if len(content) > 200_000:
            return content[:200_000] + f"\n\n... (truncated at 200k chars, full file is {len(content)} chars)"
        return content

    async def _tool_repo_file_write(self, args: dict, **ctx) -> str:
        path = self._safe_repo_path(args["repo_path"], args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"Wrote {len(args['content'])} chars to {args['path']}"

    async def _tool_repo_file_list(self, args: dict, **ctx) -> str:
        repo = Path(args["repo_path"]).resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"Repo not found: {repo}")
        subdir = args.get("subdir")
        root = (repo / subdir).resolve() if subdir else repo
        if not str(root).startswith(str(repo)):
            raise PermissionError(f"Path traversal blocked: {subdir}")
        if not root.is_dir():
            raise FileNotFoundError(f"Directory not found: {subdir}")

        from src.runtime.workspace import list_project_files
        return list_project_files(root, max_files=100)

    async def _tool_external_repo_commit(self, args: dict, **ctx) -> str:
        repo_path = Path(args["repo_path"]).resolve()
        if not (repo_path / ".git").exists():
            raise ValueError(f"Not a git repo: {repo_path}")

        files = args["files"]
        if not isinstance(files, list) or not files:
            raise ValueError("external_repo_commit requires a non-empty 'files' list")
        message = args["message"]
        branch = args.get("branch")
        allow_empty = bool(args.get("allow_empty", False))

        async def _run(cmd: str, timeout: int = 60) -> tuple[int, str]:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_path),
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, (out.decode(errors="replace") + err.decode(errors="replace"))

        results: dict = {"written": [], "commit": None, "branch": None}

        if branch:
            code, _ = await _run(f"git checkout {branch}")
            if code != 0:
                code2, out2 = await _run(f"git checkout -b {branch}")
                if code2 != 0:
                    raise RuntimeError(f"Could not checkout or create branch {branch}: {out2}")
            results["branch"] = branch

        written_rel: list[str] = []
        for entry in files:
            rel = entry["path"]
            target = (repo_path / rel).resolve()
            if not str(target).startswith(str(repo_path)):
                raise PermissionError(f"Path traversal blocked: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(entry["content"], encoding="utf-8")
            written_rel.append(rel)
        results["written"] = written_rel

        paths_arg = " ".join(f'"{p}"' for p in written_rel)
        code, out = await _run(f"git add {paths_arg}")
        if code != 0:
            raise RuntimeError(f"git add failed: {out}")

        msg_escaped = message.replace('"', '\\"')
        empty_flag = "--allow-empty " if allow_empty else ""
        code, out = await _run(f'git commit {empty_flag}-m "{msg_escaped}"')
        if code != 0 and "nothing to commit" not in out:
            raise RuntimeError(f"git commit failed: {out}")

        code, sha = await _run("git rev-parse HEAD")
        results["commit"] = sha.strip() if code == 0 else None

        return json.dumps({"status": "ok", **results})

    async def _tool_scaffold_iteration(self, args: dict, **ctx) -> str:
        """Wrap src.iteration.scaffolder.scaffold_iteration_artifacts so agents
        don't have to shell python or reach into the code-play repo."""
        artifact_dir = args.get("artifact_dir")
        if not artifact_dir:
            return json.dumps({"status": "error", "error": "artifact_dir required"})
        project_id = ctx.get("project_id")
        if not project_id:
            return json.dumps({"status": "error", "error": "project_id missing from context"})

        from src.iteration.scaffolder import scaffold_iteration_artifacts

        kwargs = {}
        if args.get("project_title"):
            kwargs["project_title"] = args["project_title"]
        if args.get("game_url"):
            kwargs["game_url"] = args["game_url"]

        loop = asyncio.get_event_loop()
        try:
            paths = await loop.run_in_executor(
                None,
                lambda: scaffold_iteration_artifacts(project_id, artifact_dir, **kwargs),
            )
        except Exception as e:
            return json.dumps({"status": "error", "error": f"scaffolder failed: {e}"})

        return json.dumps({
            "status": "ok",
            "artifact_dir": str(artifact_dir),
            "files": {k: str(v) for k, v in paths.items()} if isinstance(paths, dict) else None,
        })

    async def _tool_generate_bot(self, args: dict, **ctx) -> str:
        repo_path = Path(args["repo_path"]).resolve()
        bot_code = args["bot_code"]
        message = args["message"]
        game_analysis = args.get("game_analysis", "")

        if not repo_path.exists():
            raise FileNotFoundError(f"Repo not found: {repo_path}")

        bot_path = repo_path / "playtest_bot.mjs"

        if "window.__game" in bot_code and "GameAPI" not in bot_code:
            return json.dumps({
                "status": "error",
                "error": (
                    "Bot references window.__game but not GameAPI. "
                    "Bots must interact through window.GameAPI only "
                    "(see iteration_contract.md §1a)."
                ),
            })

        bot_path.write_text(bot_code, encoding="utf-8")

        async def _run(cmd: str, timeout: int = 60) -> tuple[int, str]:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_path),
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, (out.decode(errors="replace") + err.decode(errors="replace"))

        code, out = await _run(f'node --check "{bot_path}"')
        if code != 0:
            return json.dumps({
                "status": "error",
                "error": f"Syntax check failed: {out.strip()}",
            })

        if game_analysis:
            analysis_path = repo_path / ".codeplay" / "bot_analysis.md"
            analysis_path.parent.mkdir(parents=True, exist_ok=True)
            analysis_path.write_text(game_analysis, encoding="utf-8")

        if (repo_path / ".git").exists():
            paths_to_add = ['"playtest_bot.mjs"']
            if game_analysis:
                paths_to_add.append('".codeplay/bot_analysis.md"')
            code, out = await _run(f"git add {' '.join(paths_to_add)}")
            if code != 0:
                return json.dumps({"status": "error", "error": f"git add failed: {out}"})

            msg_escaped = message.replace('"', '\\"')
            code, out = await _run(f'git commit -m "{msg_escaped}"')
            if code != 0 and "nothing to commit" not in out:
                return json.dumps({"status": "error", "error": f"git commit failed: {out}"})

            code, sha = await _run("git rev-parse HEAD")
            commit_sha = sha.strip() if code == 0 else None
        else:
            commit_sha = None

        project_id = ctx.get("project_id")
        if project_id:
            from src.memory.project_memory import project_memory
            project_memory.write(
                project_id,
                mem_type="iteration",
                key="playtest_bot_path",
                content=str(bot_path),
                created_by="generate_bot",
            )

        return json.dumps({
            "status": "ok",
            "bot_path": str(bot_path),
            "commit": commit_sha,
            "syntax_check": "passed",
        })

    async def _tool_itchio_publish(self, args: dict, **ctx) -> str:
        import shutil as _shutil
        import os as _os
        build_dir = Path(args["build_dir"]).resolve()
        target = args["target"]
        version = args.get("version")

        if not build_dir.exists():
            raise FileNotFoundError(f"Build dir not found: {build_dir}")
        if not (build_dir / "index.html").exists():
            raise FileNotFoundError(f"No index.html in {build_dir}")

        butler = _shutil.which("butler") or "/Users/dknanlin/.local/bin/butler"
        if not Path(butler).exists():
            return json.dumps({"status": "error", "error": "butler not found on PATH"})

        env = _os.environ.copy()
        if "BUTLER_API_KEY" not in env:
            creds_path = Path.home() / ".config" / "itch" / "butler_creds"
            if creds_path.exists():
                env["BUTLER_API_KEY"] = creds_path.read_text().strip()

        vflag = f' --userversion "{version}"' if version else ""
        push_cmd = f'"{butler}" push "{build_dir}" "{target}"{vflag}'
        push = await asyncio.create_subprocess_shell(
            push_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out, err = await asyncio.wait_for(push.communicate(), timeout=600)
        push_output = (out.decode(errors="replace") + err.decode(errors="replace"))[-2000:]

        if push.returncode != 0:
            return json.dumps({
                "status": "error",
                "error": f"butler push exited {push.returncode}",
                "output": push_output,
            })

        user, slug_channel = target.split("/", 1)
        slug = slug_channel.split(":")[0]
        target_url = f"https://{user}.itch.io/{slug}"

        status_proc = await asyncio.create_subprocess_shell(
            f'"{butler}" status "{target}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        s_out, s_err = await asyncio.wait_for(status_proc.communicate(), timeout=60)
        status_output = (s_out.decode(errors="replace") + s_err.decode(errors="replace"))[-2000:]

        return json.dumps({
            "status": "ok",
            "target": target,
            "target_url": target_url,
            "push_output": push_output,
            "status_output": status_output,
        })

    async def _tool_gh_pages_publish(self, args: dict, **ctx) -> str:
        import shutil as _shutil
        repo_path = Path(args["repo_path"]).resolve()
        build_dir = Path(args["build_dir"]).resolve()
        slug = args["slug"].strip("/")
        message = args.get("message") or f"Publish {slug}"

        if not (repo_path / ".git").exists():
            raise ValueError(f"Not a git repo: {repo_path}")
        if not build_dir.exists():
            raise FileNotFoundError(f"Build dir not found: {build_dir}")

        async def _run(cmd: str, timeout: int = 120) -> tuple[int, str]:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_path),
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, (out.decode(errors="replace") + err.decode(errors="replace"))

        code, cur = await _run("git rev-parse --abbrev-ref HEAD")
        original_branch = cur.strip() if code == 0 else None

        code, _ = await _run("git rev-parse --verify gh-pages")
        if code != 0:
            code, out = await _run("git checkout --orphan gh-pages")
            if code != 0:
                return json.dumps({"status": "error", "error": f"could not create gh-pages: {out}"})
            await _run("git rm -rf . || true")
        else:
            code, out = await _run("git checkout gh-pages")
            if code != 0:
                return json.dumps({"status": "error", "error": f"could not checkout gh-pages: {out}"})

        dest = repo_path / "docs" / slug
        if dest.exists():
            _shutil.rmtree(dest)
        _shutil.copytree(build_dir, dest)

        code, out = await _run(f'git add "docs/{slug}"')
        if code != 0:
            return json.dumps({"status": "error", "error": f"git add failed: {out}"})

        msg_escaped = message.replace('"', '\\"')
        code, out = await _run(f'git commit -m "{msg_escaped}"')
        if code != 0 and "nothing to commit" not in out:
            return json.dumps({"status": "error", "error": f"git commit failed: {out}"})

        code, push_out = await _run("git push origin gh-pages", timeout=180)
        if code != 0:
            if original_branch and original_branch != "gh-pages":
                await _run(f"git checkout {original_branch}")
            return json.dumps({"status": "error", "error": f"git push failed: {push_out}"})

        code, remote = await _run("git config --get remote.origin.url")
        target_url = None
        if code == 0:
            url = remote.strip()
            m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
            if m:
                target_url = f"https://{m.group(1)}.github.io/{m.group(2)}/{slug}/"

        if original_branch and original_branch != "gh-pages":
            await _run(f"git checkout {original_branch}")

        return json.dumps({
            "status": "ok",
            "target_url": target_url,
            "slug": slug,
            "push_output": push_out[-1000:],
        })

    async def _tool_roblox_publish(self, args: dict, **ctx) -> str:
        import os as _os
        key = _os.environ.get("ROBLOX_API_KEY")
        if not key:
            return json.dumps({"status": "error", "error": "ROBLOX_API_KEY not set"})

        rbxl_path = Path(args["rbxl_path"]).resolve()
        if not rbxl_path.exists():
            raise FileNotFoundError(f"rbxl not found: {rbxl_path}")

        universe_id = args["universe_id"]
        place_id = args["place_id"]
        version_type = args.get("version_type", "Published")
        url = (
            f"https://apis.roblox.com/universes/v1/{universe_id}/places/{place_id}/"
            f"versions?versionType={version_type}"
        )

        import httpx as _httpx
        data = rbxl_path.read_bytes()
        try:
            async with _httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "x-api-key": key,
                        "Content-Type": "application/octet-stream",
                    },
                    content=data,
                )
                if resp.status_code >= 400:
                    return json.dumps({
                        "status": "error",
                        "error": f"Roblox {resp.status_code}: {resp.text[:500]}",
                    })
                body = resp.json()
        except Exception as e:
            return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"})

        return json.dumps({
            "status": "ok",
            "version": body.get("versionNumber"),
            "version_type": version_type,
            "target_url": f"https://www.roblox.com/games/{place_id}",
        })

    # --- Path safety ---

    def _project_dir(self, project_id: str = None, agent_instance_id: str = None) -> Path:
        """Resolve project directory — uses workspace if one exists for this agent."""
        if project_id and agent_instance_id:
            workspace = Path(settings.projects_dir) / project_id / "worktrees" / agent_instance_id
            if workspace.exists():
                return workspace
        if project_id:
            return Path(settings.projects_dir) / project_id
        return Path(".")

    def _safe_path(self, relative: str, project_id: str = None, agent_instance_id: str = None) -> Path:
        """Resolve path within project directory, preventing traversal."""
        base = self._project_dir(project_id, agent_instance_id)
        resolved = (base / relative).resolve()
        base_resolved = base.resolve()

        if not str(resolved).startswith(str(base_resolved)):
            raise PermissionError(f"Path traversal blocked: {relative}")
        return resolved

    # --- Governance logging ---

    def _log_governance(
        self, agent_instance_id: str, tool_name: str, params: dict, decision: str, reason: str
    ):
        with get_studio_db() as db:
            db.execute(
                """INSERT INTO governance_log (agent_instance_id, tool_name, params, decision, reason)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_instance_id, tool_name, json.dumps(params or {}), decision, reason),
            )


# Singleton
tool_executor = ToolExecutor()
