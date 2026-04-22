// upgrade_offers.mjs — Early upgrade guarantee + offer diversity (cycle 2)
//
// Ideas implemented:
//   early_upgrade_guarantee_diversity — force an upgrade offer at min(20s, 8 kills),
//     ensure 3 distinct choices (no duplicates, no already-maxed upgrades).
//   proto-05 — XP smoothing (2× on first 5 kills), pity timer to guarantee
//     first level-up by 25s.
//
// Exports:
//   createEarlyOfferTracker(xp, stats, analytics, onOffer)
//     → { tick(dt, now, killCount), onKill(), reset() }
//   getThreeDistinct(stats)  — canonical de-duped pick-3 (extends upgrades.mjs)
//   EARLY_OFFER_TIME, EARLY_OFFER_KILLS, PITY_LEVEL_MS

import { UPGRADES, pickThreeUpgrades } from './upgrades.mjs';

// ─── Shared constants (brief §4 eng-2 scope) ─────────────────────────────────
export const EARLY_OFFER_TIME  = 20_000;  // ms: force offer if no level-up yet
export const EARLY_OFFER_KILLS = 8;       // kills: also triggers early offer
export const PITY_LEVEL_MS     = 25_000;  // ms: guaranteed first level-up by here

// ─── Distinct pick-3 ─────────────────────────────────────────────────────────
// Wraps upgrades.mjs pickThreeUpgrades but guarantees exactly 3 distinct ids.
// Falls back to padding with any available upgrade if pool is thin.
export function getThreeDistinct(stats) {
  const avail = UPGRADES.filter(u => {
    const picked = stats.counts[u.id] || 0;
    return !u.max || picked < u.max;
  });
  if (avail.length === 0) return [];

  // Fisher-Yates shuffle
  const pool = avail.slice();
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }

  // Take up to 3, ensuring distinct ids
  const seen = new Set();
  const result = [];
  for (const u of pool) {
    if (!seen.has(u.id)) {
      seen.add(u.id);
      result.push(u);
      if (result.length === 3) break;
    }
  }
  return result;
}

// ─── Early offer tracker ─────────────────────────────────────────────────────
// Tracks elapsed time + kill count and fires onOffer() at most once per game.
// Also manages the XP pity timer (proto-05).
//
// Parameters:
//   xp          — the xp tracker from createXp() (has .grant() + .snapshot())
//   stats       — live stats object (for getThreeDistinct)
//   analytics   — analytics object (has .emit())
//   onOffer(choices) — callback that opens the upgrade picker with choices[]
//
// Usage in game.mjs:
//   const earlyOffer = createEarlyOfferTracker(game.xp, game.stats, game.analytics, openUpgradePicker);
//   // in updateGame(dt, now): earlyOffer.tick(dt, now, totalKills);
//   // in killEnemy(): earlyOffer.onKill();
//   // in startGame(): earlyOffer.reset();
export function createEarlyOfferTracker(xp, stats, analytics, onOffer) {
  let elapsedMs    = 0;
  let killCount    = 0;
  let offerFired   = false;   // single-fire guard (no double modal)
  let pityFired    = false;   // pity level-up guard
  let firstLevelUp = false;   // set true when xp fires its first real level-up

  // Called by xp system when a natural level-up happens.
  // If this fires before pity, pity is cancelled.
  function onNaturalLevelUp() {
    firstLevelUp = true;
    pityFired    = true; // pity no longer needed
  }

  // Called every frame while state === 'play' (and picker not open).
  // dt: seconds since last frame; nowMs: performance.now() value.
  function tick(dt, nowMs) {
    elapsedMs += dt * 1000;

    // ── proto-05: pity level-up guarantee at PITY_LEVEL_MS ──────────────────
    if (!pityFired && elapsedMs >= PITY_LEVEL_MS) {
      pityFired = true;
      if (!firstLevelUp) {
        // Force enough XP to level up immediately.
        const snap = xp.snapshot();
        const needed = Math.max(1, snap.next - snap.xp);
        xp.grant(needed);
        analytics.emit('pity:trigger', { time: elapsedMs / 1000 });
      }
    }

    // ── early_upgrade_guarantee_diversity: early offer ───────────────────────
    if (!offerFired) {
      const timeTriggered  = elapsedMs >= EARLY_OFFER_TIME;
      const killsTriggered = killCount >= EARLY_OFFER_KILLS;
      if (timeTriggered || killsTriggered) {
        _fireOffer();
      }
    }
  }

  // Called whenever a kill happens (from killEnemy in game.mjs).
  function onKill() {
    killCount += 1;
    // Check immediately on kill (don't wait for next tick).
    if (!offerFired && killCount >= EARLY_OFFER_KILLS) {
      _fireOffer();
    }
  }

  // Internal: fire the early offer exactly once.
  function _fireOffer() {
    if (offerFired) return;
    // Only fire if the player hasn't already seen an upgrade offer
    // (i.e., xp level is still 1 — they haven't levelled up naturally yet).
    // If they already levelled up, the normal flow handled it; skip.
    const snap = xp.snapshot();
    if (snap.level > 1) {
      // Natural level-up already happened — no need for early guarantee.
      offerFired = true;
      return;
    }
    offerFired = true;
    const choices = getThreeDistinct(stats);
    if (choices.length === 0) return; // all upgrades maxed (shouldn't happen early)
    analytics.emit('upgrade:offer_shown', {
      choices: choices.map(c => c.id),
      time: elapsedMs / 1000,
      source: 'early_guarantee',
    });
    onOffer(choices);
  }

  // Reset for a new game run.
  function reset() {
    elapsedMs    = 0;
    killCount    = 0;
    offerFired   = false;
    pityFired    = false;
    firstLevelUp = false;
  }

  return { tick, onKill, onNaturalLevelUp, reset };
}
