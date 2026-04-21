"""Agent Registry — loads .md definitions, manages agent lifecycle."""
from __future__ import annotations

import re
import uuid
import yaml
from pathlib import Path
from datetime import datetime, timezone

from src.models.agents import AgentDefinition, AgentInstance, AgentStatus
from src.settings import settings
from src.database import get_studio_db


class AgentRegistry:
    def __init__(self):
        self._definitions: dict[str, AgentDefinition] = {}
        self._instances: dict[str, AgentInstance] = {}
        self._agent_config: dict = {}
        self._builtin_tools: list[str] = []

    def load_config(self, config_path: str = None):
        """Load agent routing config from agents.yaml."""
        path = Path(config_path or f"{settings.config_dir}/agents.yaml")
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            self._agent_config = data.get("agents", {})
            self._defaults = data.get("defaults", {})

        # Preload governance tiers so `tools: [builtin]` can expand to the real list.
        self._builtin_tools: list[str] = []
        gov_path = Path(f"{settings.config_dir}/governance.yaml")
        if gov_path.exists():
            with open(gov_path) as f:
                gov = yaml.safe_load(f) or {}
            self._builtin_tools = list(gov.get("builtin", [])) + list(gov.get("pre_approved", []))

    def _expand_tools(self, tools: list[str]) -> list[str]:
        """Expand shorthands into concrete tool names.

        - `builtin` expands eagerly to the governance builtin+pre_approved list.
        - `mcp` is preserved as a literal sentinel. MCP tools are discovered
          asynchronously after boot (`main.py` kicks `mcp_bridge.discover_tools()`
          well after `registry.load_agents()`), so the live list isn't known here.
          `AgentRuntime._get_agent_tools()` resolves the sentinel at prompt-build
          time against `mcp_bridge.tools` so every agent sees the full surface.
        """
        if not tools:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for t in tools:
            if t == "builtin":
                for bt in self._builtin_tools:
                    if bt not in seen:
                        out.append(bt)
                        seen.add(bt)
            elif t not in seen:
                out.append(t)
                seen.add(t)
        return out

    def load_agents(self, agents_dir: str = None):
        """Scan agents/ directory, parse .md files, register definitions."""
        base = Path(agents_dir or settings.agents_dir)
        if not base.exists():
            return

        for md_file in sorted(base.rglob("*.md")):
            try:
                defn = self._parse_agent_md(md_file)
                self._definitions[defn.id] = defn
            except Exception as e:
                print(f"Warning: failed to parse {md_file}: {e}")

        # Apply routing config overrides
        for agent_id, config in self._agent_config.items():
            if agent_id in self._definitions:
                defn = self._definitions[agent_id]
                if "model" in config:
                    defn.default_model = config["model"]
                if "fallback_model" in config:
                    defn.fallback_model = config["fallback_model"]
                if "tools" in config:
                    defn.tools = self._expand_tools(config["tools"])
                if "skills" in config:
                    defn.skills = config["skills"]
                elif "skills" in self._defaults:
                    defn.skills = list(self._defaults["skills"])
                if "budget_max_tokens" in config:
                    defn.budget_max_tokens = config["budget_max_tokens"]
                if "budget_max_usd" in config:
                    defn.budget_max_usd = config["budget_max_usd"]
                if "description" in config:
                    defn.description = config["description"]

    def _parse_agent_md(self, path: Path) -> AgentDefinition:
        """Parse a .md file with YAML frontmatter into an AgentDefinition."""
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)

        # Derive ID from filename
        agent_id = path.stem
        # Remove category prefix if present (e.g. "engineering-code-reviewer" -> "code-reviewer")
        for prefix in ["engineering-", "testing-", "game-development-"]:
            if agent_id.startswith(prefix):
                agent_id = agent_id[len(prefix):]
                break

        # Derive category from parent directory
        category = path.parent.name if path.parent.name != settings.agents_dir else ""

        defaults = getattr(self, "_defaults", {})

        return AgentDefinition(
            id=agent_id,
            name=frontmatter.get("name", agent_id),
            description=frontmatter.get("description", ""),
            category=category,
            color=frontmatter.get("color", ""),
            emoji=frontmatter.get("emoji", ""),
            vibe=frontmatter.get("vibe", ""),
            default_model=frontmatter.get("default_model", defaults.get("model", "")),
            fallback_model=frontmatter.get("fallback_model", defaults.get("fallback_model", "")),
            tools=self._expand_tools(frontmatter.get("tools", []) or []),
            skills=frontmatter.get("skills", []),
            budget_max_tokens=frontmatter.get("budget_max_tokens", defaults.get("budget_max_tokens", 0)),
            budget_max_usd=frontmatter.get("budget_max_usd", defaults.get("budget_max_usd", 0.0)),
            system_prompt=body.strip(),
            source_path=str(path),
        )

    def _split_frontmatter(self, text: str) -> tuple[dict, str]:
        """Split YAML frontmatter from markdown body."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            fm = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        return fm, match.group(2)

    # --- Definition queries ---

    def get_definition(self, agent_id: str) -> AgentDefinition | None:
        return self._definitions.get(agent_id)

    def list_definitions(self, category: str = None) -> list[AgentDefinition]:
        defs = list(self._definitions.values())
        if category:
            defs = [d for d in defs if d.category == category]
        return sorted(defs, key=lambda d: (d.category, d.name))

    def list_categories(self) -> list[str]:
        return sorted(set(d.category for d in self._definitions.values() if d.category))

    # --- Instance lifecycle ---

    def spawn(
        self,
        agent_type: str,
        project_id: str = None,
        task_id: str = None,
        model_override: str = None,
        budget_max_tokens_override: int | None = None,
    ) -> AgentInstance:
        """Create a new agent instance."""
        defn = self._definitions.get(agent_type)
        if not defn:
            raise ValueError(f"Unknown agent type: {agent_type}")

        model = model_override or defn.default_model
        provider = self._resolve_provider(model)
        budget_tokens = (
            budget_max_tokens_override
            if budget_max_tokens_override and budget_max_tokens_override > 0
            else defn.budget_max_tokens
        )

        instance = AgentInstance(
            id=f"{agent_type}-{uuid.uuid4().hex[:8]}",
            agent_type=agent_type,
            project_id=project_id,
            task_id=task_id,
            status=AgentStatus.ASSIGNED,
            model=model,
            provider=provider,
            budget_max_tokens=budget_tokens,
            budget_max_usd=defn.budget_max_usd,
            started_at=datetime.now(timezone.utc),
        )
        self._instances[instance.id] = instance
        self._persist_insert(instance)
        return instance

    def _persist_insert(self, instance: AgentInstance):
        """INSERT a freshly spawned instance into agent_instances."""
        try:
            with get_studio_db() as db:
                db.execute(
                    """INSERT OR REPLACE INTO agent_instances
                       (id, agent_type, project_id, task_id, status, model, provider,
                        tokens_used, cost_usd, started_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.0, ?, NULL)""",
                    (
                        instance.id,
                        instance.agent_type,
                        instance.project_id,
                        instance.task_id,
                        instance.status.value,
                        instance.model,
                        instance.provider,
                        instance.started_at.isoformat() if instance.started_at else None,
                    ),
                )
        except Exception as e:
            print(f"Warning: failed to persist agent instance {instance.id}: {e}")

    def _persist_update(self, instance_id: str, **fields):
        """UPDATE fields on an existing agent_instances row."""
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields.keys())
        values = list(fields.values()) + [instance_id]
        try:
            with get_studio_db() as db:
                db.execute(
                    f"UPDATE agent_instances SET {cols} WHERE id=?",
                    values,
                )
        except Exception as e:
            print(f"Warning: failed to update agent instance {instance_id}: {e}")

    def get_instance(self, instance_id: str) -> AgentInstance | None:
        return self._instances.get(instance_id)

    def list_instances(
        self, project_id: str = None, status: AgentStatus = None
    ) -> list[AgentInstance]:
        instances = list(self._instances.values())
        if project_id:
            instances = [i for i in instances if i.project_id == project_id]
        if status:
            instances = [i for i in instances if i.status == status]
        return instances

    def update_status(self, instance_id: str, status: AgentStatus):
        inst = self._instances.get(instance_id)
        if inst:
            inst.status = status
            fields = {"status": status.value}
            if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.TERMINATED):
                inst.completed_at = datetime.now(timezone.utc)
                fields["completed_at"] = inst.completed_at.isoformat()
            self._persist_update(instance_id, **fields)

    def record_usage(self, instance_id: str, tokens_used: int, cost_usd: float):
        """Persist final token + cost totals at end of a run."""
        inst = self._instances.get(instance_id)
        if inst:
            inst.tokens_used = tokens_used
            inst.cost_usd = cost_usd
        self._persist_update(instance_id, tokens_used=tokens_used, cost_usd=cost_usd)

    def terminate(self, instance_id: str):
        self.update_status(instance_id, AgentStatus.TERMINATED)

    def _resolve_provider(self, model: str) -> str:
        """Extract provider from model string like 'openrouter/qwen/qwen3-coder:free'."""
        if model.startswith("openrouter/"):
            return "openrouter"
        elif model.startswith("omlx/"):
            return "omlx"
        elif model.startswith("anthropic/"):
            return "anthropic"
        elif model.startswith("openai/"):
            return "openai"
        return "omlx"  # default — OpenRouter retired, local Qwen is the baseline


# Singleton
registry = AgentRegistry()
