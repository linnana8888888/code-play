# Butt Shooting Game · v3

Arcade-style 3D shooter. Three themed levels, reload-based ammo, boss fight, combo system, analytics.

## Run

ES modules require HTTP (not `file://`). Serve from this directory:

```
cd artifacts/butt-shooting-game-v3
python3 -m http.server 8765
# open http://localhost:8765/index.html
```

FPS pointer-lock requires HTTP; this is why `file://` is not supported.

## Controls

| Key | Action |
|-----|--------|
| WASD / Arrows | Move |
| Mouse | Aim (topdown/chase) |
| **Space** or Click | Fire |
| **R** | Reload (auto when mag empty; also restarts on game over) |
| **Shift** | Dash (0.6s cooldown, 0.25s i-frames) |
| **V** | Cycle camera: topdown → chase → FPS |
| **M** | Mute (persisted) |
| **`** (backtick) | Toggle analytics dev panel |
| **Esc** | Exit pointer lock |

## Levels

1. **Desert Dunes** — 20 kills; flushers, buttlings, windies; cacti + rocks.
2. **Porcelain Lab** — 30 kills; adds toilet golems; toilets, pipes, tiles.
3. **Sewer Depths** — 40 kills → **Clog King** boss (80 HP, 3 phases).

Win condition: kill Clog King.

## Mechanics

- Magazine: 10 beans, auto-reload 1.2s after empty. Unlimited reserve.
- Combo: 2s window. Tiers at 5/10/20/40 kills → x2/x3/x4/x5 score mult.
- Powerups drop from kills: `triple` (8s fan), `rapid` (10s reload 0.4s), `speed` (10s 1.5×), `mega` (next 5 shots 3× dmg).
- Bean rain: 5 bean pickups around player every 30s.
- Hi-score persisted in `localStorage['bsg_hiscore']`.

## Modules

```
index.html        HUD shell + importmap
game.mjs          main loop, state, levels, enemies, projectiles, integration
player.mjs        buildButt, movement, magazine/reload, input helpers
camera.mjs        topdown/chase/fps cycle + pointer lock
analytics.mjs     event log + localStorage rollup + dev panel
audio.mjs         WebAudio SFX + procedural music (3 level tracks)
scenes.mjs        LEVELS config, applyLevel, prop/enemy builders
juice.mjs         floaters, combo, powerups, Clog King + AI, bean rain
```

## Dev hooks (via `window.__game`)

```js
__game.setLevel(0|1|2)        // jump to level
__game.forceKill(n)            // force-kill n enemies
__game.spawnBoss()             // force-spawn Clog King
__game.cameraMode()            // current mode string
__game.mag                     // { cur, max, reloading, ... }
__game.combo                   // { count, tier, mult, timer }
__game.analyticsSession()      // rollup of current session
__game.game                    // full state (enemies, projectiles, etc.)
```

## Playtest

```
python3 -m http.server 8765 &  # in v3 dir
node playtest.mjs              # 17 checks; screenshots in ./qa/
```

Built with [Three.js r160](https://unpkg.com/three@0.160.0/) via importmap. No bundler.
