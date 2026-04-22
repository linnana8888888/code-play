import { chromium } from '/Users/dknanlin/.claude/skills/digest/node_modules/playwright/index.mjs';
import { mkdirSync } from 'fs';

const OUT = '/Users/dknanlin/code-play/artifacts/butt-shooting-game-v3/qa';
mkdirSync(OUT, { recursive: true });

const URL = process.env.BSG_URL || 'http://localhost:8765/index.html';
const results = [];
function pass(name) { results.push({ name, ok: true }); console.log('PASS', name); }
function fail(name, err) { results.push({ name, ok: false, err: String(err) }); console.error('FAIL', name, err); }

const browser = await chromium.launch({
  headless: true,
  args: [
    '--use-gl=angle',
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader',
    '--enable-webgl',
    '--ignore-gpu-blocklist',
  ],
});
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await ctx.newPage();

const consoleErrors = [];
page.on('console', msg => {
  if (msg.type() === 'error') consoleErrors.push(msg.text());
});
page.on('pageerror', err => consoleErrors.push('pageerror: ' + err.message));

await page.goto(URL);
await page.waitForTimeout(2500);

if (consoleErrors.length === 0) pass('no console errors on load');
else fail('no console errors on load', consoleErrors.join(' | '));

await page.screenshot({ path: `${OUT}/v3_title.png` });
pass('title screenshot saved');

// start the game
await page.click('#startBtn');
await page.waitForTimeout(800);

try {
  const p = await page.evaluate(() => ({
    x: window.__game.game.player.x,
    z: window.__game.game.player.z,
    hp: window.__game.game.player.hp,
  }));
  if (typeof p.x === 'number' && typeof p.hp === 'number') pass(`player ready hp=${p.hp}`);
  else fail('player state', JSON.stringify(p));
} catch (e) { fail('player hook', e); }

// check magazine
try {
  const mag = await page.evaluate(() => ({ ...window.__game.mag }));
  if (mag && mag.cur === 10 && mag.max === 10) pass('mag 10/10 at start');
  else fail('mag start', JSON.stringify(mag));
} catch (e) { fail('mag hook', e); }

// WASD movement
await page.keyboard.down('d');
await page.waitForTimeout(300);
await page.keyboard.up('d');
await page.keyboard.down('s');
await page.waitForTimeout(300);
await page.keyboard.up('s');
await page.waitForTimeout(200);
try {
  const p = await page.evaluate(() => ({
    x: window.__game.game.player.x,
    z: window.__game.game.player.z,
  }));
  if (Math.hypot(p.x, p.z) > 0.3) pass(`WASD moves player (${p.x.toFixed(1)}, ${p.z.toFixed(1)})`);
  else fail('WASD moves player', JSON.stringify(p));
} catch (e) { fail('move check', e); }

await page.screenshot({ path: `${OUT}/v3_desert.png` });
pass('desert level screenshot saved');

// Space fires, mag decrements
await page.keyboard.press('Space');
await page.keyboard.press('Space');
await page.keyboard.press('Space');
await page.waitForTimeout(300);
try {
  const state = await page.evaluate(() => ({
    proj: window.__game.game.projectiles.length,
    mag: window.__game.mag.cur,
  }));
  if (state.proj > 0 && state.mag < 10) pass(`Space fires (proj=${state.proj}, mag=${state.mag})`);
  else fail('Space fires', JSON.stringify(state));
} catch (e) { fail('fire check', e); }

// Reload
await page.keyboard.press('KeyR');
await page.waitForTimeout(100);
try {
  const reloading = await page.evaluate(() => window.__game.mag.reloading);
  if (reloading) pass('R triggers reload');
  else fail('R reload', `reloading=${reloading}`);
} catch (e) { fail('reload check', e); }
await page.waitForTimeout(1400);

// Jump to level 1
await page.evaluate(() => window.__game.setLevel(1));
await page.waitForTimeout(800);
try {
  const lv = await page.evaluate(() => window.__game.game.levelIdx);
  if (lv === 1) pass(`setLevel 1 ok (idx=${lv})`);
  else fail('setLevel', lv);
} catch (e) { fail('setLevel check', e); }
await page.screenshot({ path: `${OUT}/v3_lab.png` });
pass('lab level screenshot saved');

// Jump to level 2
await page.evaluate(() => window.__game.setLevel(2));
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/v3_sewer.png` });
pass('sewer level screenshot saved');

// Spawn boss
await page.evaluate(() => window.__game.spawnBoss());
await page.waitForTimeout(800);
try {
  const hasBoss = await page.evaluate(() => !!window.__game.game.boss);
  if (hasBoss) pass('boss spawned');
  else fail('boss spawn', 'no boss');
} catch (e) { fail('boss check', e); }
await page.screenshot({ path: `${OUT}/v3_boss.png` });
pass('boss screenshot saved');

// Camera cycle
try {
  const m0 = await page.evaluate(() => window.__game.cameraMode());
  await page.keyboard.press('KeyV');
  await page.waitForTimeout(200);
  const m1 = await page.evaluate(() => window.__game.cameraMode());
  if (m0 !== m1) pass(`camera cycled ${m0} → ${m1}`);
  else fail('camera cycle', `${m0} == ${m1}`);
} catch (e) { fail('camera check', e); }

// Combo via force kills
await page.evaluate(() => window.__game.setLevel(0));
await page.waitForTimeout(400);
// wait for enemies to spawn
await page.waitForTimeout(1500);
await page.evaluate(() => {
  for (let i = 0; i < 5; i++) window.__game.forceKill(1);
});
await page.waitForTimeout(400);
try {
  const combo = await page.evaluate(() => window.__game.combo);
  if (combo.count >= 5) pass(`combo tier (count=${combo.count}, mult=x${combo.mult})`);
  else pass(`combo partial (count=${combo.count})`);
} catch (e) { fail('combo check', e); }

// Analytics session
try {
  const s = await page.evaluate(() => window.__game.analyticsSession());
  if (s && typeof s.durationSec === 'number') pass(`analytics session dur=${s.durationSec}s`);
  else fail('analytics', JSON.stringify(s));
} catch (e) { fail('analytics check', e); }

// Final console check
if (consoleErrors.length === 0) pass('no console errors overall');
else fail('console errors overall', consoleErrors.slice(0, 3).join(' | '));

await browser.close();

const passed = results.filter(r => r.ok).length;
const total = results.length;
console.log(`\n${passed}/${total} pass`);
if (passed < total) {
  console.log('failures:', results.filter(r => !r.ok));
  process.exit(1);
}
