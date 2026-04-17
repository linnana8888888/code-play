Dodge the Meteors — Core Loop GDD (v0.1)

Changelog
- v0.1 (2026-04-17): Initial minimal core loop, economy placeholders, and core mechanic specs

Design Pillars
- Instinctive Dodging: Movement must feel responsive and readable within milliseconds
- Relentless Escalation: Tension rises predictably via speed/spawn pressure—no sudden, unfair spikes
- Fair Failures: Every hit must feel avoidable in hindsight; generous readability and post-hit recovery
- One-More-Run: Short sessions, fast restarts, clear personal best progression

Fun Hypothesis
- Squeezing through narrow gaps at the last moment feels exhilarating and fair when ship control is snappy and meteor patterns are legible

Assumptions (flag if changed)
- Target average session length: 90–120s [PLACEHOLDER]
- Input: Keyboard arrows/WASD (desktop); touch/drag (mobile) [IMPLEMENTATION-DEPENDENT]
- Playfield: Single screen, meteors descend from top; ship moves freely within bounds (2D X/Y)

Core Loop

Moment-to-Moment (0–30s)
- Action: Player steers ship to avoid descending meteors; micro-adjusts position to slip through gaps
- Feedback: Immediate positional response; thrust VFX/SFX; near-miss sound when a meteor passes within a near-miss radius [PLACEHOLDER]; subtle screen shake on close calls [PLACEHOLDER]
- Reward: +score per second survived and small bonus per meteor passed without collision [PLACEHOLDER]

Session Loop (30s–3m)
- Goal: Survive as long as possible through accelerating waves to set/beat high score
- Tension: Meteor speed and spawn density increase per wave; occasional heavier meteor variants [OPTIONAL LATER]
- Resolution: On collision, lose 1 life; after last life, Game Over → show score, best score, quick restart

Long-Term Loop (hours–weeks)
- Progression: Local high score table (best run); optional session stats (waves survived)
- Retention Hook: Personal best chasing; “one more” via instant restart and transparent early ramp

Economy & Tuning Variables ([PLACEHOLDER] = to be tuned in playtests)
- Player
  - Max speed: 300 px/s [PLACEHOLDER] — Must traverse 1/3 screen width in ~0.5s to enable gap corrections
  - Acceleration: 1200 px/s² [PLACEHOLDER] — Enables snappy starts without overshoot
  - Deceleration (no input): 1400 px/s² [PLACEHOLDER] — Aids precision; prevents drift
  - Hitbox radius: 14 px [PLACEHOLDER] — Slightly smaller than sprite for fairness
  - Lives: 3 [PLACEHOLDER] — Allows recovery and learning within a 2-minute target session
  - Post-hit invulnerability: 1.0s [PLACEHOLDER] — Prevents rapid multi-hit; conveys recovery

- Scoring
  - Survival score rate: +1 point per 0.25s survived [PLACEHOLDER] — Makes time meaningful
  - Meteor pass bonus: +2 per meteor that fully exits screen without collision and within near-miss radius bonus window +1 [PLACEHOLDER] — Encourages risky yet skillful near-misses without comp economy
  - Wave clear bonus: +25 per wave completed [PLACEHOLDER] — Punctuates progress

- Meteors & Waves
  - Wave length: 15s [PLACEHOLDER] — Creates clear beats; 6–8 waves ≈ 90–120s target
  - Meteor base speed (Wave 1): 150 px/s [PLACEHOLDER]
  - Speed increment per wave: +25 px/s [PLACEHOLDER]
  - Spawn interval base (Wave 1): 600ms [PLACEHOLDER]
  - Spawn interval min clamp: 220ms [PLACEHOLDER] — Prevents unwinnable clutter
  - Spawn interval decrease per wave: -40ms [PLACEHOLDER]
  - Meteor size range: radius 10–24 px [PLACEHOLDER] — Visual variety; affects gap calculus
  - Spawn lanes: Uniform X across width with Poisson disc spacing [PLACEHOLDER approach] — Avoids immediate overlaps creating impossible walls

- Difficulty Guards (“Fairness Rails”)
  - Max simultaneous meteors on screen: 18 [PLACEHOLDER]
  - Unavoidable check: Do not spawn within player AABB +/- safety margin (e.g., 96 px) in first 400ms of lifetime [PLACEHOLDER]
  - First 3s grace: Speeds reduced and spawn slowed by 50% [PLACEHOLDER]

