# Survivor.io Addiction Loop — 2026-04-18

Research target: Habby's **Survivor!.io** (mobile, 2022, still pulling roughly USD 5M/month three years in). Primary sources: BlueStacks official guide, BlueStacks evolution tier list, AntGames strategy guide, WriterParty evolution list, Startpage+Reddit snippet harvesting (r/Survivorio), Habby's own marketing page. Perplexity API was intermittently unreachable so findings lean on guide sites and surfaced Reddit/TikTok snippets rather than the full Reddit thread bodies.

Absolute paths to cached primary sources: `/tmp/survio_research/{bluestacks_evo.html, bs_tier.html, writerparty_evo.html, antgames_guide.html, habby_official.html, sp_*.html}`.

---

## 1. Core session loop — what happens minute-by-minute

A Survivor!.io run is a **15-minute timer** that ends with a stage boss. Pacing across sources is consistent:

**0:00 – 1:30 (onboarding burst)**
- Slow shuffling zombies spawn one at a time from all four edges. They die in 1–2 hits of the starting Baseball Bat (or chosen weapon). The player does *nothing* offensive — movement alone dictates life or death.
- Tiny green XP crystals drop from every kill and pull toward the player inside a small magnet radius. The first level-up lands at ~15–25 seconds. Levels 1–4 happen in the first 90 seconds; each presents a 3-card choice (see §2).
- First gold coins, HP ham, magnet and bomb pickups appear from breakable crates. This teaches the pickup vocabulary before it matters.

**1:30 – 5:00 (build assembly)**
- Enemy density ramps: small packs (5–10) then screen-filling waves. Mini-elites with more HP push the player off-center. Projectile-shooting ghouls join around minute 3–4.
- By ~minute 3 the player typically has 3–4 skills, often with one weapon at level 3–4. The "what should I pick next?" question becomes strategic — players are now deliberately chasing an evolution pair (e.g. Kunai + Koga Ninja Scroll).
- A **mid-stage elite/mini-boss** ("the Big One" in Stage 1) appears around minute 4–5, drops a **golden chest**. The chest is the evolution trigger: if you meet the weapon-at-5 + matching-passive requirement, the chest *hands you the evolved form*. BlueStacks' guide explicitly calls this the decisive power spike.

**5:00 – 15:00 (power fantasy & crescendo)**
- Horde density quadruples. Boxed-in "kill wall" scenarios are routine. Screen becomes visually chaotic (AntGames: "hundreds of enemies on-screen"). Without at least one evolution the player dies here.
- Minutes 8–12 are the classic "AFK victory lap" if the build came together — reviewers quote this moment as both addictive (*"enjoyable even for F2P"*) and as the point where it starts to lose tension (*"loses the fun as soon as you're strong enough to be afk and still winning"*, r/Survivorio 2025-10-29).
- **Final boss at 15:00** — a second-tier boss arrives, player must burst it down before the timer-rage mechanic kicks in. Victory unlocks the next chapter and drops large gear/chest rewards.

---

## 2. Level-up flow

- **Cadence**: ~every 15–25 seconds early; every ~30–60 seconds by mid-run; infamously clumps together late. A Reddit player: *"my favourite part is when you've got all the xp stockpiled for health then the boss pushes you and makes you level up 20 times"* (r/Survivorio 2023-08-30). The multi-level pop is a celebrated juice moment.
- **Every level-up pauses the game** and shows **3 cards** drawn from two pools:
  - **Active weapons** (up to 6 slots, max level 5): Baseball Bat, Kunai, Forcefield, Guardian, Drill Shot, RPG, Lightning Emitter, Laser Launcher, Molotov, Drone Type-A, Drone Type-B, Durian, Brick, Soccer Ball, Boomerang, Katana, Shotgun, Revolver, Lightchaser, Void Power.
  - **Passive supports** (up to 6 slots, max level 5): Energy Cube, Energy Drink, HE Fuel, Oil Bond, Fitness Guide, Hi-Power Bullet, Hi-Power Magnet, Sports Shoes, Ronin Oyoroi, Koga Ninja Scroll, Exo-Bracer, Ammo Thruster, Medi-drone.
- **Why the choice feels meaningful**: every passive is a *flag* that points to a specific evolution (Energy Cube → Supercell + Death Ray + Spirit Shuriken; HE Fuel → Sharkmaw + Caltrops + Inferno Bomb). Taking a passive at level 3 is effectively voting for a future power spike. This gives players a "plan" after minute 1 instead of a random loot treadmill.
- **Rerolls**: a limited number per run, used to dodge dead cards when you're one step from an evolution. BlueStacks: *"if your Kunai is at level 5 but you haven't pulled Energy Cube yet, a reroll might save your run."* Scarcity makes the reroll itself feel valuable.
- **Variable reward schedule**: because you can't see what 3 cards the next level will show, leveling up is a pull-the-lever moment. r/Survivorio top thread: *"random rewards all the time — that is highly addictive."*

