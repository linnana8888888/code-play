"""
Phase 2 test suite for code-play.

Covers:
  1. Parallel research: style-research and cd-mechanics-check both feed look-and-feel
  2. Handoff-summarizer: all 6 gates have exactly one handoff-summarize-* step before them
  3. Model tiering: 12 agents verified against expected tier (opus / sonnet / haiku)
  4. Schema: handoff_brief_v1 exists with 4 required fields
"""

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipelines_yaml():
    with open("config/pipelines.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def phased_producer(pipelines_yaml):
    return pipelines_yaml["pipelines"]["phased-producer"]


@pytest.fixture(scope="module")
def steps(phased_producer):
    return {s["id"]: s for s in phased_producer["steps"]}


@pytest.fixture(scope="module")
def agents_yaml():
    with open("config/agents.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def agents(agents_yaml):
    """Return agent dict keyed by agent id."""
    return agents_yaml["agents"]


@pytest.fixture(scope="module")
def agent_defaults(agents_yaml):
    return agents_yaml.get("defaults", {})


@pytest.fixture(scope="module")
def schemas_yaml():
    with open("config/artifact_schemas.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 1. Parallel research
# ---------------------------------------------------------------------------

class TestParallelResearch:
    def test_look_and_feel_depends_on_style_research(self, steps):
        """look-and-feel must list style-research in depends_on."""
        laf = steps.get("look-and-feel")
        assert laf is not None, "look-and-feel step missing from pipeline"
        assert "style-research" in laf.get("depends_on", []), (
            f"look-and-feel.depends_on does not include style-research: {laf.get('depends_on')}"
        )

    def test_look_and_feel_depends_on_cd_mechanics_check(self, steps):
        """look-and-feel must list cd-mechanics-check in depends_on."""
        laf = steps.get("look-and-feel")
        assert laf is not None, "look-and-feel step missing from pipeline"
        assert "cd-mechanics-check" in laf.get("depends_on", []), (
            f"look-and-feel.depends_on does not include cd-mechanics-check: {laf.get('depends_on')}"
        )

    def test_style_research_and_cd_mechanics_check_share_upstream(self, steps):
        """style-research and cd-mechanics-check must share the same upstream dependency
        (i.e. they are parallel branches off the same parent — not sequential)."""
        sr = steps.get("style-research")
        cd = steps.get("cd-mechanics-check")
        assert sr is not None, "style-research step missing"
        assert cd is not None, "cd-mechanics-check step missing"

        sr_deps = set(sr.get("depends_on") or [])
        cd_deps = set(cd.get("depends_on") or [])

        # They must share at least one common upstream step
        shared = sr_deps & cd_deps
        assert shared, (
            f"style-research and cd-mechanics-check have no shared upstream dependency "
            f"(style-research deps: {sr_deps}, cd-mechanics-check deps: {cd_deps}). "
            "They should be parallel branches off the same parent."
        )

    def test_style_research_does_not_depend_on_cd_mechanics_check(self, steps):
        """style-research must NOT depend on cd-mechanics-check (they are parallel)."""
        sr = steps.get("style-research", {})
        assert "cd-mechanics-check" not in (sr.get("depends_on") or []), (
            "style-research depends on cd-mechanics-check — they are not parallel"
        )

    def test_cd_mechanics_check_does_not_depend_on_style_research(self, steps):
        """cd-mechanics-check must NOT depend on style-research (they are parallel)."""
        cd = steps.get("cd-mechanics-check", {})
        assert "style-research" not in (cd.get("depends_on") or []), (
            "cd-mechanics-check depends on style-research — they are not parallel"
        )


# ---------------------------------------------------------------------------
# 2. Handoff-summarizer gates
# ---------------------------------------------------------------------------

class TestHandoffSummarizer:
    EXPECTED_GATES = {
        "gate-concept",
        "gate-mechanics",
        "gate-laf",
        "gate-tech",
        "gate-qa",
        "gate-publish",
    }

    def test_all_six_gates_present(self, steps):
        """Pipeline must have exactly the 6 expected human gates."""
        gate_ids = {sid for sid in steps if sid.startswith("gate-")}
        assert gate_ids == self.EXPECTED_GATES, (
            f"Gate mismatch. Expected: {self.EXPECTED_GATES}, got: {gate_ids}"
        )

    @pytest.mark.parametrize("gate_id", [
        "gate-concept",
        "gate-mechanics",
        "gate-laf",
        "gate-tech",
        "gate-qa",
        "gate-publish",
    ])
    def test_gate_has_exactly_one_handoff_dep(self, steps, gate_id):
        """Each gate must have exactly one handoff-summarize-* step in its depends_on."""
        gate = steps.get(gate_id)
        assert gate is not None, f"{gate_id} not found in pipeline steps"
        deps = gate.get("depends_on") or []
        handoff_deps = [d for d in deps if "handoff" in d]
        assert len(handoff_deps) == 1, (
            f"{gate_id} must have exactly 1 handoff dep, got {handoff_deps}"
        )

    @pytest.mark.parametrize("gate_id", [
        "gate-concept",
        "gate-mechanics",
        "gate-laf",
        "gate-tech",
        "gate-qa",
        "gate-publish",
    ])
    def test_handoff_step_exists_for_gate(self, steps, gate_id):
        """The handoff-summarize-* step referenced by each gate must exist in the pipeline."""
        gate = steps.get(gate_id)
        assert gate is not None, f"{gate_id} not found"
        deps = gate.get("depends_on") or []
        handoff_deps = [d for d in deps if "handoff" in d]
        assert len(handoff_deps) == 1, f"{gate_id} has no handoff dep"
        handoff_id = handoff_deps[0]
        assert handoff_id in steps, (
            f"Handoff step '{handoff_id}' referenced by {gate_id} does not exist in pipeline"
        )

    def test_all_six_handoff_steps_exist(self, steps):
        """All 6 handoff-summarize-* steps must be present in the pipeline."""
        handoff_steps = [sid for sid in steps if sid.startswith("handoff-summarize-")]
        assert len(handoff_steps) == 6, (
            f"Expected 6 handoff-summarize-* steps, found {len(handoff_steps)}: {handoff_steps}"
        )


# ---------------------------------------------------------------------------
# 3. Model tiering
# ---------------------------------------------------------------------------

class TestModelTiering:
    def _get_model(self, agents, agent_defaults, agent_id):
        a = agents.get(agent_id)
        if a is None:
            return None
        return a.get("model") or agent_defaults.get("model") or ""

    @pytest.mark.parametrize("agent_id", [
        "creative-director",
        "technical-director",
    ])
    def test_opus_agents(self, agents, agent_defaults, agent_id):
        """creative-director and technical-director must use an opus model."""
        model = self._get_model(agents, agent_defaults, agent_id)
        assert model is not None, f"Agent {agent_id} not found in agents.yaml"
        assert "opus" in model.lower(), (
            f"{agent_id} should use opus, got: {model}"
        )

    @pytest.mark.parametrize("agent_id", [
        "game-designer",
        "qa-engineer",
        "tech-lead",
    ])
    def test_sonnet_agents(self, agents, agent_defaults, agent_id):
        """game-designer, qa-engineer, tech-lead must use a sonnet model."""
        model = self._get_model(agents, agent_defaults, agent_id)
        assert model is not None, f"Agent {agent_id} not found in agents.yaml"
        assert "sonnet" in model.lower(), (
            f"{agent_id} should use sonnet, got: {model}"
        )

    @pytest.mark.parametrize("agent_id", [
        "analytics-reporter",
        "producer",
        "publisher",
        "telemetry-engineer",
        "metrics-dashboard-builder",
    ])
    def test_haiku_agents(self, agents, agent_defaults, agent_id):
        """analytics-reporter, producer, publisher, telemetry-engineer,
        metrics-dashboard-builder must use a haiku model."""
        model = self._get_model(agents, agent_defaults, agent_id)
        assert model is not None, f"Agent {agent_id} not found in agents.yaml"
        assert "haiku" in model.lower(), (
            f"{agent_id} should use haiku, got: {model}"
        )

    def test_handoff_summarizer_exists_with_haiku(self, agents, agent_defaults):
        """handoff-summarizer agent must exist and use a haiku model."""
        assert "handoff-summarizer" in agents, (
            "handoff-summarizer agent missing from agents.yaml"
        )
        model = self._get_model(agents, agent_defaults, "handoff-summarizer")
        assert "haiku" in model.lower(), (
            f"handoff-summarizer should use haiku, got: {model}"
        )


# ---------------------------------------------------------------------------
# 4. handoff_brief_v1 schema
# ---------------------------------------------------------------------------

class TestHandoffBriefSchema:
    EXPECTED_FIELDS = {"decisions", "artifacts_ready", "whats_next", "watch_for"}

    def test_handoff_brief_v1_schema_exists(self, schemas_yaml):
        """handoff_brief_v1 schema must exist in artifact_schemas.yaml."""
        schemas = schemas_yaml.get("schemas", {})
        assert "handoff_brief_v1" in schemas, (
            "handoff_brief_v1 schema missing from artifact_schemas.yaml"
        )

    def test_handoff_brief_v1_has_four_required_fields(self, schemas_yaml):
        """handoff_brief_v1 must declare exactly 4 required fields."""
        schema = schemas_yaml.get("schemas", {}).get("handoff_brief_v1", {})
        required = set(schema.get("required_fields", []))
        assert len(required) == 4, (
            f"handoff_brief_v1 should have 4 required fields, got {len(required)}: {required}"
        )

    def test_handoff_brief_v1_required_field_names(self, schemas_yaml):
        """handoff_brief_v1 required fields must match expected names."""
        schema = schemas_yaml.get("schemas", {}).get("handoff_brief_v1", {})
        required = set(schema.get("required_fields", []))
        assert required == self.EXPECTED_FIELDS, (
            f"handoff_brief_v1 required_fields mismatch.\n"
            f"  Expected: {self.EXPECTED_FIELDS}\n"
            f"  Got:      {required}"
        )
