// playtest_new_ideas.mjs — verify the three new ideas emit expected telemetry.
// Covers: warmup_dummies_fast_first_level, healthkit_breadcrumb_beacon, artist-idea-03.
import { chromium } from '/Users/dknanlin/.claude/skills/digest/node_modules/playwright/index.mjs';

const URL = process.env.BSG_URL || 'http://localhost:8765/index.html';
const results = [];
function pass(n) { results.push({ n, ok: true }); console.log('PASS', n); }
function fail(n, e) { results.push({ n, ok: false, e: String(e) }); console.error('FAIL', n, e); }

const browser = await chromium.launch({
  headless: true,
  executablePath: '/Users/dknanlin/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
});
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await ctx.newPage();
const errs = [];
page.on('pageerror', e => errs.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });

await page.goto(URL);
await page.waitForTimeout(1200);
await page.click('#startBtn');
await page.waitForTimeout(400);

// ─── warmup idea ─────────────────────────────────────────────────────────────
try {
  const warmupStart = await page.evaluate(() => {
    return window.__game.debug.warmupOn;
  });
  if (warmupStart) pass('warmup phase active on level 0'); else fail('warmup active', 'warmupOn=false');
} catch (e) { fail('warmup active', e); }

// Let warmup play out — sample dummy spawns + wait for end.
await page.waitForTimeout(11_500);
try {
  const info = await page.evaluate(() => {
    const events = window.__game.game.analytics.events;
    return {
      startEvt: events.find(e => e.type === 'spawn:warmup_start') || null,
      endEvt: events.find(e => e.type === 'spawn:warmup_end') || null,
      dummySpawned: events.filter(e => e.type === 'spawn:warmup_start').length,
    };
  });
  if (info.startEvt && info.endEvt) pass(`warmup emitted start+end (dummies=${info.endEvt.dummiesSpawned})`);
  else fail('warmup events', JSON.stringify(info));
} catch (e) { fail('warmup events', e); }

// ─── outfit idea ─────────────────────────────────────────────────────────────
try {
  // Spawn a bunch by fast-forwarding wave timer; then inspect outfitTier distribution.
  await page.evaluate(() => {
    for (let i = 0; i < 30; i++) window.__game.game.waveTimer = 0;
  });
  await page.waitForTimeout(400);
  const outfits = await page.evaluate(() => window.__game.debug.enemyOutfits);
  const hasVariety = outfits.length > 0;
  pass(`outfits applied (sample=${outfits.slice(0, 8).join(',')}, n=${outfits.length})`);
  if (!hasVariety) fail('outfits', 'no enemies sampled');
} catch (e) { fail('outfits', e); }

// ─── healthkit idea ──────────────────────────────────────────────────────────
try {
  // Revive + keep player alive & armed — warmup may have killed them.
  await page.evaluate(() => {
    const g = window.__game.game;
    g.enemies.length = 0;
    g.pickups.length = 0;
    g.healthKits.length = 0;
    g.healthKitPityArmed = false;
    if (g.state === 'gameover') {
      g.state = 'play';
    }
    g.player.hp = g.player.maxHp;
    g.player.iFrames = 999;
  });
  await page.waitForTimeout(100);
  // Force-spawn a kit via cadence path.
  await page.evaluate(() => { window.__game.game.healthKitSpawnCd = 0.1; });
  await page.waitForTimeout(400);
  const beforeKits = await page.evaluate(() => window.__game.debug.healthKits.length);
  if (beforeKits >= 1) pass(`healthkit spawned by cadence (kits=${beforeKits})`);
  else fail('healthkit spawn', `kits=${beforeKits}`);

  const spawnEvt = await page.evaluate(() => {
    return window.__game.game.analytics.events.find(e => e.type === 'healthkit:spawn') || null;
  });
  if (spawnEvt) pass(`healthkit:spawn emitted (source=${spawnEvt.source})`);
  else fail('healthkit:spawn evt', 'not found');

  // Walk onto the cadence kit while player is still at full HP — no pity race.
  const walkDbg = await page.evaluate(() => {
    const g = window.__game.game;
    g.enemies.length = 0;
    g.player.iFrames = 2;
    const kit = g.healthKits[0];
    const info = {
      hasKit: !!kit,
      inPickups: kit ? g.pickups.includes(kit) : false,
      kitPos: kit ? { x: +kit.x.toFixed(2), z: +kit.z.toFixed(2), life: +kit.life.toFixed(1) } : null,
      playerPosBefore: { x: +g.player.x.toFixed(2), z: +g.player.z.toFixed(2) },
      state: g.state,
      pickerOpen: g.picker && g.picker.isOpen ? g.picker.isOpen() : null,
    };
    if (kit) { g.player.x = kit.x; g.player.z = kit.z; }
    return info;
  });
  console.log('walk dbg:', JSON.stringify(walkDbg));
  await page.waitForTimeout(300);
  const postWalk = await page.evaluate(() => {
    const g = window.__game.game;
    return {
      pickupsN: g.pickups.length,
      kitsN: g.healthKits.length,
      playerPos: { x: +g.player.x.toFixed(2), z: +g.player.z.toFixed(2), hp: g.player.hp },
      state: g.state,
      recent: g.analytics.events.slice(-6).map(e => ({ t: +e.t.toFixed(1), type: e.type })),
    };
  });
  console.log('post walk:', JSON.stringify(postWalk));
  const pickupEvt = await page.evaluate(() => {
    return window.__game.game.analytics.events.find(e => e.type === 'healthkit:pickup') || null;
  });
  if (pickupEvt) pass(`healthkit:pickup emitted (hp=${pickupEvt.hp})`);
  else fail('healthkit:pickup', 'not seen — kit may still be on floor');

  // Pity path — drive HP below 30% and wait a tick for updateHealthKits to arm+fire.
  await page.evaluate(() => {
    const g = window.__game.game;
    g.healthKitPityArmed = false;
    g.player.hp = 20;
    g.player.iFrames = 999;
    g.enemies.length = 0;
  });
  await page.waitForTimeout(80);
  await page.evaluate(() => {
    const g = window.__game.game;
    g.player.hp = g.player.maxHp;
    g.enemies.length = 0;
  });
  const pityEvt = await page.evaluate(() => {
    return window.__game.game.analytics.events.find(e => e.type === 'pity:trigger') || null;
  });
  if (pityEvt) pass('pity:trigger emitted on low HP');
  else fail('pity evt', 'not found');
} catch (e) { fail('healthkit flow', e); }

const realErrs = errs.filter(e => !/favicon/.test(e) && !/404/.test(e));
if (realErrs.length === 0) pass('no page errors overall');
else fail('errors', realErrs.slice(0, 3).join(' | '));

await browser.close();
const p = results.filter(r => r.ok).length;
console.log(`\n${p}/${results.length} pass`);
if (p < results.length) {
  console.log('failures:', results.filter(r => !r.ok));
  process.exit(1);
}
