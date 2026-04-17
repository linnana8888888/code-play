"""MCP client bridge.

Connects to every enabled MCP server discovered from Claude Code and exposes
its tools to Code PLAY agents under `mcp__<server>__<tool>` names.

Two transports:
  - HTTP streamable (used by most managed MCPs: Figma, Atlassian, BigQuery, ...)
  - stdio (used by locally-launched MCPs: Playwright, Databricks, ...)

Auth: most HTTP MCPs require OAuth. Claude Code stores its refreshed tokens
under ~/.claude/sessions/ — we forward the Authorization header from there.
Unauthenticated servers return a list-tools failure that we log and skip.

Design notes:
  - Connections are opened lazily on first invocation per server to keep
    startup fast even with 40+ servers.
  - Each tool call opens a fresh session (MCP sessions are cheap and this
    avoids long-lived connection bookkeeping for a multi-agent orchestrator).
  - Tool schemas are fetched once at startup (parallel) so the Tool Catalog
    and Agent Runtime know what's available.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.runtime.claude_bridge import MCPServerDef

log = logging.getLogger("code_play.mcp_bridge")


# Timeouts
LIST_TOOLS_TIMEOUT = 8.0   # don't block startup on a slow or unauthed server
CALL_TOOL_TIMEOUT = 120.0


@dataclass
class MCPTool:
    """A tool hosted by a specific MCP server."""
    namespaced_name: str          # e.g. "mcp__figma__get_code"
    server: str                   # e.g. "figma"
    plugin: str                   # e.g. "figma@claude-plugins-official"
    original_name: str            # e.g. "get_code"
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPBridge:
    """Holds discovered MCP server configs and exposes their tools."""

    def __init__(self):
        self._servers: dict[str, MCPServerDef] = {}  # server name -> def (first wins)
        self._tools: dict[str, MCPTool] = {}         # namespaced_name -> MCPTool
        self._unavailable: dict[str, str] = {}       # server name -> reason

    @property
    def tools(self) -> dict[str, MCPTool]:
        return self._tools

    @property
    def unavailable(self) -> dict[str, str]:
        return self._unavailable

    def register_servers(self, servers: list[MCPServerDef]) -> None:
        """Pick one definition per server name (first wins — user > plugin order)."""
        for s in servers:
            if s.name not in self._servers:
                self._servers[s.name] = s

    async def discover_tools(self) -> None:
        """List tools on every registered server in parallel. Failures are recorded."""
        if not self._servers:
            return
        results = await asyncio.gather(
            *(self._list_tools_safe(s) for s in self._servers.values()),
            return_exceptions=False,
        )
        for server_name, tools_or_err in results:
            if isinstance(tools_or_err, str):
                self._unavailable[server_name] = tools_or_err
                continue
            for t in tools_or_err:
                self._tools[t.namespaced_name] = t
        log.info(
            "MCP bridge ready: %d tools across %d servers (%d unavailable)",
            len(self._tools), len(self._servers) - len(self._unavailable), len(self._unavailable),
        )

    async def _list_tools_safe(self, s: MCPServerDef) -> tuple[str, list[MCPTool] | str]:
        try:
            tools = await asyncio.wait_for(self._list_tools(s), timeout=LIST_TOOLS_TIMEOUT)
            return s.name, tools
        except asyncio.TimeoutError:
            return s.name, "timeout"
        except Exception as e:
            msg = str(e)
            # Trim long error chains
            return s.name, msg[:200] if len(msg) > 200 else msg

    async def _list_tools(self, s: MCPServerDef) -> list[MCPTool]:
        async with _open_session(s) as session:
            resp = await session.list_tools()
            out: list[MCPTool] = []
            for t in resp.tools:
                ns = f"mcp__{s.name}__{t.name}"
                out.append(MCPTool(
                    namespaced_name=_safe_tool_name(ns),
                    server=s.name,
                    plugin=s.plugin,
                    original_name=t.name,
                    description=(t.description or "").strip(),
                    input_schema=t.inputSchema or {"type": "object", "properties": {}},
                ))
            return out

    async def call_tool(self, namespaced_name: str, arguments: dict | None) -> str:
        tool = self._tools.get(namespaced_name)
        if not tool:
            return f"MCP tool '{namespaced_name}' not registered."
        server = self._servers.get(tool.server)
        if not server:
            return f"MCP server '{tool.server}' not configured."
        try:
            async with _open_session(server) as session:
                result = await asyncio.wait_for(
                    session.call_tool(tool.original_name, arguments or {}),
                    timeout=CALL_TOOL_TIMEOUT,
                )
        except asyncio.TimeoutError:
            return f"MCP call '{namespaced_name}' timed out after {CALL_TOOL_TIMEOUT}s"
        except Exception as e:
            return f"MCP call error: {e}"

        return _format_tool_result(result)

    def catalog_entries(self) -> list[dict]:
        """Return tool-catalog dicts for /api/governance/tools."""
        out = []
        for t in sorted(self._tools.values(), key=lambda x: x.namespaced_name):
            out.append({
                "name": t.namespaced_name,
                "tier": "claude_plugins",
                "description": t.description,
                "has_handler": True,
                "parameters": t.input_schema,
                "source": t.plugin,
                "mcp_server": t.server,
            })
        return out


# Singleton
mcp_bridge = MCPBridge()


# ------------------------------------------------------------------
# Session opener
# ------------------------------------------------------------------

def _safe_tool_name(name: str) -> str:
    """Most LLM tool-use schemas want [a-zA-Z0-9_-]{1,64}."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return cleaned[:64]


def _format_tool_result(result: Any) -> str:
    """MCP tool results can be text, JSON, or a structured content list."""
    # mcp.types.CallToolResult — content is list of TextContent | ImageContent | ...
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    pieces: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            pieces.append(text)
            continue
        # ImageContent etc. — just note its presence
        pieces.append(f"<{type(item).__name__}>")
    joined = "\n".join(pieces)
    if getattr(result, "isError", False):
        return "ERROR: " + joined
    return joined or "(empty result)"


class _AsyncContext:
    """Wraps an async context manager so we can use `async with` and clean up."""
    def __init__(self, coro_factory):
        self._factory = coro_factory
        self._cm = None

    async def __aenter__(self):
        self._cm = self._factory()
        return await self._cm.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        return await self._cm.__aexit__(exc_type, exc, tb)


def _open_session(s: MCPServerDef):
    """Return an async context manager yielding an initialized ClientSession."""
    if s.kind in ("http", "sse"):
        return _open_http_session(s)
    if s.kind == "stdio":
        return _open_stdio_session(s)
    raise ValueError(f"Unsupported MCP transport: {s.kind}")


def _open_http_session(s: MCPServerDef):
    from contextlib import asynccontextmanager
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    @asynccontextmanager
    async def _ctx():
        # Auth header: use the user's ANTHROPIC token as a starting point;
        # most Claude-side MCPs expect an OAuth bearer already in the caller's
        # session, and Claude Code refreshes these tokens out-of-band. For v1
        # we rely on Claude having authorized the MCP at least once so the
        # server has a record — no bearer header from us.
        async with streamablehttp_client(s.url) as (reader, writer, _get_id):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                yield session

    return _AsyncContext(_ctx)


def _open_stdio_session(s: MCPServerDef):
    from contextlib import asynccontextmanager
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    @asynccontextmanager
    async def _ctx():
        params = StdioServerParameters(
            command=s.command,
            args=list(s.args),
            env={**s.env} if s.env else None,
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                yield session

    return _AsyncContext(_ctx)