---

## 3. Weapon evolution / fusion

Survivor.io's recipe grammar: **Active Weapon at max level 5 + matching Passive Skill at any level, then open a boss's golden chest** → weapon transforms into its evolved form (often doubling DPS, sometimes changing behavior entirely, and freeing the slot from further upgrade churn).

Confirmed recipes (cross-referenced BlueStacks tier list + WriterParty + AntGames):

| Base | Passive | Evolves to | Tier |
|---|---|---|---|
| Molotov | Oil Bond | **Fuel Barrel** | S |
| Lightning Emitter | Energy Cube | **Supercell** | S |
| Modular Mine | Molotov | **Inferno Bomb** | S |
| Brick | Fitness Guide | **1-Ton Iron** / Dumbbell | S |
| Drone A + Drone B | Medi-drone | **Destroyer** / Divine Destroyer | S |
| Boomerang | Hi-Power Magnet | **Magnetic Dart** | A |
| Forcefield | Energy Drink | **Pressure Forcefield** | A |
| Drill Shot | Ammo Thruster | **Whistling Arrow** | A |
| Guardian | Exo-Bracer | **Defender** | A |
| Laser Launcher | Energy Cube | **Death Ray** | A |
| RPG | HE Fuel | **Sharkmaw Gun** | A |
| Katana | Ronin Oyoroi | **Demon Blade** | A |
| Soccer Ball | Sports Shoes | **Quantum Ball** | B |
| Durian | HE Fuel | **Caltrops** | B |
| Void Power | Exo-Bracer | **Gloom Nova** | B |
| Lightchaser | Ronin Oyoroi | **Eternal Light** | B |
| Kunai | Koga Ninja Scroll | **Spirit Shuriken** | B |
| Revolver | Hi-Power Bullet | **Reaper** | C |
| Shotgun | Hi-Power Bullet | **Gatling Gun** | C |

- **Eureka moment**: the chest opens, a giant named item explodes onto screen, weapon behavior visibly changes (Lightning Emitter → Supercell doubles bolt count and arc range; Drill Shot → Whistling Arrow goes from a stubby forward cone to a relentless spiralling orbital). BlueStacks: *"Timing this evolution early can determine whether you dominate or get overrun."*
- **First evolution timing**: typically the **minute 4–5 mid-boss chest**. A fast/lucky run can evo by 3:30. If you're still waiting past minute 7 the run is usually dead.
- **Stacking**: by minute 10 elite runs have **2–3 evolutions**. BlueStacks describes that state as "near-invincibility" — the power fantasy curve becomes explicit.

---

## 4. Progression outside the run

Daily hook is *dense*, structured like an Archero-descended meta:

- **6 gear slots** — Weapon, Helmet, Armor, Gloves, Boots, Necklace. Each piece has grades (Common → S → SS) and levels; identical pieces fuse to raise grade. Evolving equipment off-run is the main power-creep pacer.
- **Tech Parts** — passive modifiers that mirror in-run passives (e.g. the Durian has the Angelic Tear Crystal / Nanobot tech part). You slot and level these between runs.
- **Elite Chips** — socketable inserts giving flat/%-damage; upgraded by duplicate shards.
- **Relic Cores / Master Yang shards / Pet Awakening / SS weapon relics / Survivor Awakening** — stacked subsystems introduced in waves since launch (r/Survivorio: *"First Eternal Techs then Master Yang then Pet Awakening and then the SS weapon relics, and now Survivor Awakening"*). Classic FOMO ladder.
- **CoV (Character of Valor) and Lucky Gacha** — premium egg/box gacha that dispenses shards of the above. "Lucky Gacha returns! It's a Spring of fortune!" events every few weeks, driven by daily login tickets so F2Ps can pull a handful per month.
- **Daily login routines** cited by players: claim login reward → do 3 chapter farms (best chapter for equipment/XP/essence) → clear daily missions for gacha coins → Fortress Defense / Trial / Dungeon rotating mode → Battle Pass daily tick → guild gifts. Multiple players note it's a 30–60 min daily routine if you're engaged and a 10 min skim if you're minimal.
- **The hook**: almost every session grants **at least one stat bump** from incremental shards, so you *always* return stronger. Plus the gacha lottery creates an occasional legendary drop that hits the random-reward circuit again.

---

