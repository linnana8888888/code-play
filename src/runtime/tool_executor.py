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

        # web_search
        self._register("web_search", self._tool_web_search, {
            "name": "web_search",
            "description": "Search the web for information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
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
        # Placeholder — will integrate with a search API
        return f"Web search not yet implemented. Query: {args['query']}"

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
