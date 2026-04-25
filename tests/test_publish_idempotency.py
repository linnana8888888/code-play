"""Tests for publish idempotency check and rollback protocol (Phase 3, Item 3.5)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

# ---------------------------------------------------------------------------
# Path setup — allow importing from src/
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(manifest_raw=None, game_html=None):
    """Return a mock project_memory whose .read() returns the given values."""
    mem = MagicMock()

    def _read(project_id, mem_type, key):
        if key == "publish_manifest_v1":
            return manifest_raw
        if key == "game_html_v1":
            return game_html
        return None

    mem.read.side_effect = _read
    return mem


def _html_ref(html: str) -> str:
    return hashlib.sha256(html.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Import the function under test
# ---------------------------------------------------------------------------

# We import lazily inside each test so the module-level FastAPI startup
# (lifespan, DB init) doesn't run during collection.
def _get_check():
    from src.main import _check_publish_idempotency
    return _check_publish_idempotency


# ---------------------------------------------------------------------------
# _check_publish_idempotency tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotency_no_manifest():
    """Returns False when no manifest exists."""
    check = _get_check()
    mem = _make_memory(manifest_raw=None)
    result = await check("proj-1", mem)
    assert result is False


@pytest.mark.asyncio
async def test_idempotency_manifest_status_failed():
    """Returns False when manifest status is 'failed'."""
    check = _get_check()
    manifest = json.dumps({"status": "failed", "ref": "abc123", "published_at": "2026-01-01T00:00:00Z"})
    mem = _make_memory(manifest_raw=manifest)
    result = await check("proj-2", mem)
    assert result is False


@pytest.mark.asyncio
async def test_idempotency_published_ref_matches():
    """Returns True when manifest status is 'published' and ref matches current game_html."""
    check = _get_check()
    html = "<html>game v1</html>"
    ref = _html_ref(html)
    manifest = json.dumps({"status": "published", "ref": ref, "published_at": "2026-01-01T00:00:00Z"})
    mem = _make_memory(manifest_raw=manifest, game_html=html)
    result = await check("proj-3", mem)
    assert result is True


@pytest.mark.asyncio
async def test_idempotency_published_ref_differs():
    """Returns False when manifest status is 'published' but ref differs (new version)."""
    check = _get_check()
    old_html = "<html>game v1</html>"
    new_html = "<html>game v2 — totally different</html>"
    old_ref = _html_ref(old_html)
    manifest = json.dumps({"status": "published", "ref": old_ref, "published_at": "2026-01-01T00:00:00Z"})
    mem = _make_memory(manifest_raw=manifest, game_html=new_html)
    result = await check("proj-4", mem)
    assert result is False


@pytest.mark.asyncio
async def test_idempotency_bad_manifest_json():
    """Returns False when manifest JSON is malformed."""
    check = _get_check()
    mem = _make_memory(manifest_raw="not-valid-json{{")
    result = await check("proj-5", mem)
    assert result is False


@pytest.mark.asyncio
async def test_idempotency_manifest_status_rollback_attempted():
    """Returns False when manifest status is 'rollback_attempted'."""
    check = _get_check()
    html = "<html>game v1</html>"
    ref = _html_ref(html)
    manifest = json.dumps({"status": "rollback_attempted", "ref": ref, "published_at": "2026-01-01T00:00:00Z"})
    mem = _make_memory(manifest_raw=manifest, game_html=html)
    result = await check("proj-6", mem)
    assert result is False


# ---------------------------------------------------------------------------
# Publisher agent prompt content tests
# ---------------------------------------------------------------------------

PUBLISHER_MD = ROOT / "agents" / "production" / "publisher.md"


def test_publisher_prompt_has_idempotency_section():
    """Publisher agent prompt contains 'Idempotency Check' section."""
    content = PUBLISHER_MD.read_text()
    assert "Idempotency Check" in content, (
        "publisher.md must contain an 'Idempotency Check' section"
    )


def test_publisher_prompt_has_rollback_section():
    """Publisher agent prompt contains 'Rollback Protocol' section."""
    content = PUBLISHER_MD.read_text()
    assert "Rollback Protocol" in content, (
        "publisher.md must contain a 'Rollback Protocol' section"
    )


def test_publisher_idempotency_references_manifest():
    """Idempotency section references publish_manifest_v1."""
    content = PUBLISHER_MD.read_text()
    assert "publish_manifest_v1" in content


def test_publisher_rollback_references_prior_version():
    """Rollback section references prior_version."""
    content = PUBLISHER_MD.read_text()
    assert "prior_version" in content


# ---------------------------------------------------------------------------
# artifact_schemas.yaml — publish_manifest_v1 schema tests
# ---------------------------------------------------------------------------

SCHEMAS_YAML = ROOT / "config" / "artifact_schemas.yaml"


def _load_schemas():
    with open(SCHEMAS_YAML) as f:
        return yaml.safe_load(f)


def test_publish_manifest_schema_exists():
    """publish_manifest_v1 schema exists in artifact_schemas.yaml."""
    schemas = _load_schemas()
    assert "publish_manifest_v1" in schemas.get("schemas", {}), (
        "publish_manifest_v1 must be defined in artifact_schemas.yaml"
    )


def test_publish_manifest_schema_required_fields():
    """publish_manifest_v1 has required_fields: status, ref, published_at."""
    schemas = _load_schemas()
    schema = schemas["schemas"]["publish_manifest_v1"]
    required = schema.get("required_fields", [])
    for field in ("status", "ref", "published_at"):
        assert field in required, f"publish_manifest_v1 must require field '{field}'"


def test_publish_manifest_status_enum_values():
    """publish_manifest_v1 status field has correct enum values."""
    schemas = _load_schemas()
    schema = schemas["schemas"]["publish_manifest_v1"]
    status_rule = schema.get("field_rules", {}).get("status", {})
    assert status_rule.get("type") == "enum", "status field_rule must be type: enum"
    values = set(status_rule.get("values", []))
    expected = {"published", "failed", "rollback_attempted", "skipped"}
    assert values == expected, (
        f"status enum values must be {expected}, got {values}"
    )


def test_publish_manifest_ref_field_rule():
    """publish_manifest_v1 ref field_rule is type: string."""
    schemas = _load_schemas()
    schema = schemas["schemas"]["publish_manifest_v1"]
    ref_rule = schema.get("field_rules", {}).get("ref", {})
    assert ref_rule.get("type") == "string"


def test_publish_manifest_published_at_field_rule():
    """publish_manifest_v1 published_at field_rule is type: string."""
    schemas = _load_schemas()
    schema = schemas["schemas"]["publish_manifest_v1"]
    pa_rule = schema.get("field_rules", {}).get("published_at", {})
    assert pa_rule.get("type") == "string"