## 5. Feedback / juice

- **XP gem magnetism** — every kill drops a tiny green crystal. Inside a small radius, they **accelerate toward the player** and bounce/stack into a stream. Bigger magnet radius is itself a buildable passive. TikTok trope: *"Maxing out everything with one magnet in one go"* — collecting a map-wide magnet pickup triggers hundreds of gems streaming in and instant multi-level-up. This single sequence is the most-clipped moment from the game.
- **Multi-level-up pop** — when a magnet or boss kill drops a huge XP clump, players level up 5–20 times in a row. The level-up sfx stacks and the card UI chains card → pick → card → pick, feeling like a slot machine jackpot.
- **Damage numbers** — bright floaters with crits in larger/yellow. Satisfies "I did a thing" at 100Hz. Mass-AOE weapons produce a wall of numbers.
- **Hit sparks + ragdoll chunking** — hits produce particle bursts; zombies explode into pixel chunks on death, reinforcing high KPM with constant visual confetti.
- **Screen-shake / flash on elite hits and boss phase changes.**
- **Power fantasy ramp** — the explicit design goal cited by Naavik-era coverage: go from *"barely surviving one zombie"* to *"standing still while the whole map dies around you."* Players frame this as their reason to keep replaying the same chapter: the first 60 seconds being fragile makes the last 300 seconds feel earned.
- **Sound design** — low-poly but hyper-responsive. Pickup pings, level-up whoosh, weapon loops layered; the game feels loud and responsive even on mute (haptics). Music ramps with wave density.

---

## 6. "The moment it hooked me" — player quotes

Harvested from r/Survivorio and adjacent snippets (full threads blocked by Cloudflare/Reddit network policy, but descriptions from Startpage/DuckDuckGo result snippets are verbatim):

