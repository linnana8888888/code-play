"""On-disk project state — model-agnostic phase tracking.

Each project gets a `project_state.yaml` next to its artifacts. The file is
plain YAML so non-Claude-Code agents (GPT, local Qwen, etc.) can read and
update it without going through the runtime's memory API.

Producer writes this file on every phase transition. The runtime reads it to
answer "what phase is <slug> in?" without round-tripping through the DB.

Schema
------
    slug: butt-shooting-game
    pipeline: phased-producer
    current_phase: publish
    current_agent: publisher
    phase_status: complete        # pending | running | awaiting_gate | complete | blocked
    last_transition_at: 2026-04-19T17:45:00Z
    next_expected_agent: null
    gates_passed: [gate-concept, ...]
    gates_pending: []
    artifacts_complete:
      concept_options_v1: {at: 2026-04-19T10:00:00Z, bytes: 2341}
    artifacts_pending: []
    validation_failures: []
    blockers: []
    history:
      - {phase: concept, at: ..., agent: game-designer, outcome: pass}
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)

PHASE_STATUSES = {"pending", "running", "awaiting_gate", "complete", "blocked"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def initial_state(slug: str, pipeline: str, first_phase: str = "concept") -> dict[str, Any]:
    """Return a fresh state dict for a new project."""
    return {
        "slug": slug,
        "pipeline": pipeline,
        "current_phase": first_phase,
        "current_agent": None,
        "phase_status": "pending",
        "last_transition_at": _now(),
        "next_expected_agent": None,
        "gates_passed": [],
        "gates_pending": [],
        "artifacts_complete": {},
        "artifacts_pending": [],
        "validation_failures": [],
        "blockers": [],
        "history": [],
    }


def read_state(state_path: Path) -> dict[str, Any] | None:
    """Load state from disk. Returns None if file missing."""
    if not state_path.exists():
        return None
    try:
        with state_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            _log.warning("project_state %s is not a mapping — ignoring", state_path)
            return None
        return data
    except (OSError, yaml.YAMLError) as exc:
        _log.warning("read_state(%s) failed: %s", state_path, exc)
        return None


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    """Atomic write (tmp file + rename) so concurrent readers never see half-written YAML."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".project_state.", suffix=".yaml.tmp", dir=str(state_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(state, fh, sort_keys=False, default_flow_style=False)
        os.replace(tmp_path, state_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def transition(
    state_path: Path,
    *,
    new_phase: str | None = None,
    phase_status: str | None = None,
    agent: str | None = None,
    outcome: str | None = None,
    artifacts_added: dict[str, dict[str, Any]] | None = None,
    gate_passed: str | None = None,
    validation_failures: list[str] | None = None,
    blockers: list[str] | None = None,
    next_expected_agent: str | None = None,
) -> dict[str, Any]:
    """Update state and append a history entry. Returns the new state.

    Creates the file with a minimal shell if it doesn't exist yet — lets
    producer call transition() against a fresh project without a separate
    bootstrap call.
    """
    state = read_state(state_path)
    if state is None:
        # Best-effort: if producer transitions without an init, spawn a shell.
        # slug is derived from the parent dir name; pipeline unknown until set.
        slug = state_path.parent.name
        state = initial_state(slug, pipeline="unknown", first_phase=new_phase or "concept")

    if phase_status is not None and phase_status not in PHASE_STATUSES:
        raise ValueError(f"invalid phase_status: {phase_status!r} (must be one of {PHASE_STATUSES})")

    now = _now()
    prev_phase = state.get("current_phase")

    if new_phase is not None:
        state["current_phase"] = new_phase
    if phase_status is not None:
        state["phase_status"] = phase_status
    if agent is not None:
        state["current_agent"] = agent
    if next_expected_agent is not None:
        state["next_expected_agent"] = next_expected_agent
    if artifacts_added:
        complete = dict(state.get("artifacts_complete") or {})
        for key, meta in artifacts_added.items():
            complete[key] = {**meta, "at": meta.get("at", now)}
        state["artifacts_complete"] = complete
    if gate_passed:
        passed = list(state.get("gates_passed") or [])
        if gate_passed not in passed:
            passed.append(gate_passed)
        state["gates_passed"] = passed
        pending = [g for g in (state.get("gates_pending") or []) if g != gate_passed]
        state["gates_pending"] = pending
    if validation_failures is not None:
        state["validation_failures"] = list(validation_failures)
    if blockers is not None:
        state["blockers"] = list(blockers)

    state["last_transition_at"] = now

    # Append history only when something observable changed (phase move,
    # status change, gate pass, or validation failure). Prevents history
    # from bloating on no-op writes.
    observable = any([
        new_phase is not None and new_phase != prev_phase,
        phase_status is not None,
        gate_passed,
        validation_failures,
    ])
    if observable:
        history = list(state.get("history") or [])
        history.append({
            "phase": state.get("current_phase"),
            "at": now,
            "agent": state.get("current_agent"),
            "outcome": outcome or state.get("phase_status"),
        })
        state["history"] = history

    write_state(state_path, state)
    return state


def resolve_state_path(slug_or_project_id: str, search_dirs: list[Path] | None = None) -> Path:
    """Return the expected project_state.yaml path.

    Prefers a path under one of the given search dirs where a directory named
    `slug_or_project_id` already exists (artifact repo or projects/<pid>).
    Falls back to `projects/<slug_or_project_id>/project_state.yaml`.
    """
    from src.settings import settings  # lazy import — avoids cycles in tests

    extra_parents = [base / slug_or_project_id for base in (search_dirs or [])]
    candidates = extra_parents + [
        Path(settings.projects_dir) / slug_or_project_id,
        Path("artifacts") / slug_or_project_id,
    ]
    for parent in candidates:
        if parent.exists() and parent.is_dir():
            return parent / "project_state.yaml"
    # Default: projects/<id>/project_state.yaml even if parent doesn't exist yet.
    return Path(settings.projects_dir) / slug_or_project_id / "project_state.yaml"
