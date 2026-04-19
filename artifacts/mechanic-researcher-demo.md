# Mechanic Researcher Demo Run

Instance: `mechanic-researcher-18befb43` · Model: `anthropic/anthropic.claude-sonnet-4-6`

---


## Turn 1 — assistant

- tool: **web_search** args={'query': 'most popular Roblox obby games 2024 2025 visit count CCU ratings'}
- tool: **web_search** args={'query': 'Tower of Hell Roblox visits CCU statistics 2024'}
- tool: **web_search** args={'query': 'Roblox obby games top charts 2025 player count'}
I'll research the current top Roblox obby experiences before writing the brief. Let me pull live traction data first.

## Turn 2 — tool


## Turn 3 — assistant

- tool: **perplexity_research** args={'query': 'most popular Roblox obby games 2024-2025 with visit counts CCU ratings traction signals Tower of Hell Mega Fun Obby', 'depth': 'standard', 'recency': 'year'}
- tool: **perplexity_research** args={'query': 'Roblox obby game mechanics analysis core loop retention hooks 2024 kids games', 'depth': 'standard', 'recency': 'year'}

## Turn 4 — tool


## Turn 5 — assistant

- tool: **perplexity_research** args={'query': 'Tower of Hell Roblox mechanics deep dive random tower generation no checkpoints time limit session length gameplay loop', 'depth': 'standard', 'recency': 'year'}
- tool: **perplexity_research** args={'query': 'Mega Fun Obby Roblox mechanics stages pets progression system rewards gameplay 2024', 'depth': 'standard', 'recency': 'year'}
- tool: **perplexity_research** args={'query': 'Rainbow Obby Roblox mechanics color themes checkpoints badges rewards session structure kids', 'depth': 'standard', 'recency': 'year'}
Good data on Tower of Hell, Mega Fun Obby, and Rainbow Obby. Now let me get deeper mechanic teardowns for each.

## Turn 6 — tool


## Turn 7 — assistant

- tool: **asset_search** args={'query': 'obstacle course platformer colorful kids', 'pool': 'kenney', 'limit': 3}
- tool: **perplexity_research** args={'query': 'Roblox obby monetization gamepasses speed coil pets what works what fails kids 7-12 design pitfalls 2024', 'depth': 'quick', 'recency': 'year'}
Excellent. I now have solid data on all three games. Let me also fetch some quick reference screenshots to complete the package.

## Turn 8 — tool


## Turn 9 — assistant

I now have everything I need. Here is the complete brief:

---

# `ideation_input_v1` — Roblox Obby Experience (Ages 7–12)
**Mechanic Researcher teardown · ~1,450 words**

---

## 1. Reference Games

