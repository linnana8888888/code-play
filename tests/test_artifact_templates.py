"""Tests for artifact template loading and injection."""
import pytest
from src.runtime.artifact_templates import (
    _extract_artifact_keys,
    _read_template,
    get_template_for_task,
)


class TestExtractArtifactKeys:
    def test_standard_pattern(self):
        keys = _extract_artifact_keys("Save to memory as artifact key 'mechanics_v1'.")
        assert keys == ["mechanics_v1"]

    def test_double_quotes(self):
        keys = _extract_artifact_keys('Save to memory as artifact key "concept_options_v1".')
        assert keys == ["concept_options_v1"]

    def test_save_as_artifact(self):
        keys = _extract_artifact_keys("save as artifact 'style_research_v1'")
        assert keys == ["style_research_v1"]

    def test_save_to_memory_as(self):
        keys = _extract_artifact_keys("Save to memory as 'qa_report_v1'")
        assert keys == ["qa_report_v1"]

    def test_no_match(self):
        keys = _extract_artifact_keys("Just build the game, no artifacts mentioned")
        assert keys == []

    def test_multiple_keys(self):
        text = (
            "Save to memory as artifact key 'mechanics_v1'. "
            "Also save as artifact 'concept_options_v1'."
        )
        keys = _extract_artifact_keys(text)
        assert "mechanics_v1" in keys
        assert "concept_options_v1" in keys

    def test_artifact_key_with_version_suffix(self):
        keys = _extract_artifact_keys("Save to memory as artifact key 'telemetry_spec_v1'.")
        assert keys == ["telemetry_spec_v1"]


class TestGetTemplateForTask:
    def test_mechanics_template(self):
        result = get_template_for_task("Save to memory as artifact key 'mechanics_v1'.")
        assert result is not None
        assert "PROJECT_TITLE" in result

    def test_tech_plan_template(self):
        result = get_template_for_task("Save to memory as artifact key 'tech_plan_v1'.")
        assert result is not None
        assert "Engine" in result

    def test_style_research_template(self):
        result = get_template_for_task("Save to memory as artifact key 'style_research_v1'.")
        assert result is not None
        assert "Palette" in result

    def test_code_review_template(self):
        result = get_template_for_task("Save to memory as artifact key 'code_review_v1'.")
        assert result is not None
        assert "Verdict" in result

    def test_juice_pass_template(self):
        result = get_template_for_task("save to memory as 'juice_pass_v1'")
        assert result is not None
        assert "Deltas" in result

    def test_implementation_brief_template(self):
        result = get_template_for_task("Save as artifact 'implementation_brief_v1'")
        assert result is not None
        assert "Acceptance Criteria" in result

    def test_no_artifact_returns_none(self):
        result = get_template_for_task("Build the game from the plan")
        assert result is None

    def test_unknown_artifact_returns_none(self):
        result = get_template_for_task("Save to memory as artifact key 'unknown_thing_v1'.")
        assert result is None

    def test_all_mapped_templates_exist(self):
        """Every entry in artifact_templates.yaml should resolve to a real file."""
        from src.runtime.artifact_templates import _load_config, _artifact_map
        _load_config()
        for key, path in _artifact_map.items():
            content = _read_template(path)
            assert content is not None, f"Template for '{key}' at '{path}' not found"
            assert len(content) > 50, f"Template for '{key}' suspiciously short"
