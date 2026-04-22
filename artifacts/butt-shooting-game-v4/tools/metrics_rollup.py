#!/usr/bin/env python3
"""
tools/metrics_rollup.py — Butt Shooting Game metrics rollup
============================================================
Reads all telemetry/*.json files from the artifact repo, materialises
the two-table SQLite store (events + sessions), and prints a JSON
summary.  Idempotent: re-running produces identical output.

Usage:
    python3 tools/metrics_rollup.py <db_path> [telemetry_dir]

    db_path       — path to metrics.sqlite (created if absent)
    telemetry_dir — directory containing *.json run files
                    (default: <repo_root>/telemetry)

The telemetry JSON format used by this artifact is a per-run summary
(not a raw event stream).  Each file has top-level fields:
  run_id, started_at, duration_sec, outcome, iteration_tag,
  shots_fired, shots_hit, accuracy, kills, dashes_used, stomps_used,
  levels_reached, score, damage_taken, times_hurt, xp_gained,
  xp_levels, upgrades_picked, time_to_first_kill_sec,
  time_to_first_levelup_sec, session_duration_sec, ...
  events: [{t, type, ...}, ...]

Schema version: 1
"""

import sqlite3
import json
import sys
import os
import glob
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY,
  session_id   TEXT NOT NULL,
  name         TEXT NOT NULL,
  ts_ms        INTEGER NOT NULL,
  build_sha    TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_name_ts ON events(name, ts_ms);