| # | Game | Platform | Link | Why Picked | Traction Signal |
|---|------|----------|------|------------|-----------------|
| 1 | **Tower of Hell** | Roblox | [roblox.com/games/1962086868](https://www.roblox.com/games/1962086868) | Defines the modern obby meta; procedural tower is the most-copied mechanic in the genre | **15.2B visits · 45K peak CCU · 4.5M favorites · 95% likes** |
| 2 | **Mega Fun Obby** | Roblox | [roblox.com/games/5205933097](https://www.roblox.com/games/5205933097) | Highest-volume pure stage-progression obby; added pets/rebirths to extend LTV | **2.8B visits · 25K peak CCU · 1.2M favorites · 92% likes** |
| 3 | **Rainbow Obby** | Roblox | [roblox.com/games/1560972808](https://www.roblox.com/games/1560972808) | Official Roblox-published; color-theme updates drove 20% YoY growth; benchmark for kid-safe design | **3.1B visits · 30K peak CCU · 800K favorites · 96% likes** |

---

## 2. Core Loops — Tick-by-Tick (≤60 seconds of play)

### 🔴 Tower of Hell
> *The rage-loop*

1. **Spawn** in lobby → 8-minute round timer starts → random tower assembles above you (6–10 sections, each a distinct obstacle type)
2. **Jump** onto first platform → navigate spinning blocks / thin ledges / laser grids using only move + jump
3. **Fall** → teleport instantly back to **ground floor** (no checkpoints — this is the hook)
4. **Re-attempt** the same tower in the same round — muscle memory builds in real time
5. **Timer expires** → new random tower generates → everyone resets regardless of progress
6. **Coins + XP** awarded for how many sections you cleared; cosmetics unlocked via leveling

**Failure state**: Instant, zero-friction — you're back at the bottom in <1 second. No death screen, no loading. The punishment is time lost, not a modal.

### 🟢 Mega Fun Obby
> *The marathon-loop*

1. **Spawn** at Stage 1 of 2,000+ sequential stages → each stage is a small, self-contained obstacle room
2. **Complete stage** → checkpoint auto-saves → move to next stage
3. **Die** → respawn at current stage checkpoint (not start of game)
4. **Collect coins** passively as you progress → spend on pets that display alongside your avatar
5. **Rebirth** at milestone stages → multiplier increases coin gain → cosmetic badge unlocked
6. **Return tomorrow** → you're exactly where you left off; the number "Stage 847" is your identity

**Failure state**: Soft — respawn at stage start. Session can be 2 minutes or 2 hours; the player decides.

### 🌈 Rainbow Obby
> *The theme-park loop*

1. **Spawn** in colorful lobby → enter portal to Stage 1
2. **Navigate** ~40 themed stages (each a distinct color world: red lava zone, blue ice zone, etc.)
3. **Hazards**: fading rainbow tiles (step → tile cycles colors → disappears), lava kill bricks, narrow beams
4. **Checkpoint** every 3–5 stages → death returns you to last checkpoint
5. **Complete a color zone** → visual fanfare, badge awarded, next zone unlocks
6. **Finish all 40 stages** → "Winner" badge + lobby cosmetic

**Failure state**: Moderate — checkpoint respawn, but losing 3–5 stages of progress stings enough to create tension without rage-quitting.

---

## 3. Session Shape + Retention Hooks (Ranked)

### Session Shapes
| Game | Avg Session | Retry Friction | Meta Progression |
|------|-------------|----------------|-----------------|
| Tower of Hell | 8 min (hard-capped by round) | Near-zero (instant respawn) | XP level, cosmetics, coin shop |
| Mega Fun Obby | 10–25 min (player-controlled) | Low (checkpoint save) | Stage number, pets, rebirth multipliers |
| Rainbow Obby | 15–30 min (completion-driven) | Medium (checkpoint, ~3-stage loss) | Badges, zone unlocks |

### Retention Hooks (ranked by observed weight)
1. **🥇 Persistent progress number** *(Mega Fun Obby's stage counter)* — kids share "I'm on Stage 1,200" as social currency; the number is the game
2. **🥈 Procedural novelty** *(Tower of Hell's random tower)* — "I've never seen this layout" kills boredom; replayability without content cost
3. **🥉 Collectible identity** *(pets, cosmetics)* — avatar expression drives return visits; pets follow you everywhere as visible status
4. **4th — Badge/achievement punctuation** *(Rainbow Obby's zone badges)* — short-term goals for kids who can't sustain a 2,000-stage marathon
5. **5th — Social spectacle** *(all three)* — watching other players attempt the same obstacle creates ambient competition without explicit PvP

---

## 4. Steal List — Concrete Mechanics + Porting Notes

### ✅ Steal 1: **Round-Based Tower with Procedural Section Swap**
*From: Tower of Hell*
- **What**: Every N minutes, a new tower assembles from a pool of handcrafted section prefabs. No two rounds are identical.
- **Port it**: Build 30–50 section prefabs (each ~10 platforms). On `RoundStart`, `math.random` picks 6–8 sections and stacks them via `CFrame` offsets. Store section pool in `ServerStorage`. One script, ~200 lines. Scope: **1 dev, 1 week**.
- **Kid adjustment**: Add 1 "easy" section guaranteed at the bottom each round so new players always get a win moment.

### ✅ Steal 2: **Persistent Stage Number as Social Identity**
*From: Mega Fun Obby*
- **What**: Player's current stage is stored server-side (DataStore), displayed above their head, and visible to all in the lobby.
- **Port it**: `DataStoreService:GetDataStore("PlayerStages")` → save on checkpoint touch → display via `BillboardGui` above character. Scope: **1 dev, 2 days**.
- **Kid adjustment**: Add milestone celebrations at round numbers (100, 250, 500) — particle burst + server announcement — to punctuate the grind.

### ✅ Steal 3: **Fading/Reactive Platform Hazards**
*From: Rainbow Obby*
- **What**: Platforms that change state on player contact — fade out, change color, flip — creating read-and-react gameplay without complex scripting.
- **Port it**: `BasePart.Touched` event → tween `Transparency` to 1 over 1.5s → set `CanCollide = false` → reset after 4s. Color cycling via `Color3.fromHSV` hue loop. Scope: **1 dev, 1 day per hazard type**.
- **Kid adjustment**: Give fading tiles a 2-second warning flash (yellow → orange → gone) so the mechanic teaches rather than punishes.

### ✅ Steal 4: **Zero-Friction Instant Respawn**
*From: Tower of Hell*
- **What**: No death screen, no "Respawn" button, no loading. Player teleports to spawn point in <0.5s.
- **Port it**: `Humanoid.Died` → `task.wait(0.1)` → `HumanoidRootPart.CFrame = spawnCFrame`. Disable default respawn in `Players.RespawnTime = 0`. Scope: **1 dev, 2 hours**.
- **Why it matters for kids**: Removes the shame/frustration loop of staring at a death screen. Failure feels like a bounce, not a punishment.

### ✅ Steal 5: **Cosmetic Pet Companion**
*From: Mega Fun Obby*
- **What**: A small animated model that follows the player, awarded at milestone stages, visible to all other players.
- **Port it**: `TweenService` to lerp pet model toward `HumanoidRootPart` position each heartbeat. Store unlocked pet ID in DataStore. Display in lobby showcase. Scope: **1 dev + 1 modeler, 3 days**.
- **Kid adjustment**: Make pets react to obstacles (bounce when player falls, cheer when player completes a stage) for emotional resonance.

---

## 5. Anti-Steal List

| Mechanic | Works There Because… | Would Fight Kids-Focused Concept Because… |
|----------|---------------------|------------------------------------------|
| **No checkpoints** *(Tower of Hell)* | Rage-loop is the brand; 10–14yo audience self-selects for punishment | Ages 7–9 will quit after 3 full-tower falls; kills new-player funnel |
| **2,000+ linear stages** *(Mega Fun Obby)* | Infinite content runway; players accept sameness | Stage 1,847 feels meaningless to a 7-year-old; needs narrative punctuation every 20–30 stages max |
| **Pure skill / no assists** *(Tower of Hell)* | Skill ceiling is the product; speedrunner community sustains it | Kids 7–9 need optional scaffolding (wider platforms, slower hazards) or they bounce before the fun begins |
| **Rebirth/prestige grind** *(Mega Fun Obby)* | Older kids enjoy number-go-up loops | Prestige resets progress — confusing and demoralizing for under-10s who worked hard to reach Stage 500 |

---

## 6. Mash-Up Hypotheses

### 🧪 Mash-Up A: "Rainbow Tower" — *Rainbow Obby themes × Tower of Hell rounds*
Each 8-minute round generates a tower where **every section has a distinct color-world theme** (lava zone, ice zone, candy zone). Completing a section awards a themed badge. Procedural novelty (ToH) + visual celebration + badge collection (Rainbow Obby).
- **Risk**: Art cost is high — 30+ section prefabs × themed dressing = significant modeling scope. Mitigate with modular kit approach.

### 🧪 Mash-Up B: "Stage Climber" — *Mega Fun Obby persistence × Tower of Hell instant-respawn*
Linear 500-stage game with **zero-friction respawn** (no death screen) and **persistent stage counter** visible in lobby. Stages grouped into 25-stage "worlds" with a boss obstacle at the end of each world. Short milestone loops (25 stages ≈ 15 min) inside a long meta arc (500 stages).
- **Risk**: DataStore writes on every checkpoint can throttle under high CCU — use debounce + batch writes.

### 🧪 Mash-Up C: "Pet Racer" — *Mega Fun Obby pets × Tower of Hell rounds × light social layer*
Round-based tower where your **pet gains XP** each round based on how high you climbed. Pet levels up visibly, unlocking new animations and sizes. Friends can see each other's pet levels in the lobby — social status without PvP conflict.
- **Risk**: Pet progression system is a full second game on top of the obby; scope creep is real. Needs a hard feature cap at MVP (3 pet tiers max).

---

## 7. Open Questions for the Designer

1. **Session length: <5 min or 15–20 min?**
   If <5 min → lean Tower of Hell (round-based, procedural, instant retry). If 15–20 min → lean Mega Fun Obby (persistent stages, world structure). This single decision determines which steal list items are load-bearing vs. optional.

2. **Failure philosophy: bounce or sting?**
   Zero-friction instant respawn (ToH model) maximizes attempts-per-session but removes tension. Checkpoint-with-setback (Rainbow Obby model) creates genuine stakes but risks frustration for ages 7–8. Do you want kids to feel *challenged* or *unstoppable*? The answer shapes every hazard's design.

3. **Solo mastery or social spectacle?**
   All three references are technically solo experiences made social by ambient visibility (stage numbers overhead, pets following you, shared tower). Do you want to deepen that ambient social layer (e.g., friends' ghosts on your tower, co-op checkpoints) — or keep it pure solo to reduce moderation surface area for a kids audience?

---

*Sources: Roblox game pages, RTrack.social analytics, Perplexity/Sonar research synthesis (April 2025). Traction figures are platform-reported or RTrack-aggregated; treat as directionally accurate, not audited.*
