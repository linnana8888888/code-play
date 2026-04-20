"""Unit tests for path-scoped rules matching."""
from __future__ import annotations

import pytest
from src.runtime.path_rules import _extract_paths, _matches, match_rules


class TestExtractPaths:
    def test_finds_artifact_paths(self):
        text = "Build the game at artifacts/my-game/dist/v1/index.html"
        paths = _extract_paths(text)
        assert "artifacts/my-game/dist/v1/index.html" in paths

    def test_finds_src_paths(self):
        text = "Edit src/runtime/agent_runtime.py to add the feature"
        paths = _extract_paths(text)
        assert "src/runtime/agent_runtime.py" in paths

    def test_finds_prototype_paths(self):
        text = 'Create files in prototypes/dodge-test/index.html'
        paths = _extract_paths(text)
        assert "prototypes/dodge-test/index.html" in paths

    def test_finds_config_paths(self):
        text = "Update config/agents.yaml with the new model"
        paths = _extract_paths(text)
        assert "config/agents.yaml" in paths

    def test_finds_agent_paths(self):
        text = "Read agents/engineering/frontend-developer.md"
        paths = _extract_paths(text)
        assert "agents/engineering/frontend-developer.md" in paths

    def test_ignores_random_text(self):
        text = "Make a fun game with cool mechanics and nice art"
        paths = _extract_paths(text)
        assert len(paths) == 0

    def test_multiple_paths(self):
        text = "Copy src/runtime/tool_executor.py to tests/test_tool.py"
        paths = _extract_paths(text)
        assert "src/runtime/tool_executor.py" in paths
        assert "tests/test_tool.py" in paths


class TestMatches:
    def test_doublestar_prefix(self):
        assert _matches("artifacts/my-game/dist/v1/index.html", "artifacts/*/dist/**")

    def test_doublestar_no_match(self):
        assert not _matches("src/runtime/agent_runtime.py", "artifacts/*/dist/**")

    def test_simple_glob(self):
        assert _matches("config/agents.yaml", "config/**")

    def test_agent_md(self):
        assert _matches("agents/engineering/frontend-developer.md", "agents/**/*.md")

    def test_prototype(self):
        assert _matches("prototypes/dodge-test/index.html", "prototypes/**")


class TestMatchRules:
    def test_returns_none_for_no_paths(self):
        rules, labels = match_rules("Make a fun game")
        assert rules is None
        assert len(labels) == 0

    def test_returns_rules_for_artifact_dist(self):
        rules, labels = match_rules("Build artifacts/my-game/dist/v1/index.html")
        assert rules is not None
        assert "Web Game Build" in rules
        assert "window.__game" in rules
        assert "Web Game Build" in labels

    def test_returns_rules_for_prototype(self):
        rules, labels = match_rules("Create prototypes/dodge/index.html")
        assert rules is not None
        assert "Prototype" in rules
        assert "PROCEED/PIVOT/KILL" in rules

    def test_returns_rules_for_runtime(self):
        rules, labels = match_rules("Edit src/runtime/agent_runtime.py")
        assert rules is not None
        assert "Runtime Code" in rules

    def test_dedupes_by_label(self):
        text = (
            "Edit src/runtime/agent_runtime.py and "
            "src/runtime/tool_executor.py and "
            "src/runtime/path_rules.py"
        )
        rules, labels = match_rules(text)
        assert rules is not None
        assert rules.count("Runtime Code Standards") == 1

    def test_multiple_rule_sets(self):
        text = "Copy src/runtime/agent_runtime.py to tests/test_runtime.py"
        rules, labels = match_rules(text)
        assert rules is not None
        assert "Runtime Code" in rules
        assert "Test Standards" in rules

    def test_exclude_labels_skips_already_injected(self):
        text = "Edit src/runtime/agent_runtime.py"
        rules_first, labels_first = match_rules(text)
        assert rules_first is not None
        assert "Runtime Code" in labels_first

        rules_second, labels_second = match_rules(text, exclude_labels=labels_first)
        assert rules_second is None
        assert len(labels_second) == 0

    def test_exclude_labels_returns_only_new(self):
        already = {"Runtime Code"}
        rules, labels = match_rules(
            "Edit src/runtime/agent_runtime.py and tests/test_path_rules.py",
            exclude_labels=already,
        )
        assert rules is not None
        assert "Test Standards" in rules
        assert "Runtime Code" not in labels
        assert "Test Code" in labels
