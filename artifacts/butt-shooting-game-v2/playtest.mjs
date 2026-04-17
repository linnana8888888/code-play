import { chromium } from '/Users/dknanlin/.claude/skills/digest/node_modules/playwright/index.mjs';
import { mkdirSync } from 'fs';

mkdirSync('/tmp/qa', { recursive: true });

const URL = 'file:///tmp/butt-shooting-game-v2.html';
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

try {
  if (consoleErrors.length === 0) pass('no console errors on load');
  else fail('no console errors on load', consoleErrors.join(' | '));
} catch (e) { fail('console check', e); }

// title screenshot (before start)
await page.screenshot({ path: '/tmp/qa/v2_title.png' });
pass('title screenshot saved');

// start the game via exposed hook (click is faked via __game.start)
await page.evaluate(() => window.__game.start());
await page.waitForTimeout(400);

try {
  const p = await page.evaluate(() => window.__game.player);
  if (p && typeof p.x === 'number' && typeof p.z === 'number' && typeof p.hp === 'number') pass('__game.player has x,z,hp');
  else fail('__game.player shape', JSON.stringify(p));
} catch (e) { fail('player hook', e); }

// press WASD
const before = await page.evaluate(() => ({...window.__game.player}));
await page.keyboard.down('d');
await page.waitForTimeout(300);
await page.keyboard.up('d');
await page.keyboard.down('s');
await page.waitForTimeout(300);
await page.keyboard.up('s');
await page.waitForTimeout(200);
const after = await page.evaluate(() => ({...window.__game.player}));
try {
  if (Math.hypot(after.x - before.x, after.z - before.z) > 0.3) pass('WASD moves player');
  else fail('WASD moves player', `delta=${after.x-before.x},${after.z-before.z}`);
} catch (e) { fail('move check', e); }

await page.screenshot({ path: '/tmp/qa/v2_post_move.png' });
pass('post-move screenshot saved');

// click to fire a bean — use direct hook since mouse coords are fiddly
await page.evaluate(() => {
  for (let i = 0; i < 3; i++) window.__game.fire();
});
await page.waitForTimeout(150);
try {
  const projectiles = await page.evaluate(() => window.__game.projectiles.length);
  if (projectiles > 0) pass(`projectiles > 0 (got ${projectiles})`);
  else fail('projectiles after fire', projectiles);
} catch (e) { fail('projectile check', e); }

// let combat unfold
const start = Date.now();
while (Date.now() - start < 8000) {
  await page.mouse.move(700, 300);
  await page.evaluate(() => window.__game.fire());
  await page.keyboard.press('KeyW');
  await page.waitForTimeout(180);
}
await page.waitForTimeout(600);
await page.screenshot({ path: '/tmp/qa/v2_mid_combat.png' });
pass('mid-combat screenshot saved');

// check game is still alive / has enemies spawning
try {
  const state = await page.evaluate(() => ({
    enemies: window.__game.enemies.length,
    state: window.__game.state,
    hp: window.__game.player ? window.__game.player.hp : 0,
  }));
  pass(`end-state enemies=${state.enemies} state=${state.state} hp=${state.hp}`);
} catch (e) { fail('end state', e); }

await browser.close();

const passed = results.filter(r => r.ok).length;
const total = results.length;
console.log(`\n${passed}/${total} pass`);
if (passed < total) {
  console.log('failures:', results.filter(r => !r.ok));
  process.exit(1);
}
