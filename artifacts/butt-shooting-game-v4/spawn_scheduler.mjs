// spawn_scheduler.mjs — warmup phase for level 0
//
// Idea: warmup_dummies_fast_first_level
// First ~10s of a fresh run spawn 3–5 low-HP "dummy" flushers at a brisk cadence
// so the player feels agency within the first few seconds instead of standing
// around waiting for the first wave timer to resolve. After the warmup budget
// is exhausted the scheduler hands control back to the normal wave loop.
//
// Public surface:
//   createSpawnScheduler({ analytics, emit })
//     .startWarmup(levelIdx)   // call from enterLevel/startLevel
//     .tick(dt, { spawn })     // call from updateGame each frame
//     .endWarmup(reason)       // force-end (picker, boss, death)
//     .isWarmup()              // boolean
//     .debug                   // { warmupOn, dummiesSpawned, secondsLeft }

export function createSpawnScheduler({ emit } = {}) {
  const cfg = {
    // Only warmup on the very first level of a run.
    activeLevels: new Set([0]),
    durationSec: 10,
    maxDummies: 5,
    minDummies: 3,
    // Warmup enemies are flushers with 1 HP — die in one pop, give player
    // a satisfying streak before real enemies ramp in.
    dummyKind: 'flusher',
    dummyHp: 1,
    dummyDamage: 6,
    spawnGapSec: 1.6,
  };

  const state = {
    warmupOn: false,
    secondsLeft: 0,
    spawnCd: 0,
    dummiesSpawned: 0,
    levelIdx: -1,
  };

  function startWarmup(levelIdx) {
    if (!cfg.activeLevels.has(levelIdx)) return false;
    state.warmupOn = true;
    state.secondsLeft = cfg.durationSec;
    state.spawnCd = 0.25; // brief grace so first dummy lands ~quarter second in
    state.dummiesSpawned = 0;
    state.levelIdx = levelIdx;
    emit && emit('spawn:warmup_start', {
      level: levelIdx,
      durationSec: cfg.durationSec,
      maxDummies: cfg.maxDummies,
    });
    return true;
  }

  function endWarmup(reason = 'timeout') {
    if (!state.warmupOn) return;
    state.warmupOn = false;
    state.secondsLeft = 0;
    state.spawnCd = 0;
    emit && emit('spawn:warmup_end', {
      level: state.levelIdx,
      reason,
      dummiesSpawned: state.dummiesSpawned,
    });
  }

  function tick(dt, hooks = {}) {
    if (!state.warmupOn) return;
    state.secondsLeft -= dt;
    state.spawnCd -= dt;

    const budgetLeft = cfg.maxDummies - state.dummiesSpawned;
    if (state.spawnCd <= 0 && budgetLeft > 0 && typeof hooks.spawn === 'function') {
      hooks.spawn({
        kind: cfg.dummyKind,
        hp: cfg.dummyHp,
        damage: cfg.dummyDamage,
        tag: 'warmup_dummy',
      });
      state.dummiesSpawned += 1;
      state.spawnCd = cfg.spawnGapSec;
    }

    const sawFloor = state.dummiesSpawned >= cfg.minDummies;
    if (state.secondsLeft <= 0 && sawFloor) endWarmup('timeout');
    else if (state.dummiesSpawned >= cfg.maxDummies && state.secondsLeft <= 0) endWarmup('cap');
  }

  return {
    startWarmup,
    endWarmup,
    tick,
    isWarmup: () => state.warmupOn,
    get debug() {
      return {
        warmupOn: state.warmupOn,
        dummiesSpawned: state.dummiesSpawned,
        secondsLeft: Math.max(0, state.secondsLeft),
      };
    },
  };
}
