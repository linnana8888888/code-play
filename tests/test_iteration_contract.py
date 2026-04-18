"""Contract lock tests. If you change the metric vocabulary, update this file
in the same commit — the point is to make silent drift impossible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.iteration.contract import (
    AGGREGATE_FNS,
    METRIC_NAMES,
    SCHEMA_VERSION,
    validate_goals_md,
)

BSG_GOALS = Path("/Users/dknanlin/scratch/butt-shooting-game/GOALS.md")


def test_metric_vocabulary_is_frozen():
    # If this test fails, the contract changed. Update METRIC_NAMES AND
    # docs/iteration_contract.md §2 AND bump SCHEMA_VERSION if semantics
    # shifted, then update the expected set below in the same commit.
    expected = {
        "session_duration_sec",
        "levels_reached",
        "score",
        "outcome",
        "accuracy",
        "kills_per_min",
        "damage_taken",
        "dashes_used",
        "stomps_used",
        "xp_levels",
        "upgrades_picked",
        "gems_collected",
        "pickups_collected",
        "time_to_first_kill_sec",
        "time_to_first_levelup_sec",
        "longest_idle_sec",
    }
    assert set(METRIC_NAMES) == expected
    assert AGGREGATE_FNS == frozenset({"median", "p25", "p75", "rate"})
    assert SCHEMA_VERSION == 1


@pytest.mark.skipif(not BSG_GOALS.exists(), reason="butt-shooting-game not checked out locally")
def test_real_goals_md_passes():
    # The canonical fixture: the hand-authored butt-shooting-game/GOALS.md.
    # Zero issues means the validator accepts the production shape.
    issues = validate_goals_md(BSG_GOALS.read_text())
    assert issues == [], f"BSG GOALS.md regressed: {issues}"


def test_unknown_metric_is_flagged():
    # Probe-test: deliberately-broken GOALS referencing `fps` (not in contract).
    bad = "- Threshold: `median(fps) >= 60`\n"
    issues = validate_goals_md(bad)
    kinds = {i.kind for i in issues}
    assert "unknown_metric" in kinds
    assert any(i.detail == "fps" for i in issues)


def test_unknown_aggregate_is_flagged():
    # mean() is not in the whitelist. `session_duration_sec` IS a metric, so
    # the metric check passes; only the aggregate should trigger.
    bad = "- Threshold: `mean(session_duration_sec) >= 180`\n"
    issues = validate_goals_md(bad)
    assert any(i.kind == "unknown_aggregate" and i.detail == "mean" for i in issues)


def test_no_threshold_is_flagged():
    # A GOALS.md with no comparison operator is useless — nothing to rate against.
    issues = validate_goals_md("# Goals\n\nSome prose, no thresholds.\n")
    assert any(i.kind == "no_threshold" for i in issues)


def test_rate_with_variable_and_metric_passes():
    # Probe: butt-shooting GOALS.md §6 uses `rate(id in upgrades_picked)`.
    # `id` is a pseudo-var, `upgrades_picked` is the actual metric — validator
    # must find the metric among all identifiers, not just the first.
    good = "- `rate(id in upgrades_picked) <= 0.80`\n"
    issues = validate_goals_md(good)
    assert [i for i in issues if i.kind in ("unknown_metric", "unknown_aggregate")] == []


def test_prose_does_not_false_positive():
    # Plain prose mentioning function-like tokens shouldn't trip the linter.
    prose = (
        "# Goals\n\n"
        "See Figure 1 (A) for background. Threshold: `median(accuracy) >= 0.3`.\n"
    )
    issues = validate_goals_md(prose)
    # Only "A" could trip aggregate check; it's uppercase so it's filtered.
    assert [i for i in issues if i.kind == "unknown_aggregate"] == []
