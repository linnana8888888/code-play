"""Unit tests for src/runtime/project_state.py.

project_state.yaml is the cross-agent substrate: Claude, GPT, and local-Qwen
producers all read/write it to track phase progress. These tests lock:
  - atomic write (no half-written YAML visible to concurrent readers)
  - initial_state shape
  - transition() updates + history appending rules
  - resolve_state_path() preference for existing parent dirs
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime.project_state import (
    PHASE_STATUSES,
    initial_state,
    read_state,
    resolve_state_path,
    transition,
    write_state,
)


def test_initial_state_shape():
    s = initial_state("my-slug", "phased-producer", first_phase="concept")
    assert s["slug"] == "my-slug"
    assert s["pipeline"] == "phased-producer"
    assert s["current_phase"] == "concept"
    assert s["phase_status"] == "pending"
    assert s["gates_passed"] == []
    assert s["artifacts_complete"] == {}
    assert s["history"] == []
    assert s["last_transition_at"].endswith("Z")


def test_read_state_missing_returns_none(tmp_path: Path):
    assert read_state(tmp_path / "does-not-exist.yaml") is None


def test_read_state_non_mapping_returns_none(tmp_path: Path):
    # A YAML list is syntactically valid but not a state mapping.
    p = tmp_path / "project_state.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    assert read_state(p) is None


def test_write_then_read_roundtrip(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    s = initial_state("s1", "phased-producer")
    write_state(p, s)
    got = read_state(p)
    assert got == s


def test_write_is_atomic_no_partial_file(tmp_path: Path):
    # After write_state returns, no .tmp should remain in the dir.
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("atomic-slug", "phased-producer"))
    leftover = [x for x in tmp_path.iterdir() if x.name.endswith(".yaml.tmp")]
    assert leftover == []


def test_transition_creates_file_when_missing(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    state = transition(p, new_phase="concept", phase_status="running", agent="game-designer")
    assert p.exists()
    assert state["current_phase"] == "concept"
    assert state["phase_status"] == "running"
    assert state["current_agent"] == "game-designer"


def test_transition_rejects_invalid_phase_status(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("s", "phased-producer"))
    with pytest.raises(ValueError):
        transition(p, phase_status="not-a-real-status")


def test_transition_appends_history_on_observable_change(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("s", "phased-producer"))
    transition(p, phase_status="running", agent="game-designer")
    transition(p, phase_status="complete", outcome="pass")
    state = read_state(p)
    assert len(state["history"]) == 2
    assert state["history"][-1]["outcome"] == "pass"


def test_transition_no_history_on_pure_artifact_update(tmp_path: Path):
    """Adding artifacts is a bookkeeping write — shouldn't bloat history."""
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("s", "phased-producer"))
    transition(p, artifacts_added={"concept_options_v1": {"bytes": 2341}})
    state = read_state(p)
    assert "concept_options_v1" in state["artifacts_complete"]
    assert state["artifacts_complete"]["concept_options_v1"]["bytes"] == 2341
    assert state["history"] == []


def test_transition_gate_passed_moves_from_pending_to_passed(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    s = initial_state("s", "phased-producer")
    s["gates_pending"] = ["gate-concept", "gate-mechanics"]
    write_state(p, s)

    transition(p, gate_passed="gate-concept")
    state = read_state(p)
    assert "gate-concept" in state["gates_passed"]
    assert "gate-concept" not in state["gates_pending"]
    assert "gate-mechanics" in state["gates_pending"]


def test_transition_gate_passed_is_idempotent(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("s", "phased-producer"))
    transition(p, gate_passed="gate-concept")
    transition(p, gate_passed="gate-concept")
    state = read_state(p)
    assert state["gates_passed"].count("gate-concept") == 1


def test_transition_validation_failures_stored(tmp_path: Path):
    p = tmp_path / "project_state.yaml"
    write_state(p, initial_state("s", "phased-producer"))
    transition(p, validation_failures=["memory[artifact/concept_options_v1] missing"])
    state = read_state(p)
    assert len(state["validation_failures"]) == 1
    assert "concept_options_v1" in state["validation_failures"][0]


def test_phase_statuses_set_is_complete():
    # Guard: if someone adds a status in the runtime, the enum here should grow too.
    assert PHASE_STATUSES == {"pending", "running", "awaiting_gate", "complete", "blocked"}


def test_resolve_state_path_prefers_existing_dir(tmp_path: Path):
    slug = "my-existing-slug"
    existing = tmp_path / slug
    existing.mkdir()
    got = resolve_state_path(slug, search_dirs=[tmp_path])
    assert got == existing / "project_state.yaml"


def test_resolve_state_path_falls_back_to_projects_dir(tmp_path: Path):
    # Search dirs don't contain the slug — should fall back to projects_dir default.
    got = resolve_state_path("slug-that-does-not-exist-anywhere", search_dirs=[tmp_path])
    assert got.name == "project_state.yaml"
