"""Phase 3 tests: before/after regression and per-level difficulty tuning.

Covers:
  - _compare_telemetry_regression: KPI comparison with tolerance
  - _generate_difficulty_tuning: per-level and session-level recommendations
"""

from __future__ import annotations

import pytest

from src.iteration.iterate_runner import (
    _compare_telemetry_regression,
    _generate_difficulty_tuning,
)


# ── _compare_telemetry_regression ────────────────────────────────────────────


class TestCompareTelemetryRegression:
    def test_no_previous_baseline_returns_empty(self):
        """When there is no previous data (empty dict), no regression is flagged."""
        result = _compare_telemetry_regression({}, {"avg_session_seconds": 120.0})
        assert result == []

    def test_no_regression_when_session_unchanged(self):
        """Same avg_session_seconds → no regression."""
        prev = {"avg_session_seconds": 120.0}
        curr = {"avg_session_seconds": 120.0}
        assert _compare_telemetry_regression(prev, curr) == []

    def test_avg_session_regression_50pct_drop(self):
        """60s vs previous 120s is a 50% drop → regression flagged."""
        prev = {"avg_session_seconds": 120.0}
        curr = {"avg_session_seconds": 60.0}
        regressions = _compare_telemetry_regression(prev, curr)
        assert len(regressions) == 1
        assert "avg_session_seconds" in regressions[0]

    def test_death_rate_regression_33pct_increase(self):
        """2.0 vs previous 1.5 is a 33% increase (> 5% tolerance) → regression."""
        prev = {"death_rate_per_min": 1.5}
        curr = {"death_rate_per_min": 2.0}
        regressions = _compare_telemetry_regression(prev, curr)
        assert len(regressions) == 1
        assert "death_rate_per_min" in regressions[0]

    def test_death_rate_regression_6_7pct_increase(self):
        """1.6 vs previous 1.5 is a 6.7% increase (> 5% tolerance) → regression."""
        prev = {"death_rate_per_min": 1.5}
        curr = {"death_rate_per_min": 1.6}
        regressions = _compare_telemetry_regression(prev, curr)
        assert len(regressions) == 1
        assert "death_rate_per_min" in regressions[0]

    def test_death_rate_no_regression_within_tolerance(self):
        """1.52 vs previous 1.5 is a 1.3% increase (within 5% tolerance) → no regression."""
        prev = {"death_rate_per_min": 1.5}
        curr = {"death_rate_per_min": 1.52}
        regressions = _compare_telemetry_regression(prev, curr)
        assert regressions == []

    def test_both_metrics_regress_both_reported(self):
        """When both avg_session_seconds and death_rate_per_min regress, both are reported."""
        prev = {"avg_session_seconds": 120.0, "death_rate_per_min": 1.5}
        curr = {"avg_session_seconds": 60.0, "death_rate_per_min": 2.0}
        regressions = _compare_telemetry_regression(prev, curr)
        assert len(regressions) == 2
        metrics = " ".join(regressions)
        assert "avg_session_seconds" in metrics
        assert "death_rate_per_min" in metrics

    def test_level1_completion_rate_regression(self):
        """Completion rate drop from 0.8 to 0.5 (37.5% drop) → regression."""
        prev = {"level1_completion_rate": 0.8}
        curr = {"level1_completion_rate": 0.5}
        regressions = _compare_telemetry_regression(prev, curr)
        assert len(regressions) == 1
        assert "level1_completion_rate" in regressions[0]

    def test_level1_completion_rate_no_regression_within_tolerance(self):
        """Completion rate drop from 0.8 to 0.77 (3.75% drop, within 5%) → no regression."""
        prev = {"level1_completion_rate": 0.8}
        curr = {"level1_completion_rate": 0.77}
        regressions = _compare_telemetry_regression(prev, curr)
        assert regressions == []

    def test_custom_tolerance_pct(self):
        """Custom tolerance_pct=10 allows up to 10% degradation."""
        prev = {"avg_session_seconds": 120.0}
        # 7% drop — within 10% tolerance
        curr_ok = {"avg_session_seconds": 112.0}
        assert _compare_telemetry_regression(prev, curr_ok, tolerance_pct=10.0) == []
        # 15% drop — exceeds 10% tolerance
        curr_bad = {"avg_session_seconds": 102.0}
        regressions = _compare_telemetry_regression(prev, curr_bad, tolerance_pct=10.0)
        assert len(regressions) == 1

    def test_missing_kpi_in_current_skipped(self):
        """If current dict doesn't have a KPI, that KPI is skipped (no crash)."""
        prev = {"avg_session_seconds": 120.0, "death_rate_per_min": 1.5}
        curr = {"avg_session_seconds": 60.0}  # death_rate_per_min absent
        regressions = _compare_telemetry_regression(prev, curr)
        # Only avg_session_seconds should be flagged
        assert len(regressions) == 1
        assert "avg_session_seconds" in regressions[0]


