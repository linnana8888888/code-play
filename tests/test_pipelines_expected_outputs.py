"""Integration-ish test: config/pipelines.yaml → substituted expected_outputs.

Locks two things:
  1. Every non-human-gate step in phased-producer + iterate_artifact declares
     at least one expected_output. If someone drops this block by accident,
     the validator would silently no-op for that step and the silent-success
     bug that drove this work would return.
  2. Template placeholders in those keys render cleanly for a concrete cycle.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.runtime.task_validator import substitute_expected_outputs


def _load_pipelines():
    path = Path(__file__).resolve().parents[1] / "config" / "pipelines.yaml"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["pipelines"]


def test_phased_producer_every_agent_step_has_expected_outputs():
    pipelines = _load_pipelines()
    steps = pipelines["phased-producer"]["steps"]
    missing = [
        s["id"] for s in steps
        if s.get("type") != "human-gate"
        and s.get("agent")
        and not s.get("expected_outputs")
    ]
    assert missing == [], f"phased-producer steps without expected_outputs: {missing}"


def test_iterate_artifact_every_agent_step_has_expected_outputs():
    pipelines = _load_pipelines()
    steps = pipelines["iterate_artifact"]["steps"]
    missing = [
        s["id"] for s in steps
        if s.get("type") != "human-gate"
        and s.get("agent")
        and not s.get("expected_outputs")
    ]
    assert missing == [], f"iterate_artifact steps without expected_outputs: {missing}"


def test_iterate_artifact_templates_render_for_a_concrete_cycle():
    pipelines = _load_pipelines()
    steps = {s["id"]: s for s in pipelines["iterate_artifact"]["steps"]}

    playtest = substitute_expected_outputs(
        steps["playtest"]["expected_outputs"], iteration_tag="v4", cycle_n=4
    )
    assert playtest[0]["key"] == "telemetry_v4"

    postmortem = substitute_expected_outputs(
        steps["postmortem"]["expected_outputs"], iteration_tag="v4", cycle_n=4
    )
    assert postmortem[0]["key"] == "postmortem_v4"

    implement = substitute_expected_outputs(
        steps["implement"]["expected_outputs"], iteration_tag="v4", cycle_n=4
    )
    # implement writes cycle n+1's HTML — templating must advance the index.
    assert implement[0]["key"] == "game_html_v5"


def test_phased_producer_expected_outputs_are_plain_strings():
    """phased-producer is not cyclic — its keys should be static, no {{…}}."""
    pipelines = _load_pipelines()
    for step in pipelines["phased-producer"]["steps"]:
        for entry in step.get("expected_outputs") or []:
            for v in entry.values():
                if isinstance(v, str):
                    assert "{{" not in v, (
                        f"phased-producer step {step['id']} has templated expected_output {entry!r}"
                    )


def test_no_expected_outputs_on_human_gates():
    """Human gates don't produce artifacts — they approve/reject the preceding
    step. Leaving expected_outputs off keeps the validator from no-op-failing
    gate tasks."""
    pipelines = _load_pipelines()
    for pname, pcfg in pipelines.items():
        for step in pcfg.get("steps") or []:
            if step.get("type") == "human-gate":
                assert not step.get("expected_outputs"), (
                    f"human-gate {pname}/{step['id']} should not declare expected_outputs"
                )
