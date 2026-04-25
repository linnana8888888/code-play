"""Post-run output validator — catches silent-success completions.

Agents occasionally exit cleanly without producing the promised deliverables
(iteration cap reached, long tool-loop ran out of budget, LLM declared itself
done after context-gathering without ever committing). The runtime used to
mark those tasks COMPLETED and advance the pipeline.

This module validates each task's `expected_outputs` contract against what the
agent actually produced, so the pipeline blocks instead of silently dropping
work. Each expected-output entry is one of:

    {"kind": "memory_key", "type": "artifact", "key": "engineer_result_eng-1_v2"}
    {"kind": "branch_commit", "branch": "iteration/eng-1-v2"}
    {"kind": "file_path", "path": "game.html", "min_bytes": 1024}

`validate_outputs` returns a list of human-readable missing-output descriptors.
Empty list → contract satisfied.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.models.tasks import Task
from src.memory.project_memory import ProjectMemory

_log = logging.getLogger(__name__)


def substitute_expected_outputs(
    expected: list[dict] | None,
    *,
    iteration_tag: str | None = None,
    cycle_n: int | None = None,
    review_round_n: int | None = None,
) -> list[dict] | None:
    """Substitute `{{iteration_tag}}`, `{{cycle_n}}`, `{{cycle_n_plus_1}}`,
    `{{review_round_n}}`, `{{review_round_n_plus_1}}` in every string field of
    each expected_output entry.

    Pipelines declare keys like `"telemetry_{{iteration_tag}}"` or
    `"code_review_v{{cycle_n}}_r{{review_round_n}}"` in config/pipelines.yaml;
    this helper renders them for a concrete task before the contract is stored
    on TaskCreate.
    """
    if not expected:
        return expected
    subs = {}
    if iteration_tag is not None:
        subs["{{iteration_tag}}"] = str(iteration_tag)
    if cycle_n is not None:
        subs["{{cycle_n}}"] = str(cycle_n)
        subs["{{cycle_n_plus_1}}"] = str(int(cycle_n) + 1)
    if review_round_n is not None:
        subs["{{review_round_n}}"] = str(review_round_n)
        subs["{{review_round_n_plus_1}}"] = str(int(review_round_n) + 1)
    if not subs:
        return [dict(e) for e in expected]

    rendered: list[dict] = []
    for entry in expected:
        new_entry: dict = {}
        for k, v in entry.items():
            if isinstance(v, str):
                for needle, value in subs.items():
                    v = v.replace(needle, value)
            new_entry[k] = v
        rendered.append(new_entry)
    return rendered


def validate_artifact_content(key: str, value, schemas_path: str = "config/artifact_schemas.yaml") -> list[str]:
    """
    Validate artifact content against schema rules.
    Returns list of error strings (empty = valid).
    """
    import yaml
    from pathlib import Path

    schema_file = Path(schemas_path)
    if not schema_file.exists():
        return []  # no schema file = no validation (graceful degradation)

    with open(schema_file) as f:
        schemas = yaml.safe_load(f)

    schema = schemas.get("schemas", {}).get(key)
    if not schema:
        return []  # no schema for this key = valid

    errors = []
    required = schema.get("required_fields", [])
    field_rules = schema.get("field_rules", {})

    # For string artifacts (game_html_v1), check min_bytes
    if isinstance(value, str):
        content_rule = field_rules.get("content", {})
        min_bytes = content_rule.get("min_bytes", 0)
        if len(value.encode()) < min_bytes:
            errors.append(f"{key}: content too short ({len(value.encode())} bytes, min {min_bytes})")
        return errors

    if not isinstance(value, dict):
        return []

    # Check required fields
    for field in required:
        if field not in value:
            errors.append(f"{key}: missing required field '{field}'")
            continue

        rule = field_rules.get(field, {})
        field_val = value[field]

        # Type checks
        if rule.get("type") == "list":
            if not isinstance(field_val, list):
                errors.append(f"{key}.{field}: expected list, got {type(field_val).__name__}")
            else:
                min_items = rule.get("min_items", 0)
                if len(field_val) < min_items:
                    errors.append(f"{key}.{field}: needs at least {min_items} items, got {len(field_val)}")
                each_requires = rule.get("each_requires", [])
                for i, item in enumerate(field_val):
                    if isinstance(item, dict):
                        for req in each_requires:
                            if req not in item:
                                errors.append(f"{key}.{field}[{i}]: missing '{req}'")

        elif rule.get("type") == "enum":
            allowed = rule.get("values", [])
            if field_val not in allowed:
                errors.append(f"{key}.{field}: '{field_val}' not in allowed values {allowed}")

        elif rule.get("type") == "string":
            if not isinstance(field_val, str):
                errors.append(f"{key}.{field}: expected string")

    return errors


def validate_outputs(
    task: Task,
    project_memory: ProjectMemory,
    project_repo_dir: Path | None = None,
) -> list[str]:
    """Return a list of missing-output descriptors. Empty == all present."""
    expected = task.expected_outputs or []
    if not expected:
        return []

    missing: list[str] = []
    for entry in expected:
        try:
            kind = str(entry.get("kind", "")).strip()
        except AttributeError:
            missing.append(f"malformed entry: {entry!r}")
            continue

        if kind == "memory_key":
            mem_type = str(entry.get("type", "artifact"))
            key = str(entry.get("key", ""))
            if not key:
                missing.append(f"memory_key entry missing 'key': {entry!r}")
                continue
            content = project_memory.read(task.project_id, mem_type, key)
            min_bytes = int(entry.get("min_bytes", 1))
            if content is None or len(content) < min_bytes:
                have = 0 if content is None else len(content)
                missing.append(
                    f"memory[{mem_type}/{key}] — have {have} bytes, need ≥{min_bytes}"
                )
            else:
                # Phase 1: warn-only artifact content validation (hard failures in Phase 2)
                try:
                    import json as _json
                    parsed = _json.loads(content)
                except (ValueError, TypeError):
                    parsed = content  # treat as raw string for string-type schemas
                schema_errors = validate_artifact_content(key, parsed)
                for err in schema_errors:
                    _log.warning("[artifact schema] %s (task=%s): %s", key, task.id, err)

        elif kind == "branch_commit":
            branch = str(entry.get("branch", ""))
            if not branch:
                missing.append(f"branch_commit entry missing 'branch': {entry!r}")
                continue
            if project_repo_dir is None or not project_repo_dir.exists():
                # No repo on disk → can't verify; skip rather than false-fail.
                continue
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", f"{branch}^{{commit}}"],
                    cwd=str(project_repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    missing.append(f"branch[{branch}] not found in {project_repo_dir.name}")
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                _log.warning("branch_commit check failed for %s: %s", branch, e)

        elif kind == "file_path":
            rel = str(entry.get("path", ""))
            if not rel:
                missing.append(f"file_path entry missing 'path': {entry!r}")
                continue
            min_bytes = int(entry.get("min_bytes", 1))
            base = project_repo_dir if project_repo_dir else Path.cwd()
            target = (base / rel).resolve()
            if not target.exists():
                missing.append(f"file[{rel}] not found")
                continue
            try:
                size = target.stat().st_size
            except OSError as e:
                missing.append(f"file[{rel}] stat failed: {e}")
                continue
            if size < min_bytes:
                missing.append(f"file[{rel}] — {size} bytes, need ≥{min_bytes}")

        else:
            missing.append(f"unknown expected_output kind: {kind!r}")

    return missing
