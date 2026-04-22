# v4 Notes — 2026-04-18

## Shipped so far

1. **FPS camera sensitivity** (camera.mjs)
   - Raised default from `0.002` → `0.0052` rad/px (~2.6×).
   - Added `[` / `]` live-tune (SENS_STEP 0.0008, clamped 0.002–0.012).
   - Persisted to `localStorage.bsg_fps_sens`.
   - Floater toast shows new value on each tap.

2. **Start-of-run grace** (game.mjs)
   - First-spawn `waveTimer` bumped `1.5s` → `3.2s`.
   - Banner: `GET READY — MOVE WITH WASD` on startGame.
   - Headless smoke: player moved `-2.03` on Z under held `W`; first enemy
     appeared at t≈3.2s, 0 console errors.

## Pending

3. Roblox-mechanic research → `RESEARCH_ROBLOX.md` (agent running)
4. Survivor.io addiction loop → `RESEARCH_SURVIVORIO.md` (agent running)
5. Visual upgrade: background + assets (after research)

## Diagnosis recap

- "Butt can't move at start" — movement was actually functional from t=0;
  perceived cause was a too-short 1.5s spawn timer that made the first
  couple seconds feel like ambush. Fixed by longer warm-up + banner.
- "Camera too slow" — mouse gain was 0.002 rad/px, below most FPS defaults
  (0.003–0.005). Raised and exposed live slider via bracket keys.
