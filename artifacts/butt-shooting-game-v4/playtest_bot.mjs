// playtest_bot.mjs — headless random-walk bot that plays the live game and
// dumps one telemetry JSON per run matching ITERATION_CONTRACT.md §1.
//
// Usage:   node playtest_bot.mjs [--runs N] [--seconds S] [--tag v4.1]
// Env:     BSG_URL (default http://localhost:8765/index.html)
//
// COMPUTE LIMITATIONS:
// - `seed`: the bot does not feed a seed into the game (game RNG isn't seedable
//   from window.__game), so we emit the bot's own Math.random() seed stub (0)
//   purely for schema conformance. Treat as non-reproducible.
// - `hi_score_beaten`: computed by comparing score to game.hiScore captured at
//   run start (the snapshot before the hiScore is bumped at death/win).
// - `boss_hits` / `boss_kills`: derived from analytics events; counters aren't
//   exposed through window.__game.
// - `camera_mode_switches`: counted by filtering analytics events of type
//   'cameraMode' (emitted in game.mjs).
// - `modifiers_picked` / `upgrades_picked`: derived from analytics events
//   ('modifier' / 'upgrade'), ids in emission order.
// - `error` (non-schema): top-level field added only on crash paths, outcome
//   forced to "quit" — explicit deviation from the schema so failures surface.

// Playwright is located via $PLAYTEST_PLAYWRIGHT_MODULE (set by iterate_runner)
// with a fallback list of known-good paths so the bot also runs standalone.
import { mkdirSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { randomUUID } from 'crypto';
import { join } from 'path';

async function loadChromium() {
  const candidates = [
    process.env.PLAYTEST_PLAYWRIGHT_MODULE,
    '/Users/dknanlin/.claude/skills/digest/node_modules/playwright/index.mjs',
    '/Users/dknanlin/.claude/skills/email-digest/node_modules/playwright/index.mjs',
    'playwright',
  ].filter(Boolean);
  let lastErr;
  for (const spec of candidates) {
    try {
      if (spec.startsWith('/') && !existsSync(spec)) continue;
      const mod = await import(spec);
      if (mod.chromium) return mod.chromium;
    } catch (e) { lastErr = e; }
  }
  throw new Error(`Could not locate Playwright. Tried: ${candidates.join(', ')}. Last error: ${lastErr?.message || 'none'}`);
}
const chromium = await loadChromium();

// ─── CLI parse ────────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const out = { runs: 5, seconds: 60, tag: 'v4.1' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--runs')    out.runs    = parseInt(argv[++i], 10);
    else if (a === '--seconds') out.seconds = parseInt(argv[++i], 10);
    else if (a === '--tag')     out.tag     = String(argv[++i]);
  }
  return out;
}

const { runs, seconds, tag } = parseArgs(process.argv);
const URL = process.env.BSG_URL || 'http://localhost:8765/index.html';
// Write telemetry into the repo being tested. The iterate_runner sets cwd to
// the artifact repo path before spawning us, so "./telemetry" always lands in
// the correct per-artifact dir that load_telemetry_dir later reads.
const REPO = process.env.PLAYTEST_REPO || process.cwd();
const TEL_DIR = join(REPO, 'telemetry');
mkdirSync(TEL_DIR, { recursive: true });

// ─── tiny utils ───────────────────────────────────────────────────────────────
const rand = (min, max) => min + Math.random() * (max - min);
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ─── shared chrome launch (mirrors playtest_v4.mjs) ───────────────────────────
// CHROME_PATH is optional. If unset, Playwright uses its own bundled browser —
// which is the right default so we don't break whenever Playwright updates its
// pinned chromium version. Override via $PLAYTEST_CHROME_PATH only if you need
// a system Chrome (e.g., when running outside this repo's test harness).
const CHROME_PATH = process.env.PLAYTEST_CHROME_PATH || null;
const CHROME_ARGS = [
  '--use-gl=angle',
  '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader',
  '--enable-webgl',
  '--ignore-gpu-blocklist',
];

