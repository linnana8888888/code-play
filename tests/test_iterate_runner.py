"""Unit tests for iterate_runner's aggregation + disk IO paths.

We do NOT exercise the subprocess launch (node/http.server) here — that's for
the Mode-B integration drill. The pure functions are the math that has to be
correct; this file locks that.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.iteration.iterate_runner import (
    aggregate_telemetry,
    load_telemetry_dir,
)


def _fake_run(
    tag: str = "v1",
    outcome: str = "death",
    session_duration_sec: float = 100.0,
    accuracy: float = 0.5,
    levels_reached: int = 1,
    dashes_used: int = 3,
    stomps_used: int = 1,
    time_to_first_kill_sec: float = 10.0,
    upgrades_picked: list[str] | None = None,
    **overrides,
) -> dict:
    base = {
        "schema_version": 1,
        "run_id": "abc12345",
        "started_at": "2026-04-18T00:00:00Z",
        "iteration_tag": tag,
        "outcome": outcome,
        "seed": 0,
        "duration_sec": session_duration_sec,
        "session_duration_sec": session_duration_sec,
        "levels_reached": levels_reached,
        "score": 1000,
        "hi_score_beaten": False,
        "shots_fired": 100,
        "shots_hit": int(100 * accuracy),
        "accuracy": accuracy,
        "kills": 10,
        "kills_per_min": 6.0,
        "boss_hits": 0,
        "boss_kills": 0,
        "damage_taken": 50,
        "times_hurt": 3,
        "dashes_used": dashes_used,
        "stomps_used": stomps_used,
        "xp_gained": 200,
        "xp_levels": 2,
        "upgrades_picked": upgrades_picked or [],
        "modifiers_picked": [],
        "gems_collected": 5,
        "pickups_collected": 8,
        "time_to_first_kill_sec": time_to_first_kill_sec,
        "time_to_first_levelup_sec": 20.0,
        "longest_idle_sec": 2.0,
        "camera_mode_switches": 1,
        "events": [],
    }
    base.update(overrides)
    return base


def test_aggregate_drops_quit_from_valid_set():
    records = [
        _fake_run(outcome="death", session_duration_sec=100),
        _fake_run(outcome="quit", session_duration_sec=999),  # bot crash, drop
        _fake_run(outcome="win", session_duration_sec=200),
    ]
    rollup = aggregate_telemetry(records)
    assert rollup["n_runs"] == 3
    assert rollup["n_valid"] == 2
    assert rollup["outcome_counts"] == {"win": 1, "death": 1, "timeout": 0, "quit": 1}
    # Median over {100, 200} — quit (999) excluded.
    assert rollup["aggregates"]["session_duration_sec"]["median"] == 150.0


def test_aggregate_median_p25_p75_against_known_values():
    # Inclusive quartile method on [1, 2, 3, 4, 5]: p25=2.0, median=3.0, p75=4.0.
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    records = [_fake_run(outcome="death", accuracy=v / 10.0) for v in values]
    rollup = aggregate_telemetry(records)
    agg = rollup["aggregates"]["accuracy"]
    assert agg["median"] == 0.3
    assert agg["p25"] == 0.2
    assert agg["p75"] == 0.4


def test_aggregate_raw_values_enables_rate_downstream():
    # GOALS.md §3 uses rate(levels_reached >= 2) >= 0.40 — postmortem computes
    # this from raw_values.
    records = [
        _fake_run(outcome="death", levels_reached=0),
        _fake_run(outcome="death", levels_reached=1),
        _fake_run(outcome="death", levels_reached=2),
        _fake_run(outcome="win",   levels_reached=3),
        _fake_run(outcome="timeout", levels_reached=2),
    ]
    rollup = aggregate_telemetry(records)
    raw = rollup["raw_values"]["levels_reached"]
    assert sorted(raw) == [0.0, 1.0, 2.0, 2.0, 3.0]
    hit_two_plus = sum(1 for v in raw if v >= 2) / len(raw)
    assert hit_two_plus == 0.6


def test_aggregate_upgrades_histogram():
    records = [
        _fake_run(outcome="death", upgrades_picked=["dmg", "fan"]),
        _fake_run(outcome="death", upgrades_picked=["dmg", "rld"]),
        _fake_run(outcome="win",   upgrades_picked=["dmg"]),
    ]
    rollup = aggregate_telemetry(records)
    assert rollup["upgrades_histogram"] == {"dmg": 3, "fan": 1, "rld": 1}


def test_aggregate_handles_empty_valid_set():
    # All quits → n_valid=0, aggregates all zero, but shape intact.
    records = [_fake_run(outcome="quit") for _ in range(3)]
    rollup = aggregate_telemetry(records)
    assert rollup["n_valid"] == 0
    for metric_block in rollup["aggregates"].values():
        assert metric_block == {"median": 0.0, "p25": 0.0, "p75": 0.0}


def test_aggregate_missing_field_defaults_to_zero():
    # A bot emitting schema v1 but missing `stomps_used` shouldn't crash.
    records = [_fake_run(outcome="death")]
    records[0].pop("stomps_used")
    rollup = aggregate_telemetry(records)
    assert rollup["aggregates"]["stomps_used"]["median"] == 0.0


def test_load_telemetry_dir_filters_by_tag_and_schema(tmp_path: Path):
    dir_ = tmp_path / "telemetry"
    dir_.mkdir()
    keep_v1 = dir_ / "2026-04-18T00-00-00Z-aaaa.json"
    keep_v1.write_text(json.dumps(_fake_run(tag="v1", outcome="death")))
    skip_v2 = dir_ / "2026-04-18T00-01-00Z-bbbb.json"
    skip_v2.write_text(json.dumps(_fake_run(tag="v2", outcome="death")))
    bad_json = dir_ / "2026-04-18T00-02-00Z-cccc.json"
    bad_json.write_text("{not json")
    wrong_schema = dir_ / "2026-04-18T00-03-00Z-dddd.json"
    wrong_schema.write_text(json.dumps(_fake_run(tag="v1", outcome="death", schema_version=99)))

    records, paths = load_telemetry_dir(dir_, "v1")
    assert [p.name for p in paths] == ["2026-04-18T00-00-00Z-aaaa.json"]
    assert len(records) == 1


def test_load_telemetry_dir_missing_dir_returns_empty(tmp_path: Path):
    records, paths = load_telemetry_dir(tmp_path / "no-such", "v1")
    assert records == []
    assert paths == []
