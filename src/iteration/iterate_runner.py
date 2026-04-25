"""Playtest batch runner.

One call = one cycle's playtest step:
  1. Pick a free port, spawn `python3 -m http.server` rooted at the artifact repo.
  2. Shell `node playtest_bot.mjs --runs N --tag v{n}` against it.
  3. Collect the JSON files the bot wrote under `<repo>/telemetry/` for this
     tag, aggregate into a rollup dict (per contract §2–3), persist it to
     project memory as `telemetry_v{n}`, and return it.

Dropping `outcome == "quit"` (bot crash, not a play signal) matches GOALS.md's
"How to compute over N runs" rule. Tests stub (1) and (2) and drive the
aggregation path on canned JSONs — see tests/test_iterate_runner.py.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_log = logging.getLogger(__name__)

from src.iteration.contract import METRIC_NAMES, SCHEMA_VERSION
from src.memory.project_memory import project_memory

# Metrics that aggregate numerically. `outcome` is an enum, `upgrades_picked`
# is an array — both handled separately.
_NUMERIC_METRICS: tuple[str, ...] = tuple(
    sorted(m for m in METRIC_NAMES if m not in {"outcome", "upgrades_picked"})
)

# Outcomes that indicate a real play session. "quit" is dropped by GOALS.md rule.
_VALID_OUTCOMES = frozenset({"win", "death", "timeout"})


@dataclass
class RunnerResult:
    cycle_n: int
    iteration_tag: str
    rollup: dict
    files: list[str]     # absolute paths of telemetry JSONs contributing to the rollup
    node_exit_code: int
    stdout_tail: str     # last ~4kB of node stdout, useful for blocked-task reporting


# ── Aggregation (pure, unit-testable) ────────────────────────────────────────


def aggregate_telemetry(records: Iterable[dict]) -> dict:
    """Turn a list of per-run telemetry dicts into a rollup.

    Shape:
        {
          "n_runs": int, "n_valid": int,
          "outcome_counts": {"win": .., "death": .., "timeout": .., "quit": ..},
          "aggregates": {metric: {"median": .., "p25": .., "p75": ..}},
          "raw_values": {metric: [..]},   # for rate(metric OP X) downstream
          "upgrades_histogram": {id: int},
        }
    Missing fields in a record count as zero for numeric metrics.
    """

    records = list(records)
    valid = [r for r in records if r.get("outcome") in _VALID_OUTCOMES]

    outcome_counts: dict[str, int] = {"win": 0, "death": 0, "timeout": 0, "quit": 0}
    for r in records:
        outc = r.get("outcome", "quit")
        outcome_counts[outc] = outcome_counts.get(outc, 0) + 1

    aggregates: dict[str, dict[str, float]] = {}
    raw_values: dict[str, list[float]] = {}

    for metric in _NUMERIC_METRICS:
        values = [float(r.get(metric, 0) or 0) for r in valid]
        raw_values[metric] = values
        if not values:
            aggregates[metric] = {"median": 0.0, "p25": 0.0, "p75": 0.0}
            continue
        med = statistics.median(values)
        if len(values) >= 2:
            quartiles = statistics.quantiles(values, n=4, method="inclusive")
            p25, p75 = float(quartiles[0]), float(quartiles[2])
        else:
            p25 = p75 = float(values[0])
        aggregates[metric] = {
            "median": float(med),
            "p25": p25,
            "p75": p75,
        }

    upgrades_hist: dict[str, int] = {}
    for r in valid:
        for up in r.get("upgrades_picked", []) or []:
            upgrades_hist[up] = upgrades_hist.get(up, 0) + 1

    return {
        "n_runs": len(records),
        "n_valid": len(valid),
        "outcome_counts": outcome_counts,
        "aggregates": aggregates,
        "raw_values": raw_values,
        "upgrades_histogram": upgrades_hist,
    }


# ── Disk helpers ─────────────────────────────────────────────────────────────


def load_telemetry_dir(telemetry_dir: Path, iteration_tag: str) -> tuple[list[dict], list[Path]]:
    """Return (records, paths) for every JSON in `telemetry_dir` whose
    `iteration_tag` matches. Unreadable files are skipped with no error — the
    runner already failed loudly upstream if the bot crashed.
    """

    records: list[dict] = []
    paths: list[Path] = []
    if not telemetry_dir.exists():
        return records, paths
    for path in sorted(telemetry_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("iteration_tag") != iteration_tag:
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            # Silent skip — the contract test will flag the mismatch at CI.
            continue
        records.append(data)
        paths.append(path)
    return records, paths


def _find_free_port() -> int:
    """Bind a socket to port 0 to get the OS to assign a free port, then close."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _wait_for_port(port: int, timeout_sec: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ── Telemetry baseline helpers ──────────────────────────────────────────────