Broken Definitions (Detect during tests)
- Average session length < 60s or > 180s at baseline skill → retune speed/spawn
- More than 1 in 20 deaths flagged as “unavoidable” by testers or via overlap check → adjust spawn safety and max simultaneous
- Player cannot traverse a typical gap (> 1.5x hitbox) given max acceleration within 300ms → increase acceleration or reduce meteor speed

Mechanic Specifications

Mechanic: Ship Movement
- Purpose: Enable precise, responsive dodging as the primary skill expression
- Player Fantasy: Agile pilot threading impossible gaps
- Input: Keyboard (WASD/Arrows) for 2D movement; continuous analog via touch/drag on mobile
- Output: Ship velocity/position updates within screen bounds; thrust VFX/SFX
- Success Condition: Player can make micro-corrections within 200–300ms and stop without overshoot
- Failure State: Sluggish response causing unavoidable hits; exiting bounds is clamped (no death)
- Edge Cases:
  - Simultaneous opposite inputs: prioritize zeroing velocity
  - Max velocity with small gap: ensure collision uses hitbox radius not sprite bounds
- Tuning Levers: Max speed, acceleration, deceleration, hitbox radius, input smoothing [PLACEHOLDER]
- Dependencies: Collision system, camera/screen bounds, VFX/SFX

Mechanic: Meteor Spawn & Wave Progression
- Purpose: Provide escalating pressure while maintaining fairness and legibility
- Player Fantasy: Surviving an intensifying meteor storm
- Input: Wave timer tick; RNG seed per wave; spawn scheduler
- Output: Meteors spawned with speed/size/position; wave transitions and UI cue
- Success Condition: Increasing challenge without creating impossible walls; visible cadence shifts per wave
- Failure State: Clumps that create unavoidable scenarios; dead time with no threat
- Edge Cases:
  - Spawn near player at low altitude: apply safety margin
  - Max meteors reached: queue or skip spawns to maintain performance/fairness
- Tuning Levers: Base speed, per-wave increment, spawn interval curve, max simultaneous, size range
- Dependencies: Collision, scoring, UI (wave indicator), RNG

Mechanic: Collision, Lives, and Invulnerability
- Purpose: Consequence for mistakes and pacing reset after hits
- Player Fantasy: Brush danger and recover with a second chance
- Input: Collision overlaps between ship and meteors
- Output: -1 life; trigger hit VFX/SFX; apply knockback [OPTIONAL]; start invulnerability frames
- Success Condition: Clear feedback; no double-hits during i-frames
- Failure State: Multiple life losses from one meteor cluster; unclear damage cause
- Edge Cases:
  - Collision during i-frames: ignore
  - Life at 1 and simultaneous double-collision: clamp to one life loss
- Tuning Levers: Lives, i-frame duration, knockback magnitude [if used]
- Dependencies: Movement, VFX/SFX, UI (lives), game state manager

Mechanic: Scoring
- Purpose: Provide clear, consistent reward for survival and skillful dodges
- Player Fantasy: Climbing the leaderboard through skill
- Input: Survival timer tick; meteor exit events; near-miss checks
- Output: Score increments; near-miss SFX; on Game Over, best score update
- Success Condition: Score growth maps to perceived performance and wave milestones
- Failure State: Score inflation that devalues survival; confusing sources of points
- Edge Cases:
  - Paused game: survival scoring paused
  - Wave transition: apply wave bonus once per transition
- Tuning Levers: Survival rate, pass bonus, near-miss radius/bonus, wave bonus
- Dependencies: Meteor lifecycle, UI, persistence (local best)

Onboarding within Wave 1 (minimal)
- First 3 seconds: Reduced speed/spawns; guaranteed gaps
- Introduce near-miss SFX once to teach safe proximity
- First life cannot be lost in first 2s due to spawn safety margin

Implementation Notes (non-binding)
- Use deterministic RNG per wave for debugging reproducibility
- Consider object pooling for meteors to maintain steady performance at high counts

Playtest Plan (first pass)
- Success: 70% of first-time players reach Wave 3; average session 90–120s; <5% report “unfair” deaths
- Variables to sweep: acceleration (±30%), spawn interval decrement (±10ms), i-frame (0.8–1.2s)