// favicon-404 filter (same semantics as playtest_v4.mjs)
function makeErrorFilter(badResources) {
  return (e) =>
    /favicon/.test(e) ||
    (/Failed to load resource.*404/.test(e) &&
     badResources.every(u => /favicon/.test(u)));
}

// ─── single run ───────────────────────────────────────────────────────────────
async function runOnce(browser, runIdx) {
  const runId = randomUUID().replace(/-/g, '').slice(0, 8);
  const startedAt = new Date();
  const startedAtIso = startedAt.toISOString();

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const badResources = [];
  page.on('response', r => { if (r.status() === 404) badResources.push(r.url()); });
  const isBenign = makeErrorFilter(badResources);

  const telemetry = {
    schema_version: 1,
    run_id: runId,
    started_at: startedAtIso,
    duration_sec: 0,
    outcome: 'quit',
    iteration_tag: tag,
    seed: 0,
    session_duration_sec: 0,
    levels_reached: 0,
    score: 0,
    hi_score_beaten: false,
    shots_fired: 0,
    shots_hit: 0,
    accuracy: 0,
    kills: 0,
    kills_per_min: 0,
    boss_hits: 0,
    boss_kills: 0,
    damage_taken: 0,
    times_hurt: 0,
    dashes_used: 0,
    stomps_used: 0,
    xp_gained: 0,
    xp_levels: 0,
    upgrades_picked: [],
    modifiers_picked: [],
    gems_collected: 0,
    pickups_collected: 0,
    time_to_first_kill_sec: 0,
    time_to_first_levelup_sec: 0,
    longest_idle_sec: 0,
    camera_mode_switches: 0,
    events: [],
  };
  let crashErr = null;
  let hiScoreAtStart = 0;
  const actionTimes = [];   // wall-clock seconds when bot issues any action
  let botStartMs = 0;       // ms when first input fired
  let playEndMs = 0;        // ms when run ended

  try {
    await page.goto(URL);
    // Wait for GameAPI to exist (module load), then start through the contract.
    await page.waitForFunction(() => !!window.GameAPI?.start, { timeout: 10_000 });
    await page.evaluate(() => window.GameAPI.start({ seed: 0 }));
    await page.waitForFunction(
      () => window.GameAPI.getState() === 'play',
      { timeout: 10_000 }
    );
    hiScoreAtStart = await page.evaluate(() => window.GameAPI.getSnapshot().hiScore | 0);

    const deadlineMs = Date.now() + seconds * 1000;
    botStartMs = Date.now();
    actionTimes.push(botStartMs);

    // Track keys currently held so we can release them cleanly at end.
    const held = new Set();
    let holdReleaseAt = 0;
    let shooting = false;
    let shootReleaseAt = 0;

    // Viewport for aim targets
    const VW = 1280, VH = 800;
    await page.mouse.move(VW / 2, VH / 2);

    // Main tick loop — 100ms cadence
    while (Date.now() < deadlineMs) {
      // GameAPI.getState() returns 'title'|'play'|'picker'|'win'|'gameover'.
      const state = await page.evaluate(() => window.GameAPI.getState());
      if (state === 'gameover' || state === 'win') break;

      // Picker handling: wait 300ms "reading", then pick a random card.
      if (state === 'picker') {
        await sleep(300);
        await page.evaluate(() => {
          const n = document.querySelectorAll('#pickerCards button').length || 1;
          window.GameAPI.pickCard(Math.floor(Math.random() * n));
        });
        actionTimes.push(Date.now());
        await sleep(120);
        continue;
      }

      // Release finished holds
      const now = Date.now();
      if (holdReleaseAt > 0 && now >= holdReleaseAt) {
        for (const k of held) await page.keyboard.up(k);
        held.clear();
        holdReleaseAt = 0;
      }
      if (shooting && now >= shootReleaseAt) {
        await page.mouse.up();
        shooting = false;
      }

      // Pick a random action on this tick
      // Weights: move 40, aim 25, shoot 20, dash 7, stomp 5, reload 3  (=100)
      const r = Math.random() * 100;
      if (r < 40) {
        // MOVE — hold one of WASD for 200-800ms, release any prior holds first
        if (held.size) {
          for (const k of held) await page.keyboard.up(k);
          held.clear();
        }
        const key = pick(['KeyW', 'KeyA', 'KeyS', 'KeyD']);
        await page.keyboard.down(key);
        held.add(key);
        holdReleaseAt = now + rand(200, 800);
      } else if (r < 65) {
        // AIM — snap mouse to random viewport spot
        await page.mouse.move(rand(40, VW - 40), rand(40, VH - 40));
      } else if (r < 85) {
        // SHOOT — mousedown for 100-400ms (skip if already shooting)
        if (!shooting) {
          await page.mouse.down();
          shooting = true;
          shootReleaseAt = now + rand(100, 400);
        }
      } else if (r < 92) {
        // DASH
        await page.keyboard.press('Shift');
      } else if (r < 97) {
        // STOMP
        await page.keyboard.press('KeyQ');
      } else {
        // RELOAD
        await page.keyboard.press('KeyR');
      }
      actionTimes.push(now);

      await sleep(100);
    }

    // Cleanup held inputs
    for (const k of held) await page.keyboard.up(k).catch(() => {});
    if (shooting) await page.mouse.up().catch(() => {});
    playEndMs = Date.now();

    // ── Snapshot game state via GameAPI ──────────────────────────────────────
    const snap = await page.evaluate(() => {
      if (!window.GameAPI?.getSnapshot) return null;
      return window.GameAPI.getSnapshot();
    });

    const finalState = snap?.state;
    telemetry.outcome =
      finalState === 'win'       ? 'win'
      : finalState === 'gameover' ? 'death'
      : 'timeout';
  } catch (e) {
    crashErr = e;
    telemetry.outcome = 'quit';
    telemetry.error = String(e && e.message ? e.message : e);
    playEndMs = Date.now();
  }

  // Grab a final snapshot even on error (best-effort, via GameAPI)
  let snap = null;
  try {
    snap = await page.evaluate(() =>
      window.GameAPI?.getSnapshot ? window.GameAPI.getSnapshot() : null
    );
  } catch {}

  // ── Fill telemetry ─────────────────────────────────────────────────────────
  const durSec = Math.max(0, (playEndMs - botStartMs) / 1000);
  telemetry.duration_sec = Math.round(durSec * 100) / 100;
  telemetry.session_duration_sec = telemetry.duration_sec;

  if (snap) {
    telemetry.score = snap.score;
    telemetry.levels_reached = snap.level?.idx ?? 0;
    telemetry.hi_score_beaten = snap.score > hiScoreAtStart;
    telemetry.shots_fired = snap.counters.shots | 0;
    telemetry.shots_hit   = snap.counters.hits  | 0;
    telemetry.accuracy    = telemetry.shots_fired > 0
      ? telemetry.shots_hit / telemetry.shots_fired
      : 0;
    telemetry.kills       = snap.counters.kills | 0;
    telemetry.kills_per_min = durSec > 0
      ? telemetry.kills / (durSec / 60)
      : 0;
    telemetry.boss_hits   = snap.counters.bossHits  | 0;
    telemetry.boss_kills  = snap.counters.bossKills | 0;
    telemetry.dashes_used = snap.counters.dashes    | 0;
    telemetry.stomps_used = (snap.events || []).filter(e => e.type === 'stomp').length;
    telemetry.pickups_collected = snap.counters.pickups | 0;
    telemetry.xp_levels   = Math.max(0, (snap.xp?.level ?? 1) - 1);
    telemetry.events = snap.events || [];
  }

  // Derived from events
  const evs = telemetry.events;
  // damage_taken + times_hurt
  let dmgTaken = 0, timesHurt = 0;
  // gems collected (count of 'gem' events)
  let gems = 0;
  // camera mode switches
  let camSwitches = 0;
  // upgrades / modifiers order
  const upgradesPicked = [];
  const modifiersPicked = [];
  // first kill / first levelup seconds
  let firstKillT = null, firstLevelupT = null;
  for (const e of evs) {
    if (e.type === 'hurt') {
      timesHurt += 1;
      if (typeof e.dmg === 'number') dmgTaken += e.dmg;
    } else if (e.type === 'gem') {
      gems += 1;
    } else if (e.type === 'cameraMode') {
      camSwitches += 1;
    } else if (e.type === 'upgrade' && e.id) {
      upgradesPicked.push(e.id);
    } else if (e.type === 'modifier' && e.id) {
      modifiersPicked.push(e.id);
    } else if (e.type === 'kill' && firstKillT == null) {
      firstKillT = e.t;
    } else if (e.type === 'levelUp' && firstLevelupT == null) {
      firstLevelupT = e.t;
    }
  }
  telemetry.damage_taken = dmgTaken;
  telemetry.times_hurt = timesHurt;
  telemetry.gems_collected = gems;
  telemetry.camera_mode_switches = camSwitches;
  telemetry.upgrades_picked = upgradesPicked;
  telemetry.modifiers_picked = modifiersPicked;
  telemetry.time_to_first_kill_sec = firstKillT ?? 0;
  telemetry.time_to_first_levelup_sec = firstLevelupT ?? 0;

  // xp_gained: sum of 'gained' on kill events (game.mjs emits kill with `gained`)
  let xpGained = 0;
  for (const e of evs) if (e.type === 'kill' && typeof e.gained === 'number') xpGained += e.gained;
  telemetry.xp_gained = xpGained;

  // longest_idle_sec: max gap between consecutive bot actions
  let longestIdle = 0;
  for (let i = 1; i < actionTimes.length; i++) {
    const gap = (actionTimes[i] - actionTimes[i - 1]) / 1000;
    if (gap > longestIdle) longestIdle = gap;
  }
  telemetry.longest_idle_sec = Math.round(longestIdle * 100) / 100;

  // ── Write file ─────────────────────────────────────────────────────────────
  const stampSafe = startedAtIso.replace(/[:.]/g, '-');
  const fname = `${stampSafe}-${runId}.json`;
  const fpath = join(TEL_DIR, fname);
  writeFileSync(fpath, JSON.stringify(telemetry, null, 2));

  // One-liner per run
  const lvDisplay = telemetry.levels_reached;
  console.log(
    `run ${runIdx + 1}/${runs}  dur=${Math.round(telemetry.duration_sec)}s  ` +
    `lv=${lvDisplay}  kills=${telemetry.kills}  score=${telemetry.score}  ` +
    `outcome=${telemetry.outcome}` +
    (crashErr ? `  err=${telemetry.error}` : '')
  );

  await ctx.close().catch(() => {});
  return fpath;
}

// ─── main ─────────────────────────────────────────────────────────────────────
const browser = await chromium.launch({
  headless: true,
  ...(CHROME_PATH ? { executablePath: CHROME_PATH } : {}),
  args: CHROME_ARGS,
});

const written = [];
const beforeCount = readdirSync(TEL_DIR).filter(f => f.endsWith('.json')).length;

try {
  for (let i = 0; i < runs; i++) {
    try {
      const fpath = await runOnce(browser, i);
      written.push(fpath);
    } catch (e) {
      // runOnce already writes a JSON on crash; defensive only.
      console.error(`run ${i + 1}/${runs} hard-crashed: ${e && e.message ? e.message : e}`);
    }
  }
} finally {
  await browser.close().catch(() => {});
}

const afterCount = readdirSync(TEL_DIR).filter(f => f.endsWith('.json')).length;
console.log(`WROTE ${afterCount - beforeCount} files to telemetry/`);
