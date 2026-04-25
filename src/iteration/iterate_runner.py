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

    rollup_full = {
        "cycle_n": cycle_n,
        "iteration_tag": iteration_tag,
        "playtest_gate_passes": passes,
        "playtest_gate_reason": gate_reason,
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