CREATE TABLE IF NOT EXISTS sessions (
  session_id           TEXT PRIMARY KEY,
  started_at_ms        INTEGER NOT NULL,
  ended_at_ms          INTEGER,
  duration_ms          INTEGER,
  reached_playable     INTEGER NOT NULL DEFAULT 0,
  outcome              TEXT,
  deaths               INTEGER NOT NULL DEFAULT 0,
  retries              INTEGER NOT NULL DEFAULT 0,
  build_sha            TEXT NOT NULL,
  -- game-specific columns promoted from payload
  iteration_tag        TEXT,
  shots_fired          INTEGER NOT NULL DEFAULT 0,
  shots_hit            INTEGER NOT NULL DEFAULT 0,
  accuracy             REAL NOT NULL DEFAULT 0,
  kills                INTEGER NOT NULL DEFAULT 0,
  dashes_used          INTEGER NOT NULL DEFAULT 0,
  stomps_used          INTEGER NOT NULL DEFAULT 0,
  levels_reached       INTEGER NOT NULL DEFAULT 0,
  score                INTEGER NOT NULL DEFAULT 0,
  damage_taken         INTEGER NOT NULL DEFAULT 0,
  times_hurt           INTEGER NOT NULL DEFAULT 0,
  xp_gained            INTEGER NOT NULL DEFAULT 0,
  xp_levels            INTEGER NOT NULL DEFAULT 0,
  time_to_first_kill_sec  REAL NOT NULL DEFAULT 0,
  upgrades_picked_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_build ON sessions(build_sha);
CREATE INDEX IF NOT EXISTS idx_sessions_tag   ON sessions(iteration_tag);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iso(ts_str: str) -> int:
    """Return milliseconds since epoch for an ISO-8601 string."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def ingest_run(con: sqlite3.Connection, run: dict, build_sha: str) -> bool:
    """
    Insert one run's events + session row.  Returns True if the session
    was new (not already present).
    """
    run_id = run.get("run_id", "unknown")
    session_id = run_id

    # Skip if already ingested (idempotency)
    existing = con.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if existing:
        return False

    started_at_str = run.get("started_at", "")
    started_at_ms = parse_iso(started_at_str)
    duration_sec = run.get("duration_sec") or run.get("session_duration_sec") or 0
    duration_ms = int(duration_sec * 1000)
    ended_at_ms = started_at_ms + duration_ms if started_at_ms else None

    raw_outcome = run.get("outcome", "timeout")
    # Normalise: bot crash / quit -> timeout; keep win / death / timeout
    if raw_outcome not in ("win", "death", "timeout"):
        raw_outcome = "timeout"

    # Expand sub-events into the events table
    sub_events = run.get("events", [])
    for ev in sub_events:
        ev_type = ev.get("type", "unknown")
        ev_t_sec = ev.get("t", 0)
        ev_ts_ms = started_at_ms + int(ev_t_sec * 1000)
        payload = {k: v for k, v in ev.items() if k not in ("type", "t")}
        con.execute(
            "INSERT INTO events(session_id, name, ts_ms, build_sha, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, ev_type, ev_ts_ms, build_sha, json.dumps(payload)),
        )

    # Synthesise canonical events for funnel tracking
    # session_start
    con.execute(
        "INSERT INTO events(session_id, name, ts_ms, build_sha, payload_json) "
        "VALUES (?, 'session_start', ?, ?, '{}')",
        (session_id, started_at_ms, build_sha),
    )
    # first_playable — infer from first 'start' or 'levelStart' sub-event
    first_playable_t = None
    for ev in sub_events:
        if ev.get("type") in ("start", "levelStart"):
            first_playable_t = ev.get("t", 0)
            break
    if first_playable_t is not None:
        fp_ts_ms = started_at_ms + int(first_playable_t * 1000)
        con.execute(
            "INSERT INTO events(session_id, name, ts_ms, build_sha, payload_json) "
            "VALUES (?, 'first_playable', ?, ?, '{}')",
            (session_id, fp_ts_ms, build_sha),
        )

    # session_end / win / death terminal event
    end_event_name = raw_outcome if raw_outcome in ("win", "death") else "session_end"
    if ended_at_ms:
        con.execute(
            "INSERT INTO events(session_id, name, ts_ms, build_sha, payload_json) "
            "VALUES (?, ?, ?, ?, '{}')",
            (session_id, end_event_name, ended_at_ms, build_sha),
        )

    # Count deaths from sub-events
    death_count = sum(1 for ev in sub_events if ev.get("type") == "death")
    if death_count == 0 and raw_outcome == "death":
        death_count = 1

    # Insert session row
    con.execute(
        """
        INSERT INTO sessions(
             session_id, started_at_ms, ended_at_ms, duration_ms,
             reached_playable, outcome, deaths, retries, build_sha,
             iteration_tag, shots_fired, shots_hit, accuracy, kills,
             dashes_used, stomps_used, levels_reached, score,
             damage_taken, times_hurt, xp_gained, xp_levels,
             time_to_first_kill_sec, upgrades_picked_json
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id,
            started_at_ms,
            ended_at_ms,
            duration_ms,
            1 if first_playable_t is not None else 0,
            raw_outcome,
            death_count,
            0,
            build_sha,
            run.get("iteration_tag", ""),
            run.get("shots_fired", 0),
            run.get("shots_hit", 0),
            run.get("accuracy", 0.0),
            run.get("kills", 0),
            run.get("dashes_used", 0),
            run.get("stomps_used", 0),
            run.get("levels_reached", 0),
            run.get("score", 0),
            run.get("damage_taken", 0),
            run.get("times_hurt", 0),
            run.get("xp_gained", 0),
            run.get("xp_levels", 0),
            run.get("time_to_first_kill_sec", 0),
            json.dumps(run.get("upgrades_picked", [])),
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Main rollup
# ---------------------------------------------------------------------------

def rollup(db_path: str, telemetry_dir: str) -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_DDL)
    con.commit()

    before_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    pattern = os.path.join(telemetry_dir, "*.json")
    files = sorted(glob.glob(pattern))

    sessions_added = 0

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                run = json.load(f)
        except Exception as e:
            print(f"[WARN] Could not parse {fpath}: {e}", file=sys.stderr)
            continue

        fname = os.path.basename(fpath)
        sha_part = fname.rsplit("-", 1)[-1].replace(".json", "")
        build_sha = sha_part if len(sha_part) == 8 else "unknown"

        added = ingest_run(con, run, build_sha)
        if added:
            sessions_added += 1

    con.commit()

    after_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    after_events   = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    con.close()

    return {
        "db_path": db_path,
        "telemetry_dir": telemetry_dir,
        "files_scanned": len(files),
        "sessions_total": after_sessions,
        "sessions_added": sessions_added,
        "rows_added": after_events - before_events,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python3 tools/metrics_rollup.py <db_path> [telemetry_dir]",
            file=sys.stderr,
        )
        sys.exit(1)

    db = sys.argv[1]
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tel_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(repo_root, "telemetry")

    result = rollup(db, tel_dir)
    print(json.dumps(result, indent=2))
