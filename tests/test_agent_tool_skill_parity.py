"""Claude-Code-parity for agents — MCP tools + skills surface.

Locks the contract behind commit 2026-04-20:
  - Every agent in `config/agents.yaml` opts into `builtin` AND `mcp`.
  - Every id in that config maps to a real `.md` under `agents/`.
  - `AgentRegistry._expand_tools` preserves the `mcp` sentinel (defers expansion).
  - `AgentRuntime._get_agent_tools` resolves `mcp` against the live bridge catalog.
  - `SkillRegistry` exposes `get_builtin_skills()` + `catalog_for_prompt()`,
    and the runtime auto-seeds `defn.skills` from the builtin set when empty.

If any of these regress, the fleet silently loses access to the Claude Code plugin
surface — exactly the bug this session fixed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.orchestrator.agent_registry import AgentRegistry
from src.runtime.agent_runtime import AgentRuntime
from src.runtime.skill_registry import SkillRegistry
from src.runtime.mcp_bridge import MCPTool


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_YAML = REPO_ROOT / "config" / "agents.yaml"
GOVERNANCE_YAML = REPO_ROOT / "config" / "governance.yaml"
AGENTS_DIR = REPO_ROOT / "agents"


def _load_agents_yaml() -> dict:
    with AGENTS_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _make_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.load_config(str(AGENTS_YAML))
    return reg


# ---------------------------------------------------------------------------
# _expand_tools — shorthand handling
# ---------------------------------------------------------------------------

def test_expand_tools_builtin_pulls_governance_list_without_mcp():
    reg = _make_registry()
    expanded = reg._expand_tools(["builtin"])
    # Pulled governance builtins
    assert "file_read" in expanded
    assert "bash_execute" in expanded
    assert "skill_invoke" in expanded
    # MCP is a separate sentinel, not implied by `builtin`
    assert "mcp" not in expanded


def test_expand_tools_preserves_mcp_sentinel():
    reg = _make_registry()
    expanded = reg._expand_tools(["builtin", "mcp"])
    assert "mcp" in expanded, "mcp must survive _expand_tools for late binding"
    # governance builtins still present
    assert "file_read" in expanded


def test_expand_tools_preserves_restricted_extras():
    reg = _make_registry()
    expanded = reg._expand_tools(["builtin", "mcp", "git_push"])
    assert "git_push" in expanded
    assert "mcp" in expanded


# ---------------------------------------------------------------------------
# _get_agent_tools — late-bind mcp against the live bridge catalog
# ---------------------------------------------------------------------------

def test_get_agent_tools_resolves_mcp_sentinel(monkeypatch):
    from src.runtime import tool_executor as te_mod
    from src.runtime import mcp_bridge as bridge_mod
    from src.models.agents import AgentDefinition

    # Load real governance so file_read has a schema to return.
    te_mod.tool_executor.load_governance(str(GOVERNANCE_YAML))

    fake_tool = MCPTool(
        namespaced_name="mcp__figma__get_code",
        server="figma",
        plugin="figma@claude-plugins-official",
        original_name="get_code",
        description="figma get_code",
        input_schema={"type": "object", "properties": {}},
    )
    monkeypatch.setattr(
        bridge_mod.mcp_bridge,
        "_tools",
        {fake_tool.namespaced_name: fake_tool},
        raising=False,
    )
    # Also register a schema for the MCP tool so get_tool_schemas picks it up.
    te_mod.tool_executor._tool_schemas[fake_tool.namespaced_name] = {
        "name": fake_tool.namespaced_name,
        "description": fake_tool.description,
        "parameters": fake_tool.input_schema,
    }

    defn = AgentDefinition(
        id="fake-agent", name="fake", description="", tools=["file_read", "mcp"]
    )
    schemas = AgentRuntime()._get_agent_tools(defn)
    names = {s.get("name") for s in schemas}
    assert "file_read" in names
    assert fake_tool.namespaced_name in names

    # Cleanup so we don't leak into neighbours.
    te_mod.tool_executor._tool_schemas.pop(fake_tool.namespaced_name, None)


def test_resolve_mcp_sentinel_is_noop_without_token():
    assert AgentRuntime._resolve_mcp_sentinel(["file_read", "bash_execute"]) == [
        "file_read",
        "bash_execute",
    ]


# ---------------------------------------------------------------------------
# Skill registry accessors
# ---------------------------------------------------------------------------

def test_skill_registry_builtin_list_covers_governance_entries():
    reg = SkillRegistry()
    reg.load_governance(str(GOVERNANCE_YAML))
    builtins = reg.get_builtin_skills()
    # From governance.yaml's builtin_skills block.
    for expected in ("coding-standards", "git-workflow", "testing-patterns", "asset-sources"):
        assert expected in builtins


def test_skill_registry_catalog_for_prompt_marks_unapproved(tmp_path):
    reg = SkillRegistry()
    reg.load_governance(str(GOVERNANCE_YAML))
    # Inject a fake skill that is NOT in builtin_skills.
    from src.runtime.skill_registry import SkillDefinition

    reg._skills["custom-helper"] = SkillDefinition(
        id="custom-helper",
        name="Custom Helper",
        description="short description",
        content="",
        source_path="",
    )
    # And a fake builtin skill (one of the governance-declared ids) so the
    # catalog reflects both tiers.
    reg._skills["coding-standards"] = SkillDefinition(
        id="coding-standards",
        name="Coding Standards",
        description="auto-approved",
        content="",
        source_path="",
    )
    catalog = reg.catalog_for_prompt()
    assert "coding-standards" in catalog
    assert "custom-helper" in catalog
    # Non-builtin tagged with [needs approval], builtin is not.
    custom_line = next(line for line in catalog.splitlines() if "custom-helper" in line)
    builtin_line = next(line for line in catalog.splitlines() if "coding-standards" in line)
    assert "[needs approval]" in custom_line
    assert "[needs approval]" not in builtin_line


# ---------------------------------------------------------------------------
# Auto-seed skills in _build_initial_conversation
# ---------------------------------------------------------------------------

def test_build_initial_conversation_auto_seeds_builtin_skills(monkeypatch):
    from src.models.agents import AgentDefinition
    from src.runtime import agent_runtime as runtime_mod

    # Replace the module-level skill_registry with a primed fake so the test
    # doesn't depend on the real singleton's state.
    fake = SkillRegistry()
    fake.load_governance(str(GOVERNANCE_YAML))
    from src.runtime.skill_registry import SkillDefinition
    fake._skills["coding-standards"] = SkillDefinition(
        id="coding-standards",
        name="Coding Standards",
        description="do the right thing",
        content="# Coding Standards body",
        source_path="",
    )
    monkeypatch.setattr(runtime_mod, "skill_registry", fake)

    defn = AgentDefinition(
        id="auto-seed-agent",
        name="auto",
        description="",
        system_prompt="[SYSTEM PROMPT]",
        skills=[],  # empty → auto-seed
    )
    msgs = AgentRuntime()._build_initial_conversation(defn, "do it")
    system = msgs[0]["content"]
    assert "## Skill: Coding Standards" in system
    assert "## Available skills (invoke via `skill_invoke(skill_id)`):" in system
    assert "- coding-standards" in system


def test_build_initial_conversation_respects_explicit_skill_list(monkeypatch):
    from src.models.agents import AgentDefinition
    from src.runtime import agent_runtime as runtime_mod
    from src.runtime.skill_registry import SkillDefinition

    fake = SkillRegistry()
    fake.load_governance(str(GOVERNANCE_YAML))
    fake._skills["coding-standards"] = SkillDefinition(
        id="coding-standards", name="Coding Standards",
        description="auto-approved",
        content="# body-a", source_path="",
    )
    fake._skills["custom-helper"] = SkillDefinition(
        id="custom-helper", name="Custom Helper",
        description="explicit",
        content="# body-b", source_path="",
    )
    fake.approve("custom-helper", "pick-agent")
    monkeypatch.setattr(runtime_mod, "skill_registry", fake)

    defn = AgentDefinition(
        id="pick-agent",
        name="pick",
        description="",
        system_prompt="[SYSTEM PROMPT]",
        skills=["custom-helper"],
    )
    msgs = AgentRuntime()._build_initial_conversation(defn, "do it")
    system = msgs[0]["content"]
    assert "## Skill: Custom Helper" in system
    # Builtin auto-seed is suppressed — only the explicit list is injected.
    assert "## Skill: Coding Standards" not in system
    # Catalog line is always appended.
    assert "## Available skills" in system


# ---------------------------------------------------------------------------
# Lock tests — the config stays Claude-Code-parity
# ---------------------------------------------------------------------------

def test_every_agent_in_yaml_declares_builtin_and_mcp():
    cfg = _load_agents_yaml()
    missing = []
    for agent_id, block in (cfg.get("agents") or {}).items():
        tools = block.get("tools") or []
        if "builtin" not in tools or "mcp" not in tools:
            missing.append((agent_id, tools))
    assert not missing, (
        "every agent must opt into builtin + mcp for Claude-Code parity; "
        f"violators: {missing}"
    )


def test_every_agent_id_maps_to_a_markdown_file():
    cfg = _load_agents_yaml()
    md_ids = set()
    for md in AGENTS_DIR.rglob("*.md"):
        agent_id = md.stem
        for prefix in ("engineering-", "testing-", "game-development-"):
            if agent_id.startswith(prefix):
                agent_id = agent_id[len(prefix):]
                break
        md_ids.add(agent_id)
    orphans = [aid for aid in (cfg.get("agents") or {}) if aid not in md_ids]
    assert orphans == [], f"agents.yaml ids without a matching .md: {orphans}"


def test_publisher_no_longer_references_package_html():
    tools = (_load_agents_yaml()["agents"]["publisher"]["tools"])
    assert "package_html" not in tools
    doc = (AGENTS_DIR / "production" / "publisher.md").read_text(encoding="utf-8")
    assert "package_html" not in doc
