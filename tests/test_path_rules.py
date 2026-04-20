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
        result = match_rules("Make a fun game")
        assert result is None

    def test_returns_rules_for_artifact_dist(self):
        result = match_rules("Build artifacts/my-game/dist/v1/index.html")
        assert result is not None
        assert "Web Game Build" in result
        assert "window.__game" in result

    def test_returns_rules_for_prototype(self):
        result = match_rules("Create prototypes/dodge/index.html")
        assert result is not None
        assert "Prototype" in result
        assert "PROCEED/PIVOT/KILL" in result

    def test_returns_rules_for_runtime(self):
        result = match_rules("Edit src/runtime/agent_runtime.py")
        assert result is not None
        assert "Runtime Code" in result

    def test_dedupes_by_label(self):
        text = (
            "Edit src/runtime/agent_runtime.py and "
            "src/runtime/tool_executor.py and "
            "src/runtime/path_rules.py"
        )
        result = match_rules(text)
        assert result is not None
        assert result.count("Runtime Code Standards") == 1

    def test_multiple_rule_sets(self):
        text = "Copy src/runtime/agent_runtime.py to tests/test_runtime.py"
        result = match_rules(text)
        assert result is not None
        assert "Runtime Code" in result
        assert "Test Standards" in result
