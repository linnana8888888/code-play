# GOALS — butt-shooting-game iteration targets

Metric names are verbatim from `ITERATION_CONTRACT.md` §2. Aggregates wrap
those names in `median()`, `p25()`, `p75()`, or `rate()` (fraction of runs
matching a condition). Do not introduce names outside the contract — flag
them under "Open additions" instead.

## How to compute over N runs

The postmortem agent loads all `telemetry/*.json` with `iteration_tag` matching
the current version, filters to `outcome in {"win","death","timeout"}` (drop
`"quit"` — bot crash, not a play signal), and computes each aggregate across
that filtered set. N ≥ 5 runs per tag before a target is considered meaningful;
below that, report "insufficient sample" rather than a pass/fail verdict.

## Targets

1. **Session length (engagement)**
   - Threshold: `median(session_duration_sec) >= 180`
   - Rationale: a run under 3 minutes is over before the upgrade loop gets interesting; median anchors the typical experience against outlier wins/early deaths.

2. **Skill expression (accuracy band)**
   - Threshold: `p25(accuracy) >= 0.25 AND p75(accuracy) <= 0.75`
   - Rationale: if the bottom quartile can't crack 25% the game punishes whiffs too hard; if the top quartile exceeds 75% aim barely matters — the band keeps shooting a skill.

3. **Progression reach (late game visible)**
   - Threshold: `rate(levels_reached >= 2) >= 0.40`
   - Rationale: at least 40% of runs should see the Sewer Depths / boss layer, otherwise the content after Porcelain Lab is dead weight nobody experiences.

4. **Feature usage (dashes + stomps earn their keys)**
   - Threshold: `median(dashes_used) >= 3 AND median(stomps_used) >= 1`
   - Rationale: a mechanic the median run never touches is UI noise; these floors confirm both movement tools get exercised without mandating spam.

5. **Early hook (time to first kill)**
   - Threshold: `median(time_to_first_kill_sec) <= 15 AND p75(time_to_first_kill_sec) <= 25`
   - Rationale: the first dopamine hit has to land fast; the p75 ceiling guards against a long tail of silent, enemy-less openings post-grace-timer.

6. **Upgrade diversity (no single dominant pick)**
   - Threshold: for every upgrade id appearing in any run, `rate(id in upgrades_picked) <= 0.80` and `rate(id in upgrades_picked) >= 0.15` for ids that appeared at all
   - Rationale: computed from the `upgrades_picked` array; if one id shows in >80% of runs it's a trap pick, if any appearing id shows in <15% it's been priced out of relevance.

## Open additions

None. All six targets are expressible with names already in the contract.
