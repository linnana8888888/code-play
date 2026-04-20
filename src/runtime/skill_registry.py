"""Skill Registry — loads .md skill definitions and manages injection with permissions.

Skills are markdown files with YAML frontmatter, similar to agent definitions.
They provide runtime-injectable knowledge/workflows for agents.
Skills are restricted by default — agents must get approval to use non-builtin skills.
"""
from __future__ import annotations

import re
import yaml
from pathlib import Path

from src.settings import settings
from src.database import get_studio_db


class SkillDefinition:
    """A parsed skill definition from a .md file."""
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        category: str = "",
        content: str = "",
        source_path: str = "",
    ):
        self.id = id
        self.name = name
        self.description = description
        self.category = category
        self.content = content
        self.source_path = source_path


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}
        self._builtin_skills: set[str] = set()
        self._approved_grants: dict[str, set[str]] = {}  # agent_type -> set of skill_ids

    def load_skills(self, skills_dir: str = None):
        """Scan skills/ directory, parse .md files, register definitions."""
        base = Path(skills_dir or getattr(settings, "skills_dir", "skills"))
        if not base.exists():
            return

        for md_file in sorted(base.rglob("*.md")):
            try:
                skill = self._parse_skill_md(md_file)
                self._skills[skill.id] = skill
            except Exception as e:
                print(f"Warning: failed to parse skill {md_file}: {e}")

    def load_claude_plugin_skills(self, skills) -> int:
        """Ingest skills discovered from ~/.claude (user + enabled plugins).

        `skills` is an iterable of src.runtime.claude_bridge.SkillDef. All of these
        are auto-approved because the user already enabled the host plugin in
        Claude Code. Returns number of skills added.
        """
        added = 0
        for s in skills:
            if s.id in self._skills:
                continue
            self._skills[s.id] = SkillDefinition(
                id=s.id,
                name=s.name,
                description=s.description,
                category=s.source,           # "user" or plugin id
                content=s.body,
                source_path=s.path,
            )
            self._builtin_skills.add(s.id)   # no approval prompt — host already trusted it
            added += 1
        return added

    def load_governance(self, config_path: str = None):
        """Load builtin_skills list from governance.yaml."""
        path = Path(config_path or f"{settings.config_dir}/governance.yaml")
        if not path.exists():
            return

        with open(path) as f:
            data = yaml.safe_load(f)

        for skill_id in data.get("builtin_skills", []):
            self._builtin_skills.add(skill_id)

    def _parse_skill_md(self, path: Path) -> SkillDefinition:
        """Parse a skill .md file with YAML frontmatter."""
        text = path.read_text(encoding="utf-8")

        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if match:
            try:
                fm = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                fm = {}
            body = match.group(2)
        else:
            fm = {}
            body = text

        skill_id = path.stem
        category = path.parent.name if path.parent.name != "skills" else ""

        return SkillDefinition(
            id=skill_id,
            name=fm.get("name", skill_id),
            description=fm.get("description", ""),
            category=category,
            content=body.strip(),
            source_path=str(path),
        )

    # --- Queries ---

    def get_skill(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillDefinition]:
        return sorted(self._skills.values(), key=lambda s: s.id)

    def get_builtin_skills(self) -> list[str]:
        """Return sorted IDs of every auto-approved skill.

        Combines governance-marked `builtin_skills` with skills discovered from
        `~/.claude` (user + enabled plugins) via `load_claude_plugin_skills`.
        Agents without explicit `skills:` frontmatter auto-seed from this list
        so they match the Claude Code CLI surface.
        """
        return sorted(self._builtin_skills)

    def catalog_for_prompt(self, max_desc_chars: int = 120) -> str:
        """One-line-per-skill catalog for system-prompt injection.

        Lists every registered skill — not just builtins — so the agent knows
        which `skill_invoke(<id>)` calls the governance layer will accept.
        Non-builtin skills still go through the approval queue at call time.
        Format: `- <id> — <description-truncated>`.
        """
        lines: list[str] = []
        for skill in sorted(self._skills.values(), key=lambda s: s.id):
            desc = (skill.description or "").strip().replace("\n", " ")
            if len(desc) > max_desc_chars:
                desc = desc[: max_desc_chars - 1].rstrip() + "…"
            tag = "" if skill.id in self._builtin_skills else " [needs approval]"
            lines.append(f"- {skill.id}{tag} — {desc}" if desc else f"- {skill.id}{tag}")
        return "\n".join(lines)

    # --- Permission model ---

    def is_builtin(self, skill_id: str) -> bool:
        return skill_id in self._builtin_skills

    def is_approved(self, skill_id: str, agent_type: str) -> bool:
        """Check if an agent type has been granted access to a skill."""
        if self.is_builtin(skill_id):
            return True
        return skill_id in self._approved_grants.get(agent_type, set())

    def approve(self, skill_id: str, agent_type: str, approved_by: str = "human"):
        """Grant an agent type access to a skill."""
        if agent_type not in self._approved_grants:
            self._approved_grants[agent_type] = set()
        self._approved_grants[agent_type].add(skill_id)

        # Log to DB
        try:
            with get_studio_db() as db:
                db.execute(
                    """INSERT INTO governance_log (agent_instance_id, tool_name, params, decision, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (agent_type, f"skill:{skill_id}", "{}", "approved", f"Approved by {approved_by}"),
                )
        except Exception:
            pass

    def deny(self, skill_id: str, agent_type: str):
        """Revoke an agent type's access to a skill."""
        grants = self._approved_grants.get(agent_type, set())
        grants.discard(skill_id)

    # --- Injection ---

    def get_injectable_content(self, agent_type: str, skill_ids: list[str]) -> str:
        """Build skill content block for injection into agent conversation.

        Only includes skills that are builtin or explicitly approved.
        Returns formatted string ready for system prompt injection.
        """
        parts = []
        for skill_id in skill_ids:
            if not self.is_approved(skill_id, agent_type):
                continue
            skill = self._skills.get(skill_id)
            if skill:
                parts.append(f"## Skill: {skill.name}\n{skill.content}")

        if not parts:
            return ""
        return "\n\n[Available Skills]\n" + "\n\n".join(parts)

    def get_unapproved_skills(self, agent_type: str, skill_ids: list[str]) -> list[str]:
        """Return skill IDs that the agent needs approval for."""
        return [
            sid for sid in skill_ids
            if sid in self._skills and not self.is_approved(sid, agent_type)
        ]


# Singleton
skill_registry = SkillRegistry()
