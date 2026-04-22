# v3 Module Contracts

Single-file v2 split into ES modules. Agents implement isolated modules against the contracts below. Integration done by the coordinator.

## Shared conventions

- Browser-native ES modules. Load order from `index.html`:
  ```html
  <script type="importmap">
    { "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js" } }
  </script>
  <script type="module" src="./game.mjs"></script>
  ```
- No bundler. Keep code runnable from `file://` (with note that FPS pointer-lock prefers localhost).
- One shared palette `C` lives in `game.mjs` and is passed into modules via `ctx`.
- Shared `ctx` object (passed to scenes/juice):
  ```js
  ctx = {
    THREE,                 // the three namespace
    C,                     // palette (object of hex numbers, see below)
    ARENA: 32,             // half-arena radius
    toon(color, opts),     // factory for MeshLambertMaterial
    withOutline(mesh, t),  // adds ink BackSide outline
    blobShadow(size),      // ground shadow disc
    scene,                 // THREE.Scene
  };
  ```
- Palette `C` (reuse v2):
  ```js
  const C = {
    peach:0xF5B08A, cleft:0xC77A5A, blush:0xFF7B7B,
    beanGold:0xE8B84D, beanDark:0x6B3410,
    cream:0xFFF4D6, rival:0xE85C4A,
    windy:0x9DD96A, windyDark:0x6FA63E,
    impact:0xFF5FA2, sand:0xE8D7A8, sky:0x7FC4E0,
    ink:0x2A1A0E, porcelain:0xF0EDE5, water:0x5AC8E8,
    rock:0xAA8A66, cactus:0x6FA658,
    // new v3 additions
    tile:0xF0EDE5, pipe:0xB8B2A8, chrome:0xDCDCDC,
    sewerGreen:0x3A5548, sewerDark:0x1A2E22, slime:0x6FA63E,
    bossRed:0xA63E3E, gold:0xFFD24D,
  };
  ```

## `audio.mjs` — Agent A

WebAudio only. Unlocks on first `init()` call (called from a user-gesture handler in game.mjs).

```js
export const sfx = {
  init(),                // create AudioContext, nodes, load mute state
  shot(), impact(), reload(), dash(), hurt(),
  pickup(), levelUp(), waveStart(), death(),
  comboTier(n),          // rising bell, n = tier count (1,2,3...)
  startMusic(levelIdx),  // 0/1/2; loop procedural chord/bass pattern
  stopMusic(),
  setMuted(bool),
  isMuted(),             // reads from instance state
};
```

Design notes:
- Use oscillators + BiquadFilter + GainNode envelopes. Square/saw/sine/noise buffer.
- Short FX (< 400ms). Master gain around 0.25; music gain around 0.08 so it sits behind SFX.
- Music loop: three different chord progressions (bright/clean/dark), one per level. Chord change every 8 bars at ~110-130 bpm. Two-oscillator pad + noisy kick on beat 1 (optional), simple bass pattern.
- Persist mute to `localStorage['bsg_mute']` on `setMuted`. Read on `init`.

## `scenes.mjs` — Agent B

Declarative levels + environment swap.

```js
export const LEVELS = [
  {
    id: 0, name: 'Desert Dunes', kills: 20,
    sky: 0x7FC4E0, floor: 0xE8D7A8, ring: 0xC7B383,
    fog: [0x7FC4E0, 45, 85],                 // color, near, far
    hemiTop: 0xFFF4D6, hemiBot: 0xE8D7A8, hemiI: 0.55,
    sunColor: 0xFFFFFF, sunI: 0.95,
    props: ['cactus', 'rock'],                // buildProp kinds
    propCount: 22,
    enemyMix: [
      { kind: 'flusher',  weight: 0.45 },
      { kind: 'buttling', weight: 0.40 },
      { kind: 'windy',    weight: 0.15 },
    ],
    musicIdx: 0,
  },
  {
    id: 1, name: 'Porcelain Lab', kills: 30,
    sky: 0xE8F4F8, floor: 0xF0EDE5, ring: 0xD8D2C8,
    fog: [0xE8F4F8, 40, 75],
    hemiTop: 0xFFFFFF, hemiBot: 0xE8F4F8, hemiI: 0.65,
    sunColor: 0xFFFFFF, sunI: 0.85,
    props: ['toilet', 'pipe', 'tile'],
    propCount: 28,
    enemyMix: [
      { kind: 'flusher',      weight: 0.35 },
      { kind: 'buttling',     weight: 0.35 },
      { kind: 'toiletGolem',  weight: 0.30 },
    ],
    musicIdx: 1,
  },
  {
    id: 2, name: 'Sewer Depths', kills: 40,
    sky: 0x2D4A3E, floor: 0x3A5548, ring: 0x223028,
    fog: [0x1A2E22, 30, 60],
    hemiTop: 0x6FA63E, hemiBot: 0x1A2E22, hemiI: 0.4,
    sunColor: 0x9DD96A, sunI: 0.5,
    props: ['pipe', 'grate', 'puddle'],
    propCount: 26,
    enemyMix: [
      { kind: 'buttling',  weight: 0.35 },
      { kind: 'windy',     weight: 0.25 },
      { kind: 'sewerRat',  weight: 0.40 },
    ],
    musicIdx: 2,
    boss: 'clog_king',
  },
];

/** Remove old level contents, apply a new level config. Returns new {propRoot, hemi, sun}. */
export function applyLevel(scene, hemi, sun, cfg, ctx);

/** Clear just the prop/level geometry, leaving player/enemies/fx alone. */
export function clearPropRoot(scene, propRoot);

/** Build one prop kind at (x, z). Returns THREE.Group. */
export function buildProp(kind, x, z, ctx);   // kinds: cactus, rock, toilet, pipe, tile, grate, puddle

/** New enemy models. Match v2's builder style (toon materials + outline). */
export function buildToiletGolem(ctx);
export function buildSewerRat(ctx);
```

