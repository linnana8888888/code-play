"""Agent Registry — loads .md definitions, manages agent lifecycle."""
from __future__ import annotations

import re
import uuid
import yaml
from pathlib import Path
from datetime import datetime, timezone

from src.models.agents import AgentDefinition, AgentInstance, AgentStatus
from src.settings import settings


class AgentRegistry:
    def __init__(self):
        self._definitions: dict[str, AgentDefinition] = {}
        self._instances: dict[str, AgentInstance] = {}
        self._agent_config: dict = {}

    def load_config(self, config_path: str = None):
        """Load agent routing config from agents.yaml."""
        path = Path(config_path or f"{settings.config_dir}/agents.yaml")
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            self._agent_config = data.get("agents", {})
            self._defaults = data.get("defaults", {})

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
                    defn.tools = config["tools"]
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
            tools=frontmatter.get("tools", []),
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
    ) -> AgentInstance:
        """Create a new agent instance."""
        defn = self._definitions.get(agent_type)
        if not defn:
            raise ValueError(f"Unknown agent type: {agent_type}")

        model = model_override or defn.default_model
        provider = self._resolve_provider(model)

        instance = AgentInstance(
            id=f"{agent_type}-{uuid.uuid4().hex[:8]}",
            agent_type=agent_type,
            project_id=project_id,
            task_id=task_id,
            status=AgentStatus.ASSIGNED,
            model=model,
            provider=provider,
            started_at=datetime.now(timezone.utc),
        )
        self._instances[instance.id] = instance
        return instance

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
            if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.TERMINATED):
                inst.completed_at = datetime.now(timezone.utc)

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
        return "openrouter"  # default


# Singleton
registry = AgentRegistry()
