"""Claude Code plugin discovery.

Reads ~/.claude/settings.json `enabledPlugins` and resolves each plugin's
installed location via ~/.claude/plugins/installed_plugins.json. Parses each
plugin's `.mcp.json` for MCP server definitions and its `skills/` dir for
SKILL.md files. Also collects user-level skills from ~/.claude/skills/.

The discovery output is passed to mcp_bridge (for MCP tool registration) and
skill_registry (for skill loading). Agents in Code PLAY get the same plugin
surface the host Claude Code CLI has enabled.
"""
from __future__ import annotations

import json
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CLAUDE_HOME = Path.home() / ".claude"


@dataclass
class MCPServerDef:
    """A discovered MCP server — one per enabled plugin per server entry."""
    name: str                    # e.g. "figma"
    plugin: str                  # e.g. "figma@claude-plugins-official"
    kind: str                    # "http" | "sse" | "stdio"
    url: str | None = None       # for http/sse
    command: str | None = None   # for stdio
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SkillDef:
    """A discovered skill — frontmatter + body."""
    id: str                      # full id e.g. "superpowers:brainstorming"
    name: str                    # slug
    description: str
    source: str                  # "user" | plugin id
    path: str                    # absolute path to SKILL.md
    body: str                    # full markdown after frontmatter


@dataclass
class Discovery:
    mcp_servers: list[MCPServerDef]
    skills: list[SkillDef]
    enabled_plugins: list[str]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return {}, m.group(2)


def _parse_skill_file(path: Path, source: str, prefix: str | None) -> SkillDef | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _split_frontmatter(text)
    name = fm.get("name") or path.parent.name
    slug = re.sub(r"[^a-z0-9_-]", "-", str(name).lower()).strip("-")
    skill_id = f"{prefix}:{slug}" if prefix else slug
    return SkillDef(
        id=skill_id,
        name=slug,
        description=str(fm.get("description", "")).strip(),
        source=source,
        path=str(path),
        body=body.strip(),
    )


def _plugin_install_paths(installed: dict, plugin_id: str) -> list[Path]:
    """Return install paths for a plugin id like 'figma@claude-plugins-official'."""
    plugins = installed.get("plugins", {})
    entries = plugins.get(plugin_id, [])
    paths: list[Path] = []
    for entry in entries:
        p = entry.get("installPath")
        if p:
            paths.append(Path(p))
    return paths


def _load_mcp_servers(plugin_id: str, install_path: Path) -> list[MCPServerDef]:
    mcp_file = install_path / ".mcp.json"
    data = _load_json(mcp_file)
    if not data:
        return []

    # Two known shapes:
    #   { "mcpServers": { name: {...} } }
    #   { name: {...} }   (playwright uses this flat shape)
    servers = data.get("mcpServers") if isinstance(data, dict) and "mcpServers" in data else data
    if not isinstance(servers, dict):
        return []

    out: list[MCPServerDef] = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        kind = cfg.get("type") or ("stdio" if cfg.get("command") else "")
        url = cfg.get("url") or None
        # Skip empty-URL entries (e.g. snowflake placeholder)
        if kind in ("http", "sse") and not url:
            continue
        if kind == "" and cfg.get("command"):
            kind = "stdio"
        out.append(MCPServerDef(
            name=name,
            plugin=plugin_id,
            kind=kind or "http",
            url=url,
            command=cfg.get("command"),
            args=list(cfg.get("args") or []),
            env=dict(cfg.get("env") or {}),
        ))
    return out


def _load_plugin_skills(plugin_id: str, install_path: Path) -> list[SkillDef]:
    skills_dir = install_path / "skills"
    if not skills_dir.exists():
        return []
    out: list[SkillDef] = []
    short_plugin = plugin_id.split("@", 1)[0]
    for skill_md in skills_dir.rglob("SKILL.md"):
        skill = _parse_skill_file(skill_md, source=plugin_id, prefix=short_plugin)
        if skill:
            out.append(skill)
    return out


def _load_user_skills() -> list[SkillDef]:
    user_skills = CLAUDE_HOME / "skills"
    if not user_skills.exists():
        return []
    out: list[SkillDef] = []
    for skill_md in user_skills.rglob("SKILL.md"):
        skill = _parse_skill_file(skill_md, source="user", prefix=None)
        if skill:
            out.append(skill)
    return out


def discover() -> Discovery:
    """Main entry — read Claude Code config and return everything enabled."""
    settings = _load_json(CLAUDE_HOME / "settings.json") or {}
    installed = _load_json(CLAUDE_HOME / "plugins" / "installed_plugins.json") or {}

    enabled = [pid for pid, on in (settings.get("enabledPlugins") or {}).items() if on]

    # Also pick up user-level MCP servers (settings.json → mcpServers, if set)
    user_mcps: list[MCPServerDef] = []
    for name, cfg in (settings.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        user_mcps.append(MCPServerDef(
            name=name,
            plugin="user",
            kind=cfg.get("type") or ("stdio" if cfg.get("command") else "http"),
            url=cfg.get("url"),
            command=cfg.get("command"),
            args=list(cfg.get("args") or []),
            env=dict(cfg.get("env") or {}),
        ))

    mcp_servers: list[MCPServerDef] = list(user_mcps)
    skills: list[SkillDef] = _load_user_skills()

    for plugin_id in enabled:
        for path in _plugin_install_paths(installed, plugin_id):
            mcp_servers.extend(_load_mcp_servers(plugin_id, path))
            skills.extend(_load_plugin_skills(plugin_id, path))

    # Dedupe MCPs by (plugin, name) — some plugins list the same server twice across versions
    seen: set[tuple[str, str]] = set()
    deduped_mcps: list[MCPServerDef] = []
    for s in mcp_servers:
        key = (s.plugin, s.name)
        if key in seen:
            continue
        seen.add(key)
        deduped_mcps.append(s)

    # Dedupe skills by id
    seen_ids: set[str] = set()
    deduped_skills: list[SkillDef] = []
    for sk in skills:
        if sk.id in seen_ids:
            continue
        seen_ids.add(sk.id)
        deduped_skills.append(sk)

    return Discovery(
        mcp_servers=deduped_mcps,
        skills=deduped_skills,
        enabled_plugins=enabled,
    )
