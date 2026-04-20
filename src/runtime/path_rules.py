"""Path-scoped rules — auto-inject domain rules into agent prompts.

Loads glob→rules mappings from config/path_rules.yaml. When building an
agent's system prompt, the runtime calls `match_rules(text)` with the task
prompt + context. Every file path found in the text is matched against the
configured patterns; all matching rule blocks are returned, deduped by label.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger("code_play.runtime.path_rules")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "path_rules.yaml"

_PATH_PATTERN = re.compile(
    r"""(?:^|[\s"'`(])"""
    r"("
    r"(?:artifacts|src|config|agents|skills|tests|dashboard|prototypes|games|templates)"
    r"(?:/[\w.*{}\[\]-]+)+"
    r")",
    re.MULTILINE,
)


class PathRuleSet:
    __slots__ = ("pattern", "label", "rules")

    def __init__(self, pattern: str, label: str, rules: str):
        self.pattern = pattern
        self.label = label
        self.rules = rules.strip()


_rule_sets: list[PathRuleSet] = []
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not _CONFIG_PATH.exists():
        logger.debug("No path_rules.yaml found — path-scoped rules disabled")
        return
    try:
        with open(_CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        for entry in data.get("rules", []):
            _rule_sets.append(
                PathRuleSet(
                    pattern=entry["pattern"],
                    label=entry["label"],
                    rules=entry["rules"],
                )
            )
        logger.info("Loaded %d path-scoped rule sets", len(_rule_sets))
    except Exception:
        logger.exception("Failed to load path_rules.yaml")


def _extract_paths(text: str) -> set[str]:
    return {m.group(1) for m in _PATH_PATTERN.finditer(text)}


def _matches(path: str, pattern: str) -> bool:
    if "**" in pattern:
        prefix = pattern.split("**")[0].rstrip("/")
        return path.startswith(prefix) or fnmatch.fnmatch(path, pattern)
    return fnmatch.fnmatch(path, pattern)


def match_rules(text: str) -> str | None:
    """Return assembled rules block for all paths mentioned in *text*, or None."""
    _load()
    if not _rule_sets:
        return None

    paths = _extract_paths(text)
    if not paths:
        return None

    matched_labels: set[str] = set()
    blocks: list[str] = []

    for rule_set in _rule_sets:
        if rule_set.label in matched_labels:
            continue
        for p in paths:
            if _matches(p, rule_set.pattern):
                matched_labels.add(rule_set.label)
                blocks.append(rule_set.rules)
                break

    if not blocks:
        return None

    header = "## Path-Scoped Rules (auto-injected)\n"
    header += "The following rules apply because your task references files in these areas:\n"
    return header + "\n\n".join(blocks)
