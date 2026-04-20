"""Artifact template injection — loads structured templates for pipeline artifacts.

When an agent's task prompt references a known artifact key (e.g., "Save to memory
as artifact key 'mechanics_v1'"), this module finds the matching template file and
returns its content for injection into the agent's system prompt.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger("code_play.runtime.artifact_templates")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "artifact_templates.yaml"

_artifact_map: dict[str, str] = {}
_template_cache: dict[str, str] = {}


def _load_config() -> None:
    """Load artifact_templates.yaml into _artifact_map."""
    global _artifact_map
    if _artifact_map:
        return
    if not _CONFIG_PATH.exists():
        logger.warning("artifact_templates.yaml not found at %s", _CONFIG_PATH)
        return
    with open(_CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    _artifact_map = data.get("artifact_templates", {})
    logger.info("Loaded %d artifact template mappings", len(_artifact_map))


_ARTIFACT_KEY_RE = re.compile(
    r"""(?:artifact\s+key\s+|as\s+artifact\s+|Save.*?as\s+|save\s+to\s+memory\s+as\s+)"""
    r"""['"](\w+)['"]""",
    re.IGNORECASE,
)


def _extract_artifact_keys(text: str) -> list[str]:
    """Extract artifact key names from task prompt text."""
    return _ARTIFACT_KEY_RE.findall(text)


def _read_template(rel_path: str) -> str | None:
    """Read a template file, returning cached content or None."""
    if rel_path in _template_cache:
        return _template_cache[rel_path]
    full_path = _PROJECT_ROOT / rel_path
    if not full_path.exists():
        logger.warning("Template file not found: %s", full_path)
        return None
    content = full_path.read_text()
    _template_cache[rel_path] = content
    return content


def get_template_for_task(task_prompt: str) -> str | None:
    """Scan a task prompt for artifact key references and return the matching template.

    Returns the first matching template content, or None if no artifact key
    is referenced or no template exists for the referenced key.
    """
    _load_config()
    if not _artifact_map:
        return None

    keys = _extract_artifact_keys(task_prompt)
    for key in keys:
        if key in _artifact_map:
            content = _read_template(_artifact_map[key])
            if content:
                logger.debug("Matched artifact '%s' → %s", key, _artifact_map[key])
                return content

    return None