- *"Why is this game so addictive? ... random rewards all the time — that is highly addictive. Just google 'random reward addiction'."* (r/Survivorio, 2024-06-24)
- *"It's hella addictive and well enjoyable even for free to play and it has a lot of gotcha moments with gamble like mechanics if you like those."* (r/Survivorio, 2025-01-21, "How is Survivorio")
- *"My favourite part is when you've got all the xp stockpiled for health then the boss pushes you and makes you level up 20 times."* (r/Survivorio, 2023-08-30, "This is so annoying!!!" — noted it's ironic praise; the overload is the fun)
- *"Does anyone else camp out by a magnet until the boss spawns? ... experience for the next magnet."* (r/Survivorio, 2022-11-06) — players literally plan routes around the magnet pickup because the stream-and-level-up moment is a highlight.
- *"Welcome to the grind! The useless but super addictive grind."* (r/Survivorio, 2023-04, re: meta progression)
- *"Loses the fun as soon as you're strong enough to be afk and still winning."* (r/Survivorio, 2025-10-29) — negative but telling: the run-power arc from 0 to god is *the* loop, and flattening it kills engagement.

Across sources the hook clusters into three moments: **(a)** the first evolution's visual/DPS shift at ~minute 4, **(b)** the magnet-pickup mass-collect cascade, and **(c)** logging in the next day to find a legendary gear shard from the Lucky Gacha.

---

## Portable tricks for a 1-file HTML5 Three.js game

Given this repo (`index.html` shell, modules: `game.mjs`, `juice.mjs`, `player.mjs`, `scenes.mjs`, `audio.mjs`, `analytics.mjs`), five tricks rank-ordered by effort-to-impact:

1. **XP gems with magnet radius + interrupting level-up modal**
   - File: `juice.mjs` — add `Gem` entity class {pos, value=1}, push onto `window.__game.gems`.
   - In `game.mjs` enemy death hook: spawn 1–3 gems at corpse position with small radial kick.
   - Tick in main loop: if `|player.pos - gem.pos| < player.magnetR` (start 2.5 world units), lerp-ease gem toward player at `5 + dt * factor`; on overlap, `player.xp += gem.value`, sfx `xp_pickup`.
   - Curve: `xpToNext = 3 + level * 2`. Add `levelUpQueue` counter; when `xp >= xpToNext`, decrement xp, increment counter, set `gamePaused=true`, show 3-card modal via a new `chooseCard()` overlay in `index.html` (absolute-positioned HTML, not WebGL).
   - Card pool: draw 3 random from a list of {weaponUpgrades, passiveUpgrades}, weighted so currently-held items appear more (keeps builds converging). Dequeue one card → unpause; if `levelUpQueue > 0`, re-show immediately. This chains the slot-machine feel.

2. **Weapon evolution recipe via golden-chest drop**
   - File: `scenes.mjs` — declare `EVOLUTIONS = [{base:'triple',passive:'rapid',evo:'tripleRapid'}, {base:'mega',passive:'speed',evo:'megaRush'}]`.
   - Your existing powerup catalogue already has {triple,rapid,speed,mega} — promote them from timed buffs to *levelable* skills with max-level 5.
   - On mid-level elite kill (add a level-flagged `elite` enemy in `juice.mjs`), drop a `goldChest` prop. On pickup, iterate `EVOLUTIONS`: if `player.skills[base].level>=5 && player.skills[passive]`, replace base slot with evo form that has a unique fire pattern (e.g. `tripleRapid` = 7-way fan + 0.2s reload). Play a distinct "EVOLUTION!" banner + screen-flash.
   - Ship even 2–3 recipes — the pattern itself is the dopamine, not recipe count.

3. **Variable-reward 3-card draw with reroll + passive→weapon pointers**
   - File: `juice.mjs` or new `cards.mjs`. Each passive card explicitly tells the player which weapon it unlocks — e.g. "Ammo Thruster (needed for Drill Shot → Whistling Arrow)". This turns level-ups from loot into a plan, which is the core of Survivor.io's stickiness.
   - Give player 2 rerolls per run; each used reroll re-draws the 3 cards. Surface a tiny "plan meter" in HUD: "Drill Shot 3/5 + Ammo Thruster ✓ — 2 picks to evolution" — that anticipation is the engagement.

4. **Mass-magnet pickup & multi-level-up jackpot**
   - File: `juice.mjs` — on rare drop (minute 3+, elite kills), spawn a `BigMagnet` pickup. Collect → set `player.magnetR = 999` for 1.5s, then back to normal. All gems on map stream in; HP bar and XP bar fill; level-up modal chains.
   - Add a distinct rising-tone audio cue, a screen-wide radial-pulse shader in `juice.mjs` (Three.js `ShaderMaterial` on a fullscreen quad), and a combo counter that stacks `LEVEL UP x N` floaters. This is the single most-clipped moment of the source game — free virality if you nail the audio + visual confetti.

5. **15-minute wave escalation with guaranteed mid-boss chest and final boss**
   - File: `scenes.mjs` — replace the current "kill X then next level" with a `timer`-driven wave curve. Wave spec: `{t:0, dps:2}, {t:90, dps:6}, {t:240, elite:true, drop:'goldChest'}, {t:600, boss:'MidBoss'}, {t:900, boss:'ClogKing'}`.
   - Difficulty ramps on wall-clock, not kills. Gold chest at minute 4 guarantees the evolution power spike (matches Habby's pacing). Existing Clog King can slot in as the 15:00 final boss; add a mid-boss at 10:00 so the arc has two crescendos.
   - Bonus: keep a running "how far did you get" telemetry in `analytics.mjs` to see where your retention cliff actually is.

---

## NOT portable (or portable only as lightweight stub)

- **Equipment gacha / gear fusion (6 slots × grades × fusion)** — heavy meta requires persistent accounts, server, and months of content to pace. *Lightweight substitute*: a single "loadout" in `localStorage` that carries 1 stat bonus (+5% damage) earned per run completed. Ladder stops at +50%. Gives a "come back tomorrow for something" hook without a real gear economy.
- **CoV / Lucky Gacha with premium currency** — don't touch monetization for a portfolio/toy project; also legally fraught (loot boxes). *Lightweight substitute*: a cosmetic-only "card pack" that unlocks at end of each run and grants a random player skin/projectile trail. Pure vanity, keeps the "surprise at run-end" beat.
- **Tech parts / elite chips / pet awakening / master yang / survivor awakening** — these are stacked compulsion loops a live-ops team ships over years. A 1-file HTML5 clone won't reproduce them, and shouldn't: they're the compromise that *costs* Survivor.io its original charm (see "afk and still winning" complaints). *Substitute*: one "meta upgrade tree" with 10 nodes (max HP, magnet radius, reroll count, start-with skill). Gold earned per run unlocks a node. Ten unlocks and you're done — no infinite grind.
- **Daily missions / battle pass / events calendar** — require a backend and a live team. *Substitute*: a single "daily challenge" seeded from `new Date().toDateString()` in JS (e.g. "beat level 2 with only melee"). One daily, one reward, resets at local midnight. Zero infra, 1-day ship.
- **Multiplayer/guild features** — ignore.

Biggest trap to avoid: Survivor.io's later monetization crust (Master Yang, Awakening, etc.) is widely cited as the reason veteran players churn. The *design magic* is in-run — evolution, magnet, level-up-chain, power fantasy ramp. Port those. Leave the hamster wheel at the door.