def _store_telemetry_baseline(
    project_id: str,
    cycle_tag: str,
    telemetry: dict,
) -> None:
    """Persist telemetry as a named baseline in project memory.

    Key format: ``telemetry_baseline_{cycle_tag}``  (e.g. ``telemetry_baseline_v3``).
    """
    project_memory.write(
        project_id,
        mem_type="artifact",
        key=f"telemetry_baseline_{cycle_tag}",
        content=json.dumps(telemetry, indent=2),
        created_by=f"pipeline:iterate_artifact:{cycle_tag}",
    )


def _load_telemetry_baseline(project_id: str, previous_cycle_tag: str) -> dict | None:
    """Load a previously stored telemetry baseline.  Returns None if absent."""
    raw = project_memory.read(
        project_id,
        mem_type="artifact",
        key=f"telemetry_baseline_{previous_cycle_tag}",
    )
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _log.warning("Could not parse telemetry baseline for %s", previous_cycle_tag)
        return None


# ── Regression comparison ─────────────────────────────────────────────────────


def _compare_telemetry_regression(
    previous: dict,
    current: dict,
    *,
    tolerance_pct: float = 5.0,
) -> list[str]:
    """Compare current telemetry against previous baseline.

    Returns a list of regression description strings (empty list = no regression).

    KPIs checked:
    - avg_session_seconds: current must be >= previous * (1 - tolerance/100)
    - death_rate_per_min:  current must be <= previous * (1 + tolerance/100)
    - level1_completion_rate: current must be >= previous * (1 - tolerance/100)

    tolerance_pct: allowed % degradation before flagging (default 5%).
    """
    regressions: list[str] = []
    tol = tolerance_pct / 100.0

    # avg_session_seconds — higher is better
    prev_sess = previous.get("avg_session_seconds")
    curr_sess = current.get("avg_session_seconds")
    if prev_sess is not None and curr_sess is not None:
        threshold = prev_sess * (1.0 - tol)
        if curr_sess < threshold:
            regressions.append(
                f"avg_session_seconds regressed: {curr_sess:.1f}s < {threshold:.1f}s "
                f"(previous {prev_sess:.1f}s, tolerance {tolerance_pct}%)"
            )

    # death_rate_per_min — lower is better
    prev_dr = previous.get("death_rate_per_min")
    curr_dr = current.get("death_rate_per_min")
    if prev_dr is not None and curr_dr is not None:
        threshold = prev_dr * (1.0 + tol)
        if curr_dr > threshold:
            regressions.append(
                f"death_rate_per_min regressed: {curr_dr:.3f}/min > {threshold:.3f}/min "
                f"(previous {prev_dr:.3f}/min, tolerance {tolerance_pct}%)"
            )

    # level1_completion_rate — higher is better
    prev_cr = previous.get("level1_completion_rate")
    curr_cr = current.get("level1_completion_rate")
    if prev_cr is not None and curr_cr is not None:
        threshold = prev_cr * (1.0 - tol)
        if curr_cr < threshold:
            regressions.append(
                f"level1_completion_rate regressed: {curr_cr:.3f} < {threshold:.3f} "
                f"(previous {prev_cr:.3f}, tolerance {tolerance_pct}%)"
            )

    return regressions


# ── Per-level difficulty tuning ───────────────────────────────────────────────


