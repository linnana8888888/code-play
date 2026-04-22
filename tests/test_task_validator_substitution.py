"""Tests for task_validator.substitute_expected_outputs.

Pipelines declare expected_outputs with template placeholders
({{iteration_tag}}, {{cycle_n}}, {{cycle_n_plus_1}}) so the same step config
works for every cycle. This helper renders them before the contract lands on
TaskInput — if it drops a placeholder, validate_outputs will look for a key
like "telemetry_{{iteration_tag}}" that no agent ever writes, and every task
will block forever.
"""
from __future__ import annotations

from src.runtime.task_validator import substitute_expected_outputs


def test_none_passes_through():
    assert substitute_expected_outputs(None) is None


def test_empty_list_passes_through():
    assert substitute_expected_outputs([]) == []


def test_substitutes_iteration_tag_in_key():
    eo = [{"kind": "memory_key", "type": "artifact", "key": "telemetry_{{iteration_tag}}", "min_bytes": 100}]
    rendered = substitute_expected_outputs(eo, iteration_tag="v7", cycle_n=7)
    assert rendered[0]["key"] == "telemetry_v7"
    assert rendered[0]["min_bytes"] == 100  # non-string preserved


def test_substitutes_cycle_n_and_cycle_n_plus_1():
    eo = [
        {"kind": "memory_key", "key": "player_feedback_v{{cycle_n}}"},
        {"kind": "memory_key", "key": "game_html_v{{cycle_n_plus_1}}"},
    ]
    rendered = substitute_expected_outputs(eo, cycle_n=3)
    assert rendered[0]["key"] == "player_feedback_v3"
    assert rendered[1]["key"] == "game_html_v4"


def test_does_not_mutate_input():
    original = [{"kind": "memory_key", "key": "telemetry_{{iteration_tag}}"}]
    substitute_expected_outputs(original, iteration_tag="v2", cycle_n=2)
    # Original untouched — pipeline YAML cache must stay templated.
    assert original[0]["key"] == "telemetry_{{iteration_tag}}"


def test_keeps_non_string_fields():
    eo = [{"kind": "file_path", "path": "artifact_v{{cycle_n}}.html", "min_bytes": 2048}]
    rendered = substitute_expected_outputs(eo, cycle_n=5)
    assert rendered[0]["path"] == "artifact_v5.html"
    assert rendered[0]["min_bytes"] == 2048
    assert isinstance(rendered[0]["min_bytes"], int)


def test_no_substitutions_when_no_vars_provided():
    """Rendering without any substitution vars returns the entries unchanged
    (still a fresh list, so callers can't corrupt the source)."""
    eo = [{"kind": "branch_commit", "branch": "iteration/v{{cycle_n_plus_1}}"}]
    rendered = substitute_expected_outputs(eo)
    assert rendered == eo
    assert rendered is not eo


def test_all_three_placeholders_in_one_string():
    eo = [{"kind": "memory_key", "key": "a_{{iteration_tag}}_b_{{cycle_n}}_c_{{cycle_n_plus_1}}"}]
    rendered = substitute_expected_outputs(eo, iteration_tag="v2", cycle_n=2)
    assert rendered[0]["key"] == "a_v2_b_2_c_3"


def test_substitutes_review_round_n_and_plus_1():
    eo = [
        {"kind": "memory_key", "key": "code_review_v{{cycle_n}}_r{{review_round_n}}"},
        {"kind": "memory_key", "key": "code_review_v{{cycle_n}}_r{{review_round_n_plus_1}}"},
    ]
    rendered = substitute_expected_outputs(eo, cycle_n=2, review_round_n=1)
    assert rendered[0]["key"] == "code_review_v2_r1"
    assert rendered[1]["key"] == "code_review_v2_r2"


def test_review_round_n_zero_substitutes_literal_zero():
    eo = [{"kind": "memory_key", "key": "pre_review_r{{review_round_n}}"}]
    rendered = substitute_expected_outputs(eo, review_round_n=0)
    assert rendered[0]["key"] == "pre_review_r0"


def test_matches_pipelines_yaml_playtest_shape():
    """Lock the shape used by iterate_artifact.playtest — every iterate step
    uses memory_key + {{iteration_tag}} or {{cycle_n}} in the key."""
    eo = [{
        "kind": "memory_key",
        "type": "artifact",
        "key": "telemetry_{{iteration_tag}}",
        "min_bytes": 100,
    }]
    rendered = substitute_expected_outputs(eo, iteration_tag="v3", cycle_n=3)
    assert rendered == [{
        "kind": "memory_key",
        "type": "artifact",
        "key": "telemetry_v3",
        "min_bytes": 100,
    }]
