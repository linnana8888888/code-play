# Iteration Contract — code-play doctrine

**Status:** canonical. All game artifacts produced or iterated through code-play
reference this file. Promoted from butt-shooting-game's per-game contract so the
telemetry schema, metric vocabulary, and aggregate-function whitelist live in
one place and cannot drift per game.

**Who reads it:** the scaffolder (`src/iteration/scaffolder.py`) at new-game
build time, the runtime validator (`src/iteration/contract.py`) at cycle time,
and every postmortem/propose agent task in the `iterate_artifact` pipeline.

**IMPORTANT: keep in sync.** `src/iteration/contract.py` re-exports the metric
name set and aggregate whitelist from this file. If you edit §2 or the
aggregate list in §3, update `contract.py` in the same commit and rerun
`tests/test_iteration_contract.py` — the test locks the vocabulary.

## 1a. `window.GameAPI` — the bot ↔ game contract (mandatory)

Every code-play game artifact **must** expose `window.GameAPI` on its entry
HTML before `playtest_bot.mjs` is asked to drive it. The bot never reaches into
game internals (`window.__game.game.*`, DOM ids, …). It drives and reads the
game **only through this interface**, so a bot built for one artifact can drive
any other artifact without changes.

```ts
window.GameAPI = {
  version: 1,

  /**
   * Begin a run. MUST resolve once `getState() === 'play'` is guaranteed
   * (the first input tick after the player entity exists). Seed is optional
   * but, if honored, makes runs reproducible for A/B postmortems.
   */
  start(opts?: { seed?: number }): Promise<void>,

  /**
   * One of 'title' | 'play' | 'picker' | 'paused' | 'win' | 'gameover'.
   * 'picker' means a modal (level-up / modifier / upgrade) is open and the
   * bot should call pickCard(i) instead of issuing gameplay input.
   */
  getState(): 'title' | 'play' | 'picker' | 'paused' | 'win' | 'gameover',

  /**
   * Everything the bot needs to fill telemetry without DOM scraping. Shape:
   *
   *   {
   *     schemaVersion: 1,
   *     state, pickerOpen, score, hiScore,
   *     level:    { idx, name },
   *     xp:       { level, gained },
   *     counters: { shots, hits, kills, bossHits, bossKills, dashes, pickups, ... },
   *     events:   [ {t, type, ...}, ... ],   // last 400
   *     mag?, combo?                         // game-specific extras allowed
   *   }
   *
   * Games without a given counter omit the key (bot treats missing as 0).
   * Counters MUST cover every metric GOALS.md refs in §2 — there is no other
   * way for the bot to observe them without reverse-engineering internals.
   */
  getSnapshot(): GameSnapshot,

  /**
   * Click the `idx`-th card in an open picker modal. Returns false if no
   * picker is up. Present even when the game has no picker flow — callers
   * can no-op.
   */
  pickCard(idx: number): boolean,

  /** Optional teardown. Default implementation may be empty. */
  stop?(): void,
}
```

**Why a separate API and not just `__game`?** `__game` is free-form dev
inspection — its shape drifts with refactors and differs per game. `GameAPI`
is a stable, versioned contract the bot + analytics can rely on. Games should
keep `__game` for dev panels but route every bot interaction through
`GameAPI`.

**Bump `version`** whenever the snapshot shape or method signatures change.
Old bots detect the bump and should refuse to run rather than emit silently
broken telemetry.

## 1. Telemetry schema (what `playtest_bot.mjs` writes per run)

File: `<artifact_repo>/telemetry/<iso8601>-<run-id>.json`