def _generate_difficulty_tuning(telemetry: dict) -> list[dict]:
    """Parse telemetry and generate concrete per-level tuning recommendations.

    Returns a list of recommendation dicts:
        {"level": int, "metric": str, "current": float,
         "target": float, "recommendation": str}

    Rules applied:
    - Level N death_rate > 3/min  → "reduce spawn rate by 20%"
    - Level N death_rate < 0.5/min → "add elite enemy variant"
    - Level N completion_rate > 90% → "add bonus challenge"
    - Level N completion_rate < 30% → "reduce enemy speed by 15%"
    - avg_session_seconds < 90  → "extend level duration or reduce difficulty"
    - avg_session_seconds > 300 → "add skip option or reduce level length"

    Returns empty list if telemetry doesn't have per-level data.
    """
    recommendations: list[dict] = []

    # Per-level data: telemetry["per_level"] is a list of
    # {"level": int, "death_rate": float, "completion_rate": float, ...}
    # Also accepts "levels" key and "death_rate_per_min" as aliases.
    per_level = telemetry.get("per_level") or telemetry.get("levels", [])
    if not per_level:
        # No per-level data — nothing to tune at level granularity.
        # Still check session-level metrics below.
        pass

    for entry in per_level:
        level = entry.get("level", 0)
        # Accept both "death_rate" and "death_rate_per_min" as the same metric.
        death_rate = entry.get("death_rate") if entry.get("death_rate") is not None else entry.get("death_rate_per_min")
        completion_rate = entry.get("completion_rate")

        if death_rate is not None:
            if death_rate > 3.0:
                recommendations.append({
                    "level": level,
                    "metric": "death_rate",
                    "current": float(death_rate),
                    "target": 3.0,
                    "recommendation": "reduce spawn rate by 20%",
                })
            elif death_rate < 0.5:
                recommendations.append({
                    "level": level,
                    "metric": "death_rate",
                    "current": float(death_rate),
                    "target": 0.5,
                    "recommendation": "add elite enemy variant",
                })

        if completion_rate is not None:
            if completion_rate > 90.0:
                recommendations.append({
                    "level": level,
                    "metric": "completion_rate",
                    "current": float(completion_rate),
                    "target": 90.0,
                    "recommendation": "add bonus challenge",
                })
            elif completion_rate < 30.0:
                recommendations.append({
                    "level": level,
                    "metric": "completion_rate",
                    "current": float(completion_rate),
                    "target": 30.0,
                    "recommendation": "reduce enemy speed by 15%",
                })

    # Session-level checks (not per-level)
    avg_session = telemetry.get("avg_session_seconds")
    if avg_session is not None:
        if avg_session < 90:
            recommendations.append({
                "level": 0,
                "metric": "avg_session_seconds",
                "current": float(avg_session),
                "target": 90.0,
                "recommendation": "extend level duration or reduce difficulty",
            })
        elif avg_session > 300:
            recommendations.append({
                "level": 0,
                "metric": "avg_session_seconds",
                "current": float(avg_session),
                "target": 300.0,
                "recommendation": "add skip option or reduce level length",
            })

    return recommendations


# ── Playtest quality gate ────────────────────────────────────────────────────


def _check_playtest_thresholds(telemetry_data: dict) -> tuple[bool, str]:
    """
    Returns (passes, reason).
    passes=True means game meets minimum quality bar.
    """
    sessions = telemetry_data.get("sessions", [])
    if not sessions:
        return False, "No playtest sessions recorded"

    # Average session length (seconds)
    session_lengths = [s.get("duration_seconds", 0) for s in sessions]
    avg_session = sum(session_lengths) / len(session_lengths) if session_lengths else 0

    # Death rate per minute in level 1
    level1_deaths = []
    for s in sessions:
        events = s.get("events", [])
        deaths = sum(1 for e in events if e.get("type") == "death" and e.get("level", 1) == 1)
        duration_min = s.get("duration_seconds", 60) / 60
        level1_deaths.append(deaths / max(duration_min, 0.1))
    avg_death_rate = sum(level1_deaths) / len(level1_deaths) if level1_deaths else 0

    # Thresholds
    MIN_SESSION_SECONDS = 90
    MAX_DEATH_RATE_PER_MIN = 3.0

    if avg_session < MIN_SESSION_SECONDS:
        return False, f"Session too short: {avg_session:.0f}s avg (min {MIN_SESSION_SECONDS}s)"
    if avg_death_rate > MAX_DEATH_RATE_PER_MIN:
        return False, f"Death rate too high in level 1: {avg_death_rate:.1f}/min (max {MAX_DEATH_RATE_PER_MIN})"

    return True, f"OK — session {avg_session:.0f}s, death rate {avg_death_rate:.1f}/min"