Design notes:
- Replace fog, scene.background, floor material/color, ring color, hemi/sun lights per level.
- Props stay inside arena radius; scatter similar to v2.
- New enemies get the same treatment as v2 (toon + outline + shadow).
- `buildToiletGolem`: chunky, porcelain body, 2.2x scale of flusher, big crown rim.
- `buildSewerRat`: low, long, fast, glowing red eyes.

## `juice.mjs` — Agent C

Presentation layer + boss + retention mechanics. No direct game-state mutation beyond what the returned APIs expose.

```js
/**
 * DOM floating text layer (score pops, pickup tags).
 * @returns {{
 *   spawn(worldPos: THREE.Vector3, text: string, color: string, big?: boolean): void,
 *   update(): void,   // call each frame; projects each active floater to screen
 * }}
 */
export function createFloaters(containerEl, camera);

/**
 * Combo tracker.
 * @returns {{
 *   hit(): { count:number, tier:number, mult:number, tierChanged:boolean },
 *   decay(dt: number): void,   // resets if window expires
 *   reset(): void,
 *   snapshot(): { count:number, tier:number, mult:number, timer:number },
 * }}
 */
export function createCombo(opts = { windowSec: 2.0 });

/**
 * Powerup effect manager. Applies timed buffs to player.
 * @returns {{
 *   apply(kind: 'triple'|'rapid'|'speed'|'mega'): void,
 *   update(dt: number): void,
 *   isActive(kind: string): boolean,
 *   megaShotsLeft(): number,          // for 'mega' (charge-based, not time)
 *   renderHud(): void,                // update inner buff bar in hudEl
 *   snapshot(): object,
 * }}
 */
export function createPowerups(player, hudEl);

/** Clog King boss model. Returns THREE.Group; attach metadata at group.userData.boss. */
export function buildClogKing(ctx);

/**
 * Run one AI tick for the boss. api provides the side effects into game state.
 * api = {
 *   spawnEnemyBean(x, z, ax, az, speed, damage),
 *   damagePlayer(n),
 *   spawnPoof(x, z, color, count),
 *   sfx,    // full sfx interface
 * }
 */
export function clogKingAI(boss, player, dt, api);

/**
 * Drop a ring of bean pickups around a point. Respects cadence limits.
 * @param dropBeanPickupFn (x, z, amount) => void
 */
export function beanRainTick(game, dt, dropBeanPickupFn);
```

Design notes:
- **Floaters** use CSS-positioned divs inside `containerEl` (a `<div id="floaters">` in index.html, `position:fixed; inset:0; pointer-events:none;`). Each floater: 0.9s life, starts at projected screen coord, rises ~60px, fades out. Big mode = 2x size for combo tier breaks.
- **Combo**: on `hit()`, bump count, reset timer. Tiers trigger at 5, 10, 20, 40 kills; mult = 1,2,3,5. Return `tierChanged:true` when crossing a tier so caller can play bell + spawn big floater.
- **Powerups**:
  - `triple`: fire 3 beans in a 20° fan. Duration 8s.
  - `rapid`: reload time 1.2s → 0.4s. Duration 10s.
  - `speed`: player.baseSpeed * 1.5. Duration 10s.
  - `mega`: next 5 shots deal 3x damage. Charge-based.
  - HUD: small icons with remaining time bar each.
- **ClogKing**: 80 HP, big flusher body, gold crown. Two attacks:
  - Charge: lunges at player every 5s.
  - Ring burst: every 7s, fires 16 beans radially.
  - On death: confetti poof + "YOU CLEANED THE KINGDOM".
- **beanRainTick**: every 30s, drop 5 beans in a small circle around player.

## Shared state (declared in `game.mjs`)

```js
export const game = {
  state: 'title'|'play'|'gameover'|'win',
  wave: 1,
  levelIdx: 0,
  killsInLevel: 0,
  player: Player,
  playerObj,
  enemies: [...],
  projectiles: [...],
  pickups: [...],
  decals: [...],
  poofs: [...],
  propRoot: Group,
  lastShot: 0,
  dashCooldown: 0,
  waveTimer: 0,
  spawnQueue: 0,
  enemyCap: 12,
  score: 0,
  hiScore: number,          // loaded from localStorage['bsg_hiscore']
  boss: null | bossRef,
  rain: { timer: 0 },
  // systems (wired by coordinator)
  sfx, floaters, combo, powerups, analytics, cam,
};
```

## Player shape (declared in `player.mjs`)

```js
{
  obj, x, z, vx, vz, hp, maxHp,
  baseSpeed: 7.0, accel: 1.1, friction: 0.82,
  mag: { cur: 10, max: 10, reloading: false, reloadT: 0, reloadTime: 1.2 },
  iFrames: 0, recoil: { t: 0, dx: 0, dz: 0 },
  rot: 0, aimX: 0, aimZ: 1,
  toxTime: 0,
}
```

## Reference

- v2 source: `../butt-shooting-game-v2/index.html` — reuse toon/withOutline/blobShadow/buildButt/buildFlusher/buildBean patterns.
- Don't worry about perfect copying; adapt as needed, keep the same "chunky toon" feel.
