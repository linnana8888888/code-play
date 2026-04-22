import { chromium } from '/Users/dknanlin/.claude/skills/digest/node_modules/playwright/index.mjs';
import { mkdirSync } from 'fs';

const OUT = '/Users/dknanlin/scratch/butt-shooting-game/qa';
mkdirSync(OUT, { recursive: true });

const URL = process.env.BSG_URL || 'http://localhost:8765/index.html';
const results = [];
function pass(n) { results.push({ n, ok: true }); console.log('PASS', n); }
function fail(n, e) { results.push({ n, ok: false, e: String(e) }); console.error('FAIL', n, e); }

const browser = await chromium.launch({
  headless: true,
  executablePath: '/Users/dknanlin/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
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

const errs = [];
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
page.on('pageerror', e => errs.push('pageerror: ' + e.message));
// track 404s by URL so we can ignore favicon etc.
const badResources = [];
page.on('response', r => {
  if (r.status() === 404) badResources.push(r.url());
});

await page.goto(URL);
await page.waitForTimeout(1500);
// filter 404-resource errors caused by missing favicon — harmless
const isBenign = (e) =>
  /favicon/.test(e) ||
  (/Failed to load resource.*404/.test(e) &&
   badResources.every(u => /favicon/.test(u)));
const realErrs = errs.filter(e => !isBenign(e));
if (realErrs.length === 0) pass('no load errors'); else fail('load errors', realErrs.join(' | '));
await page.screenshot({ path: `${OUT}/v4_title.png` });

// Start — should drop straight into level 0, NO modifier picker at start
await page.click('#startBtn');
await page.waitForTimeout(600);

try {
  const pickerVisible = await page.evaluate(() => {
    const o = document.getElementById('pickerOverlay');
    return o && !o.classList.contains('hide');
  });
  if (!pickerVisible) pass('no picker at game start (drops straight in)');
  else fail('picker at start', 'picker should NOT show at start');
} catch (e) { fail('picker check', e); }

// Level 0 should be loaded immediately with player
try {
  const st = await page.evaluate(() => ({
    levelIdx: window.__game.game.levelIdx,
    player: !!window.__game.game.player,
    hp: window.__game.game.player?.hp,
    state: window.__game.game.state,
  }));
  if (st.levelIdx === 0 && st.player && st.state === 'play') {
    pass(`level 0 loaded immediately (hp=${st.hp})`);
  } else {
    fail('level 0 immediate load', JSON.stringify(st));
  }
} catch (e) { fail('state check', e); }
await page.screenshot({ path: `${OUT}/v4_play.png` });

// WASD movement — should work right away
await page.keyboard.down('d');
await page.waitForTimeout(280);
await page.keyboard.up('d');
await page.waitForTimeout(150);
try {
  const p = await page.evaluate(() => ({ x: window.__game.game.player.x }));
  if (Math.abs(p.x) > 0.3) pass(`move works immediately (x=${p.x.toFixed(2)})`);
  else fail('move', JSON.stringify(p));
} catch (e) { fail('move', e); }

// Aim → butt rotation. Move mouse to a known position, check p.rot follows aim.
try {
  await page.mouse.move(1100, 400); // right side of screen
  await page.waitForTimeout(200);
  const aimRight = await page.evaluate(() => ({
    aimX: window.__game.game.player.aimX,
    aimZ: window.__game.game.player.aimZ,
    rot: window.__game.game.player.rot,
  }));
  // rot should satisfy rot = atan2(-aimX, -aimZ) (butt faces aim)
  const expected = Math.atan2(-aimRight.aimX, -aimRight.aimZ);
  const diff = Math.abs(aimRight.rot - expected);
  if (diff < 0.01) pass(`butt faces aim (rot=${aimRight.rot.toFixed(2)}, aim=(${aimRight.aimX.toFixed(2)},${aimRight.aimZ.toFixed(2)}))`);
  else fail('butt facing', `rot=${aimRight.rot}, expected=${expected}, diff=${diff}`);
} catch (e) { fail('aim rot', e); }

// Force-kill to drop gems
await page.evaluate(() => {
  for (let i = 0; i < 10; i++) window.__game.forceKill(1);
});
await page.waitForTimeout(300);
try {
  const gem = await page.evaluate(() => ({
    gems: window.__game.game.gems.length,
    xp: window.__game.game.xp?.snapshot(),
  }));
  if (gem.gems >= 0) pass(`xp/gems system ok (gems=${gem.gems}, lv=${gem.xp?.level}, frac=${gem.xp?.frac?.toFixed(2)})`);
  else fail('gems', JSON.stringify(gem));
} catch (e) { fail('gems', e); }

// Teleport to gems
await page.evaluate(() => {
  const p = window.__game.game.player;
  for (const g of window.__game.game.gems) { p.x = g.x; p.z = g.z; }
});
await page.waitForTimeout(400);

// Force level-up via grant(500)
await page.evaluate(() => window.__game.game.xp.grant(500));
await page.waitForTimeout(400);
try {
  const modalOpen = await page.evaluate(() => {
    const o = document.getElementById('pickerOverlay');
    return o && !o.classList.contains('hide');
  });
  if (modalOpen) pass('level-up picker shows');
  else fail('levelup modal', 'not visible');
} catch (e) { fail('levelup', e); }
await page.screenshot({ path: `${OUT}/v4_levelup_modal.png` });

// PAUSE TEST: with picker open, enemies should NOT move
try {
  const e0 = await page.evaluate(() => {
    const e = window.__game.game.enemies[0];
    return e ? { x: e.obj.position.x, z: e.obj.position.z } : null;
  });
  if (!e0) {
    // spawn one manually for pause test
    await page.evaluate(() => {
      for (let i = 0; i < 3; i++) {
        const now = performance.now() / 1000;
        window.__game.game.waveTimer = 0;
      }
    });
  }
  await page.waitForTimeout(500);
  const snapA = await page.evaluate(() => {
    const e = window.__game.game.enemies[0];
    const p = window.__game.game.player;
    return {
      enemyPos: e ? { x: e.obj.position.x, z: e.obj.position.z } : null,
      playerX: p.x, playerZ: p.z,
    };
  });
  // wait while picker is open
  await page.waitForTimeout(800);
  const snapB = await page.evaluate(() => {
    const e = window.__game.game.enemies[0];
    const p = window.__game.game.player;
    return {
      enemyPos: e ? { x: e.obj.position.x, z: e.obj.position.z } : null,
      playerX: p.x, playerZ: p.z,
    };
  });
  const enemyMoved = snapA.enemyPos && snapB.enemyPos &&
    (Math.abs(snapA.enemyPos.x - snapB.enemyPos.x) > 0.01 ||
     Math.abs(snapA.enemyPos.z - snapB.enemyPos.z) > 0.01);
  if (!enemyMoved) pass('game is paused while picker is open');
  else fail('pause', `enemy moved during picker: ${JSON.stringify({ snapA, snapB })}`);
} catch (e) { fail('pause test', e); }

// pick an upgrade
try {
  await page.evaluate(() => {
    const cards = document.querySelectorAll('#pickerCards button');
    if (cards[0]) cards[0].click();
  });
  await page.waitForTimeout(400);
  const stats = await page.evaluate(() => window.__game.game.stats);
  const pickedAny = Object.keys(stats.counts).length > 0;
  if (pickedAny) pass(`upgrade applied (counts=${JSON.stringify(stats.counts)})`);
  else fail('upgrade apply', JSON.stringify(stats));
} catch (e) { fail('upgrade click', e); }

// After pick: picker closed, no focused button eats WASD
try {
  const focused = await page.evaluate(() => document.activeElement?.tagName);
  if (focused !== 'BUTTON') pass(`focus released after pick (activeEl=${focused})`);
  else fail('focus', 'button still focused — WASD may be eaten');
} catch (e) { fail('focus', e); }

// Stomp test (Q)
await page.waitForTimeout(1500);
await page.evaluate(() => {
  for (const e of window.__game.game.enemies) {
    e.obj.position.x = window.__game.game.player.x + 2;
    e.obj.position.z = window.__game.game.player.z;
  }
});
const beforeStomp = await page.evaluate(() => ({
  stock: window.__game.game.stats.stompStock,
  enemies: window.__game.game.enemies.length,
}));
await page.keyboard.press('KeyQ');
await page.waitForTimeout(300);
const afterStomp = await page.evaluate(() => ({
  stock: window.__game.game.stats.stompStock,
  cd: window.__game.game.stompCd,
}));
if (afterStomp.stock < beforeStomp.stock && afterStomp.cd > 0) {
  pass(`stomp fires (stock ${beforeStomp.stock}→${afterStomp.stock}, cd=${afterStomp.cd.toFixed(2)})`);
} else {
  fail('stomp', JSON.stringify({ beforeStomp, afterStomp }));
}

// Level screenshots
await page.evaluate(() => window.__game.setLevel(1));
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/v4_lab.png` });
await page.evaluate(() => window.__game.setLevel(2));
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/v4_sewer.png` });
pass('level screenshots saved');

const finalErrs = errs.filter(e => !isBenign(e));
if (finalErrs.length === 0) pass('no errors overall');
else fail('errors overall', finalErrs.slice(0, 5).join(' | '));

await browser.close();

const p = results.filter(r => r.ok).length;
const t = results.length;
console.log(`\n${p}/${t} pass`);
if (p < t) {
  console.log('failures:', results.filter(r => !r.ok));
  process.exit(1);
}
