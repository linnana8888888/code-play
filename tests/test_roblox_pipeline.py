"""Phase 4.3 tests: Roblox pipeline parity.

Covers:
  - roblox-producer pipeline exists in pipelines.yaml
  - Pipeline has required steps: roblox-concept, roblox-mechanics, roblox-build,
    roblox-qa, roblox-publish
  - Pipeline has exactly 3 human gates
  - kid-safety-roblox step exists and depends on roblox-build
  - gate-roblox-qa depends on both roblox-qa and kid-safety-roblox
  - roblox_script_v1 schema exists in artifact_schemas.yaml
  - All agents referenced in roblox-producer exist in agents.yaml
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINES_PATH = REPO_ROOT / "config" / "pipelines.yaml"
SCHEMAS_PATH = REPO_ROOT / "config" / "artifact_schemas.yaml"
AGENTS_PATH = REPO_ROOT / "config" / "agents.yaml"


@pytest.fixture(scope="module")
def pipelines() -> dict:
    return yaml.safe_load(PIPELINES_PATH.read_text())


@pytest.fixture(scope="module")
def roblox_pipeline(pipelines) -> dict:
    return pipelines["pipelines"]["roblox-producer"]


@pytest.fixture(scope="module")
def roblox_steps(roblox_pipeline) -> dict[str, dict]:
    """Return steps keyed by id for easy lookup."""
    return {step["id"]: step for step in roblox_pipeline["steps"]}


@pytest.fixture(scope="module")
def artifact_schemas() -> dict:
    return yaml.safe_load(SCHEMAS_PATH.read_text())


@pytest.fixture(scope="module")
def agents() -> dict:
    return yaml.safe_load(AGENTS_PATH.read_text())


# ── Pipeline existence ────────────────────────────────────────────────────────


class TestRobloxPipelineExists:
    def test_roblox_producer_pipeline_exists(self, pipelines):
        assert "roblox-producer" in pipelines["pipelines"], (
            "roblox-producer pipeline missing from pipelines.yaml"
        )

    def test_pipeline_has_name(self, roblox_pipeline):
        assert roblox_pipeline.get("name"), "roblox-producer pipeline missing 'name'"

    def test_pipeline_has_description(self, roblox_pipeline):
        assert roblox_pipeline.get("description"), "roblox-producer pipeline missing 'description'"

    def test_pipeline_has_steps(self, roblox_pipeline):
        assert roblox_pipeline.get("steps"), "roblox-producer pipeline has no steps"


# ── Required steps ────────────────────────────────────────────────────────────


class TestRobloxPipelineRequiredSteps:
    REQUIRED_STEPS = [
        "roblox-concept",
        "roblox-mechanics",
        "roblox-build",
        "roblox-qa",
        "roblox-publish",
    ]

    @pytest.mark.parametrize("step_id", REQUIRED_STEPS)
    def test_required_step_exists(self, roblox_steps, step_id):
        assert step_id in roblox_steps, (
            f"Required step '{step_id}' missing from roblox-producer pipeline"
        )


# ── Human gates ───────────────────────────────────────────────────────────────


class TestRobloxPipelineHumanGates:
    def test_pipeline_has_exactly_3_human_gates(self, roblox_steps):
        gates = [s for s in roblox_steps.values() if s.get("type") == "human-gate"]
        assert len(gates) == 3, (
            f"Expected 3 human gates, found {len(gates)}: {[g['id'] for g in gates]}"
        )

    def test_gate_roblox_concept_exists(self, roblox_steps):
        assert "gate-roblox-concept" in roblox_steps

    def test_gate_roblox_mechanics_exists(self, roblox_steps):
        assert "gate-roblox-mechanics" in roblox_steps

    def test_gate_roblox_qa_exists(self, roblox_steps):
        assert "gate-roblox-qa" in roblox_steps


# ── Kid safety step ───────────────────────────────────────────────────────────


class TestKidSafetyRoblox:
    def test_kid_safety_roblox_step_exists(self, roblox_steps):
        assert "kid-safety-roblox" in roblox_steps, (
            "kid-safety-roblox step missing from roblox-producer pipeline"
        )

    def test_kid_safety_roblox_depends_on_roblox_build(self, roblox_steps):
        step = roblox_steps["kid-safety-roblox"]
        depends = step.get("depends_on", [])
        assert "roblox-build" in depends, (
            f"kid-safety-roblox should depend on roblox-build, got: {depends}"
        )


# ── gate-roblox-qa dependencies ───────────────────────────────────────────────


class TestGateRobloxQaDependencies:
    def test_gate_roblox_qa_depends_on_roblox_qa(self, roblox_steps):
        step = roblox_steps["gate-roblox-qa"]
        depends = step.get("depends_on", [])
        assert "roblox-qa" in depends, (
            f"gate-roblox-qa should depend on roblox-qa, got: {depends}"
        )

    def test_gate_roblox_qa_depends_on_kid_safety_roblox(self, roblox_steps):
        step = roblox_steps["gate-roblox-qa"]
        depends = step.get("depends_on", [])
        assert "kid-safety-roblox" in depends, (
            f"gate-roblox-qa should depend on kid-safety-roblox, got: {depends}"
        )


# ── Artifact schema ───────────────────────────────────────────────────────────


class TestRobloxScriptSchema:
    def test_roblox_script_v1_schema_exists(self, artifact_schemas):
        schemas = artifact_schemas.get("schemas", {})
        assert "roblox_script_v1" in schemas, (
            "roblox_script_v1 schema missing from artifact_schemas.yaml"
        )

    def test_roblox_script_v1_has_required_fields(self, artifact_schemas):
        schema = artifact_schemas["schemas"]["roblox_script_v1"]
        required = schema.get("required_fields", [])
        assert "script_content" in required, "roblox_script_v1 missing required_field: script_content"
        assert "entry_point" in required, "roblox_script_v1 missing required_field: entry_point"

    def test_roblox_script_v1_field_rules(self, artifact_schemas):
        schema = artifact_schemas["schemas"]["roblox_script_v1"]
        rules = schema.get("field_rules", {})
        assert "script_content" in rules, "roblox_script_v1 missing field_rule for script_content"
        assert "entry_point" in rules, "roblox_script_v1 missing field_rule for entry_point"
        assert rules["script_content"].get("type") == "string"
        assert rules["entry_point"].get("type") == "string"


# ── Agent existence ───────────────────────────────────────────────────────────


class TestRobloxPipelineAgentsExist:
    def _collect_agent_refs(self, roblox_pipeline: dict) -> set[str]:
        """Collect all agent references from pipeline steps."""
        refs = set()
        for step in roblox_pipeline.get("steps", []):
            agent = step.get("agent")
            if agent:
                refs.add(agent)
        return refs

    def test_all_referenced_agents_exist(self, roblox_pipeline, agents):
        agent_defs = agents.get("agents", {})
        refs = self._collect_agent_refs(roblox_pipeline)
        missing = [a for a in refs if a not in agent_defs]
        assert not missing, (
            f"Agents referenced in roblox-producer but missing from agents.yaml: {missing}"
        )

    @pytest.mark.parametrize("agent_id", [
        "roblox-experience-designer",
        "roblox-systems-scripter",
        "game-designer",
        "handoff-summarizer",
        "qa-engineer",
        "kid-safety-reviewer",
    ])
    def test_specific_agent_exists(self, agents, agent_id):
        agent_defs = agents.get("agents", {})
        assert agent_id in agent_defs, (
            f"Agent '{agent_id}' missing from agents.yaml"
        )

    @pytest.mark.parametrize("agent_id", [
        "roblox-systems-scripter",
        "roblox-experience-designer",
    ])
    def test_roblox_agents_not_using_omlx(self, agents, agent_id):
        """Roblox agents should not use omlx (no tool-use capability)."""
        agent_def = agents.get("agents", {}).get(agent_id, {})
        model = agent_def.get("model", "")
        assert not model.startswith("omlx/"), (
            f"Agent '{agent_id}' uses omlx model '{model}' which lacks tool-use capability"
        )