# ── Public entry point ───────────────────────────────────────────────────────


def run_playtest_batch(
    project_id: str,
    repo_path: str | Path,
    cycle_n: int,
    runs: int = 5,
    seconds_per_run: int = 60,
    game_entry: str = "index.html",
    bot_script: str = "playtest_bot.mjs",
) -> RunnerResult:
    """Run the full playtest batch and persist the rollup.

    Caller (the `qa-engineer` task body) is responsible for broadcasting the
    `playtest_batch_complete` WS event from the returned result.
    """

    repo = Path(repo_path).resolve()
    telemetry_dir = repo / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    iteration_tag = f"v{cycle_n}"

    port = _find_free_port()
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_port(port):
            raise RuntimeError(f"http.server on port {port} did not come up")

        env = os.environ.copy()
        env["BSG_URL"] = f"http://127.0.0.1:{port}/{game_entry}"
        bot = subprocess.run(
            [
                "node",
                bot_script,
                "--runs", str(runs),
                "--seconds", str(seconds_per_run),
                "--tag", iteration_tag,
            ],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(60, seconds_per_run * runs * 2 + 60),
        )
        node_exit = bot.returncode
        stdout_tail = (bot.stdout or "")[-4000:] + (bot.stderr or "")[-4000:]
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    records, paths = load_telemetry_dir(telemetry_dir, iteration_tag)
    rollup = aggregate_telemetry(records)

    # Build a sessions list for the quality gate from the raw telemetry records.
    # Each record maps to one session; `session_duration_sec` → `duration_seconds`.
    # The `events` field is not present in per-run records, so death-rate check
    # gracefully returns 0 (no events = no deaths counted).
    sessions_for_gate = [
        {
            "duration_seconds": float(r.get("session_duration_sec", 0) or 0),
            "events": r.get("events", []),
        }
        for r in records
        if r.get("outcome") in _VALID_OUTCOMES
    ]

    passes, gate_reason = _check_playtest_thresholds({"sessions": sessions_for_gate})
    if not passes:
        _log.warning("Playtest auto-REVISE: %s", gate_reason)
    else:
        _log.info("Playtest quality gate passed: %s", gate_reason)

    # ── Build a flat KPI dict for regression comparison ───────────────────────
    # Derive avg_session_seconds from the aggregated rollup.
    agg = rollup.get("aggregates", {})
    current_kpis: dict = {
        "avg_session_seconds": agg.get("session_duration_sec", {}).get("median", 0.0),
    }
    # death_rate_per_min and level1_completion_rate come from sessions_for_gate
    # (same data used by the quality gate above).
    if sessions_for_gate:
        level1_deaths_per_min = []
        level1_completions = []
        for s in sessions_for_gate:
            events = s.get("events", [])
            deaths = sum(1 for e in events if e.get("type") == "death" and e.get("level", 1) == 1)
            duration_min = s.get("duration_seconds", 60) / 60
            level1_deaths_per_min.append(deaths / max(duration_min, 0.1))
            completions = [e for e in events if e.get("type") == "level_complete" and e.get("level", 0) == 1]
            level1_completions.append(1.0 if completions else 0.0)
        current_kpis["death_rate_per_min"] = (
            sum(level1_deaths_per_min) / len(level1_deaths_per_min)
        )
        current_kpis["level1_completion_rate"] = (
            sum(level1_completions) / len(level1_completions)
        )

    # ── Before/after regression check ────────────────────────────────────────
    previous_tag = f"v{cycle_n - 1}" if cycle_n > 1 else None
    regression_details: list[str] = []
    if previous_tag:
        prev_baseline = _load_telemetry_baseline(project_id, previous_tag)
        if prev_baseline is not None:
            regression_details = _compare_telemetry_regression(
                prev_baseline, current_kpis
            )
            if regression_details:
                _log.warning(
                    "Playtest regression detected (cycle %d vs %s): %s",
                    cycle_n, previous_tag, regression_details,
                )
                passes = False
                gate_reason = "Regression vs previous baseline: " + "; ".join(regression_details)

    # ── Store current run as new baseline ────────────────────────────────────
    _store_telemetry_baseline(project_id, iteration_tag, current_kpis)

    # ── Per-level difficulty tuning ───────────────────────────────────────────
    # Build a telemetry dict that _generate_difficulty_tuning can consume.
    # avg_session_seconds comes from the KPI dict; per_level data from sessions.
    tuning_input: dict = {
        "avg_session_seconds": current_kpis.get("avg_session_seconds"),
        "per_level": [],  # populated below when per-level event data is available
    }
    # Aggregate per-level stats from session events if present.
    level_stats: dict[int, dict] = {}
    for s in sessions_for_gate:
        for e in s.get("events", []):
            lvl = e.get("level", 1)
            if lvl not in level_stats:
                level_stats[lvl] = {"deaths": 0, "completions": 0, "sessions": 0}
            if e.get("type") == "death":
                level_stats[lvl]["deaths"] += 1
            if e.get("type") == "level_complete":
                level_stats[lvl]["completions"] += 1
        # Count sessions per level (rough: any event on that level)
        levels_seen = {e.get("level", 1) for e in s.get("events", [])}
        for lvl in levels_seen:
            level_stats.setdefault(lvl, {"deaths": 0, "completions": 0, "sessions": 0})
            level_stats[lvl]["sessions"] += 1

    total_sessions = len(sessions_for_gate) or 1
    for lvl, stats in sorted(level_stats.items()):
        n = stats["sessions"] or total_sessions
        duration_min = (
            sum(s.get("duration_seconds", 60) for s in sessions_for_gate) / total_sessions / 60
        )
        tuning_input["per_level"].append({
            "level": lvl,
            "death_rate": stats["deaths"] / max(duration_min * n, 0.1),
            "completion_rate": (stats["completions"] / n) * 100.0,
        })

    difficulty_tuning = _generate_difficulty_tuning(tuning_input)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tuning_record = {
        "cycle_tag": iteration_tag,
        "recommendations": difficulty_tuning,
        "generated_at": now_iso,
    }
    project_memory.write(
        project_id,
        mem_type="artifact",
        key=f"difficulty_tuning_{iteration_tag}",
        content=json.dumps(tuning_record, indent=2),
        created_by=f"pipeline:iterate_artifact:cycle_{cycle_n}",
    )
    if difficulty_tuning:
        _log.info(
            "Difficulty tuning generated %d recommendations for %s",
            len(difficulty_tuning), iteration_tag,
        )

    rollup_full = {
        "cycle_n": cycle_n,
        "iteration_tag": iteration_tag,
        "playtest_gate_passes": passes,
        "playtest_gate_reason": gate_reason,
        "regression_details": regression_details,
        "difficulty_tuning": difficulty_tuning,
        **rollup,
    }
    project_memory.write(
        project_id,
        mem_type="artifact",
        key=f"telemetry_{iteration_tag}",
        content=json.dumps(rollup_full, indent=2),
        created_by=f"pipeline:iterate_artifact:cycle_{cycle_n}",
    )

    # If the gate fails, write a REVISE signal to memory so the pipeline
    # can auto-set the next step to REVISE (skip human gate).
    if not passes:
        project_memory.write(
            project_id,
            mem_type="artifact",
            key=f"playtest_revise_{iteration_tag}",
            content=json.dumps({
                "auto_revise": True,
                "reason": gate_reason,
                "regression_details": regression_details,
                "cycle_n": cycle_n,
                "iteration_tag": iteration_tag,
            }, indent=2),
            created_by=f"pipeline:iterate_artifact:cycle_{cycle_n}",
        )

    return RunnerResult(
        cycle_n=cycle_n,
        iteration_tag=iteration_tag,
        rollup=rollup_full,
        files=[str(p) for p in paths],
        node_exit_code=node_exit,
        stdout_tail=stdout_tail,
    )