```jsonc
{
  "schema_version": 1,
  "run_id": "string",                    // uuid or timestamp-based
  "started_at": "ISO-8601",
  "duration_sec": 0,                     // wall-clock in play state
  "outcome": "win|death|timeout|quit",
  "iteration_tag": "string",             // e.g. "v1", "v4.1"; set by runner
  "seed": 0,                             // RNG seed for reproducibility

  // ── Core funnel metrics ────────────────────────────────────────────────
  "session_duration_sec": 0,             // first input → death/win
  "levels_reached": 0,
  "score": 0,
  "hi_score_beaten": false,

  // ── Combat metrics ─────────────────────────────────────────────────────
  "shots_fired": 0,
  "shots_hit": 0,
  "accuracy": 0.0,                       // hits / max(1, shots)
  "kills": 0,
  "kills_per_min": 0.0,
  "boss_hits": 0,
  "boss_kills": 0,

  // ── Survival metrics ───────────────────────────────────────────────────
  "damage_taken": 0,
  "times_hurt": 0,
  "dashes_used": 0,
  "stomps_used": 0,

  // ── Progression metrics ────────────────────────────────────────────────
  "xp_gained": 0,
  "xp_levels": 0,
  "upgrades_picked": [],                 // ordered ids, e.g. ["dmg","fan"]
  "modifiers_picked": [],
  "gems_collected": 0,
  "pickups_collected": 0,

  // ── Pacing / feel ──────────────────────────────────────────────────────
  "time_to_first_kill_sec": 0.0,
  "time_to_first_levelup_sec": 0.0,
  "longest_idle_sec": 0.0,
  "camera_mode_switches": 0,

  // ── Raw event log (bounded) ────────────────────────────────────────────
  "events": []                           // last 400 events from analytics.mjs
}
```

**Units:** seconds, unitless counts, 0–1 fractions. No "ms", no percentages.
Games without e.g. a boss layer emit `0` for those fields — never omit the key,
or the aggregator's median/p25/p75 over sparse inputs becomes ambiguous.

## 2. Metric names available to GOALS.md

GOALS.md MUST only reference these names (verbatim). This set is the contract
between game-designer (who writes goals), bot author (who emits telemetry), and
analytics agent (who computes rollups):

```
session_duration_sec
levels_reached
score
accuracy
kills_per_min
damage_taken
dashes_used
stomps_used
xp_levels
upgrades_picked        (array; length or content)
gems_collected
pickups_collected
time_to_first_kill_sec
time_to_first_levelup_sec
longest_idle_sec
outcome                (enum)
```

Adding a metric is a contract change: extend both §1 and §2, bump
`schema_version` if you change field semantics, update `contract.py`, and
re-run the contract test.

## 3. Aggregates + file paths

**Aggregates** allowed in GOALS.md expressions (applied over the N runs of a
tag after dropping `outcome == "quit"`):

```
median
p25
p75
rate        # fraction of runs matching a condition, e.g. rate(levels_reached >= 2)
```

Example: `median(session_duration_sec) >= 180`, `rate(levels_reached >= 2) >= 0.40`.

**File paths** (per-artifact; `<repo>` is the game's artifact repo):

| Artifact | Path |
|---|---|
| Contract pointer | `<repo>/ITERATION_CONTRACT.md` (points at this doctrine) |
| Goals doc | `<repo>/GOALS.md` |
| Bot script | `<repo>/playtest_bot.mjs` |
| Telemetry dir | `<repo>/telemetry/` |
| Per-repo config | `<repo>/.codeplay/config.yaml` |
| Phase runbook | `code-play/docs/phases/iterate_artifact.md` |

## 4. Tone / length budget

- GOALS.md: ~40 lines. 5–7 targets, each with threshold + rationale + metric.
- playtest_bot.mjs: ~200 lines. Uses the same Playwright launch flags as the
  code-play-produced game (WebGL via SwiftShader on headless Chrome for Testing).
- Phase runbook: ~80 lines. Concrete enough for a code-play dev to wire up.

## 5. Non-goals (for this first cut)

- No per-player personalization. Bot is a single random-walk policy.
- No learning loop across runs. Each run is independent.
- No cross-artifact comparisons. Scope = one artifact repo per pipeline run.