# ── _generate_difficulty_tuning ──────────────────────────────────────────────


class TestGenerateDifficultyTuning:
    def test_high_death_rate_level1_reduce_spawn(self):
        """death_rate 4.0/min on level 1 → 'reduce spawn rate by 20%'."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 4.0, "completion_rate": 50.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        death_recs = [r for r in recs if r["metric"] == "death_rate" and r["level"] == 1]
        assert len(death_recs) == 1
        assert "reduce spawn rate" in death_recs[0]["recommendation"]
        assert death_recs[0]["current"] == 4.0

    def test_low_death_rate_level2_add_elite_enemy(self):
        """death_rate 0.3/min on level 2 → 'add elite enemy variant'."""
        telemetry = {"per_level": [{"level": 2, "death_rate": 0.3, "completion_rate": 60.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        death_recs = [r for r in recs if r["metric"] == "death_rate" and r["level"] == 2]
        assert len(death_recs) == 1
        assert "elite enemy" in death_recs[0]["recommendation"]
        assert death_recs[0]["current"] == 0.3

    def test_high_completion_rate_add_bonus_challenge(self):
        """completion_rate 95% → 'add bonus challenge'."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 1.0, "completion_rate": 95.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        cr_recs = [r for r in recs if r["metric"] == "completion_rate"]
        assert len(cr_recs) == 1
        assert "bonus challenge" in cr_recs[0]["recommendation"]
        assert cr_recs[0]["current"] == 95.0

    def test_low_completion_rate_reduce_enemy_speed(self):
        """completion_rate 20% → 'reduce enemy speed by 15%'."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 1.0, "completion_rate": 20.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        cr_recs = [r for r in recs if r["metric"] == "completion_rate"]
        assert len(cr_recs) == 1
        assert "enemy speed" in cr_recs[0]["recommendation"]
        assert cr_recs[0]["current"] == 20.0

    def test_short_session_extend_duration(self):
        """avg_session_seconds 60 (<90) → 'extend level duration or reduce difficulty'."""
        telemetry = {"avg_session_seconds": 60.0, "per_level": []}
        recs = _generate_difficulty_tuning(telemetry)
        sess_recs = [r for r in recs if r["metric"] == "avg_session_seconds"]
        assert len(sess_recs) == 1
        assert "extend" in sess_recs[0]["recommendation"]
        assert sess_recs[0]["current"] == 60.0
        assert sess_recs[0]["target"] == 90.0

    def test_long_session_add_skip_option(self):
        """avg_session_seconds 400 (>300) → 'add skip option or reduce level length'."""
        telemetry = {"avg_session_seconds": 400.0, "per_level": []}
        recs = _generate_difficulty_tuning(telemetry)
        sess_recs = [r for r in recs if r["metric"] == "avg_session_seconds"]
        assert len(sess_recs) == 1
        assert "skip option" in sess_recs[0]["recommendation"]
        assert sess_recs[0]["target"] == 300.0

    def test_empty_telemetry_returns_empty_list(self):
        """Empty telemetry dict → empty list, no crash."""
        assert _generate_difficulty_tuning({}) == []

    def test_no_per_level_data_returns_empty_for_level_rules(self):
        """Telemetry without per_level → no per-level recommendations."""
        telemetry = {"avg_session_seconds": 150.0}  # within range, no per_level
        recs = _generate_difficulty_tuning(telemetry)
        assert recs == []

    def test_multiple_levels_multiple_recommendations(self):
        """Multiple levels with issues → one recommendation per issue."""
        telemetry = {
            "per_level": [
                {"level": 1, "death_rate": 4.0, "completion_rate": 95.0},  # 2 issues
                {"level": 2, "death_rate": 0.3, "completion_rate": 20.0},  # 2 issues
            ]
        }
        recs = _generate_difficulty_tuning(telemetry)
        assert len(recs) == 4

    def test_death_rate_exactly_at_boundary_not_flagged(self):
        """death_rate exactly 3.0 is not > 3.0, so no 'reduce spawn rate' rec."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 3.0, "completion_rate": 50.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        spawn_recs = [r for r in recs if "reduce spawn rate" in r.get("recommendation", "")]
        assert spawn_recs == []

    def test_death_rate_exactly_0_5_not_flagged(self):
        """death_rate exactly 0.5 is not < 0.5, so no 'add elite enemy' rec."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 0.5, "completion_rate": 50.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        elite_recs = [r for r in recs if "elite enemy" in r.get("recommendation", "")]
        assert elite_recs == []

    def test_recommendation_shape(self):
        """Each recommendation has the required keys with correct types."""
        telemetry = {"per_level": [{"level": 1, "death_rate": 5.0, "completion_rate": 50.0}]}
        recs = _generate_difficulty_tuning(telemetry)
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec["level"], int)
        assert isinstance(rec["metric"], str)
        assert isinstance(rec["current"], float)
        assert isinstance(rec["target"], float)
        assert isinstance(rec["recommendation"], str)
