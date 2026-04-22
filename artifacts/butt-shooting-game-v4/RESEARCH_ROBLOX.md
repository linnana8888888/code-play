# Roblox Mechanic Mining — 2026-04-18

Research scope: Arsenal, Bad Business, Phantom Forces, Blade Ball, Murder Mystery 2, Evade, Doors (2024–2026 live metas). Deliberately excluding mechanics our game already has (waves, combo multiplier, powerups, bosses, reload, magazine, dash, camera cycle, 10-round clip).

Primary sources (Fandom MediaWiki APIs, verified live):
- robloxarsenal.fandom.com — Gun Game, Stomp, Rocket/Recoil Jumping, Domination & Revenge
- bladeball.fandom.com — Dash, Randomizer gamemode, Playtime Rewards, Classic
- roblox-phantom-forces.fandom.com — Mechanics/Combat, Mechanics/Spotting
- roblox-bad-business.fandom.com — Gamemodes (Gun Game, Randomizer, Rapid Randomizer, Overclocked, Infection), Skins
- murder-mystery-2.fandom.com — Roles, Sheriff
- roblox-evade.fandom.com — Utilities (Decoy, Radar, Compass, Radio, Timer)
- doors-game.fandom.com — Hiding mechanic, Rush entity cadence

---

## 1. Gun Game weapon ladder (weapon-of-the-kill)

**Source**: Arsenal (core mode, 32 stages → Golden Knife finisher); Bad Business "Gun Game" (30 weapons + Golden Gun on kill 30 + Golden Knife on kill 31; 75-point assist also advances). Everyone sees the same weapon list so there's a shared "oh no he's on the knife" moment.

**Input**: No new button. Every kill silently swaps your primary; a big banner pops in ("LEVEL 7 — DB Shotgun") and a sound sting plays. The *last* stage is a melee-only Golden Knife — visible to everyone via kill feed / HUD badge so enemies know who to focus.

**Feedback loop**: Kill → freeze-frame of the *next* weapon flying into your hands with a clicky rack sound → new HUD icon → you immediately try it. Lose your streak by dying and you drop a stage in some variants (Arsenal does not, classic CoD Gun Game does — pick the kid-friendly version: no drop).

**Why sticky**: Novelty treadmill. Kids who'd normally spam one weapon are *forced* to try the rocket launcher, the minigun, the pistol, the crossbow — each kill is a free loot box. The Golden Knife finisher creates an iconic "last-boss-of-the-round" moment within the match and is endlessly clippable.

**Port effort (S/M/L)**: **S**. We already have a single weapon; just keep a ladder array `['pistol','smg','shotgun,'rocket','railgun','minigun','goldenKnife']`, rotate on kill, re-use existing projectile code with different colour/damage/spread tables.

**Risk**: Rocket/railgun visuals need to be distinct enough that a 7-year-old immediately gets the new rules. If two weapons feel the same, the novelty breaks.

---

## 2. Active-parry skill-check (Blade Ball deflect)

**Source**: Blade Ball (parry is THE game — a ball homes at you, you click within a tight window to reverse it). ~30M+ plays/day for two years. Accepted so universally that the devs even allow autoclickers — the tension is the *timing window*, not clicks-per-second.

**Input**: Single key/mouse press (Blade Ball uses left-click; on our game map it to `F` or right-click so it doesn't conflict with shooting). Window ~120–250ms; visible ring contracts, audio "whoosh" rising in pitch.

**Feedback loop**: Incoming projectile → camera-edge red indicator + rising tone → press `F` inside window → screen flash, freeze-frame, projectile reversed at 2× speed back at shooter with chromatic aberration → kill feed shows "PARRY!". Miss = full damage and a muted "dud" sound.

**Why sticky**: Pure skill expression kids can *feel* getting better at. First hour you parry 10% of shots; by hour five you parry 80%. Every successful parry is a dopamine hit AND it turns defence into offence — you literally kill the enemy who shot you. It's also the most clippable moment in any shooter.

**Port effort (S/M/L)**: **M**. Need a tagged subset of enemy projectiles (boss plasma, mini-boss grenades) to be parry-able, a reliable incoming-angle test, and visual telegraph. Don't parry bullets (too fast, too frustrating) — parry slow telegraphed attacks only.

**Risk**: Timing windows that are too tight frustrate kids; too loose is a free button. Tune at 200ms default with a +50ms "kid mode" toggle.

---

## 3. Stomp / ground-pound insta-kill from height

**Source**: Arsenal's Stomp (canon since Mega Update, inherited from Team Fortress 2 / Typical Colors 2). Fall from ~91 studs onto an enemy head = instakill with a *spring* sound effect. Multiplies fall damage by 24× as outgoing.

**Input**: No new button — it's an emergent consequence of jumping/falling. We already have a jump; the innovation is making the *landing* weaponized.

**Feedback loop**: Airborne over an enemy → crosshair shows a red DOWN-chevron target lock → landing triggers spring-boing sound + cartoon shockwave ring + big "STOMP!" banner → enemy flattens. If you stomp from low altitude it does partial damage; from high it's insta-kill.

**Why sticky**: Converts Three.js's weakest combat dimension (vertical) into its most meme-able. Kids will deliberately climb boxes, rocket-jump up, and dive on bosses for a clean stomp kill. It also reads instantly in a kids' game — "land on head = bonk" needs no tutorial. Pairs naturally with the shooter's existing platform geometry.

**Port effort (S/M/L)**: **S**. We already track `player.velocity.y` and enemy collisions; add a check: if landing on an enemy with `|vy| > threshold`, deal vy² damage. Spring sound + ring decal = 20 lines.

**Risk**: Can feel cheap if geometry lets kids camp a rooftop. Limit it by requiring `vy < -12` so enemies have to be actively fallen onto, not stood on.

---

## 4. Domination & Revenge rivalry (personal nemesis system)

**Source**: Arsenal (explicit "DOMINATING"/"REVENGE" UI, +10 currency for revenge kill), inherited from TF2. Absent from our game but trivially portable to any solo-player format by using named enemy types.

**Input**: No input — emergent state. Kill same enemy type (or tagged elite) 4× without dying = you're DOMINATING it; die to it = it's your NEMESIS; kill the nemesis back = REVENGE bonus.

**Feedback loop**: Kill #4 on a given elite name ("Red Hat Boomer") → big pink banner "DOMINATING Red Hat Boomer" + distinct sound cue. That elite's next spawn has a red halo + nemesis tag over its head. When you finally kill it → "REVENGE!" banner in green + bonus combo / powerup. When they kill you → "NEW NEMESIS!" on the death screen showing their avatar.

**Why sticky**: Turns faceless wave-enemies into *characters*. Kids spontaneously narrate: "Oh no it's the yellow one again!" It's TF2's single most-copied UX for a reason — gives every run emergent drama without any scripted story.

**Port effort (S/M/L)**: **S**. Tag 3 enemy archetypes with persistent nicknames; keep a `kills[name]` / `deathsBy[name]` counter; swap sprite outline colour and add HUD banner when thresholds hit. ~40 lines.

**Risk**: Needs the game to be long enough per run for the rivalry arc to complete. If rounds are <90s, you never hit the 4-kill domination threshold. Solve by reducing threshold to 3 and including boss phases.

---

## 5. Round modifier / "random rule of the round"

**Source**: Bad Business Rapid Randomizer (random loadout every 30s to the whole lobby), Overclocked mode (must kill within a countdown or you die), Blade Ball Elementals (whole round has a themed ability pool), Doors Modifiers (per-run rule tweaks). Kids LOVE this — every round feels fresh without new content.

**Input**: Round-start screen shows a spinning slot machine of 3 modifier cards; kid presses `SPACE` to lock. Some modifiers are cross-cut (active for all) — no input needed, just announced.

**Feedback loop**: Between waves → screen dims → 3 cards flip: e.g. "LOW GRAVITY", "SNIPER-ONLY", "GIANT BULLETS", "NO RELOAD", "BOSS RUSH", "TIME ATTACK — kill within 3s or die (Overclocked)", "MIRROR — enemies shoot your last weapon back at you". Kid picks one (or it's chosen randomly with a big "THIS ROUND: LOW GRAVITY" banner) → round visibly transforms (gravity tween, bullet scale tween, HUD chip).

**Why sticky**: Huge replayability from tiny code. Five modifiers × 10 waves = 50 combinations that feel *custom*. Overclocked's "kill or die" countdown is particularly good for kids because it forces aggression and kills grinding / camping.

**Port effort (S/M/L)**: **M**. Need a modifier registry (scale gravity, scale bulletSize, force a weapon, toggle reload, add death-timer). Each modifier should be <30 lines. UI is the main work.

**Risk**: Some modifiers conflict (e.g. "no reload" + "sniper only" = can't aim fast enough). Hand-curate the roster; don't truly randomize across all pairs.

---

## 6. Playtime reward drip (session-based loot ticks)

**Source**: Blade Ball Playtime Rewards — at 5/10/15/20/25/30 min of *uninterrupted session play* you get a Sword Crate, 100 coins, Wheel Spin, 150 coins, another Wheel Spin, Premium Crate. Rewards RESET if you leave the server. Explicitly designed as anti-cherry-pick.

**Input**: None — timer + notification pop.

**Feedback loop**: Toast at top of screen at each checkpoint: "PLAYTIME +5 MIN — unlocked Blue Hat!" → click to equip → cosmetic visible next life. Progress bar sits in corner.

**Why sticky**: Creates a mini-goal for kids who were *about* to quit. "One more minute and I get the skin!" is a proven retention hook. Non-combat unlocks mean losing players also win.

**Port effort (S/M/L)**: **S**. `setInterval` + toast + localStorage of unlocked cosmetics (hat on butt-model, trail colour, muzzle-flash colour). No server needed.

**Risk**: Kids dad is a PM focused on NPS; make sure rewards are cosmetic + immediate, not "come back tomorrow" — that turns into grind-guilt.

---

## 7. Spotting / "mark the enemy" team ping

**Source**: Phantom Forces (Q to spot; ~25° cone raises arm, tags enemy with red dot through walls, team sees it, +25 Spot Bonus if ally kills). Ported verbatim into our game as a *solo* mechanic: spotting reveals weak points / boss HP bars.

**Input**: `Q` key. Point-and-mark animation, small cooldown (~2s).

**Feedback loop**: Press Q while aiming at an enemy → arm-raise anim → red diamond appears over enemy head + HP bar reveals + weakpoint highlight (crit box glows yellow). Spotted enemies take +15% damage for 4s. Sound: two-tone "bing-bong".

**Why sticky**: Gives kids a *verb other than shoot*. Information as a toy. It also surfaces our existing weakpoint/combo system — most kids never notice enemies have backs that take more damage; spotting teaches them. Converts a passive HUD into an active one.

**Port effort (S/M/L)**: **S**. Raycast from camera; closest tagged enemy gets a flag `spotted = true` for 4s; shader on spotted enemies adds red outline; damage multiplier read in damage pipeline.

**Risk**: Minimal. Could be perceived as "wall hacks" in PvP, but we're PvE so no issue.

---

## 8. Decoy / clone toss (Evade utility)

**Source**: Evade's Decoy item — places a stationary duplicate of you that enemies chase and destroy instead.

**Input**: `G` key. Throws a decoy at a crosshair point; it spawns for ~8 seconds or until shot ~N times.

**Feedback loop**: Press G → cute "fssht" puff of smoke → a grey silhouette of the butt-character appears at target spot → enemies within aggro range switch target and shoot the decoy → you flank and shoot them in the back. Decoy explodes in confetti when destroyed.

**Why sticky**: Expression + problem-solving — decoy becomes a puzzle tool as much as a weapon. Kids invent their own uses (decoy on a cliff edge, decoy behind a boss). Very low-skill floor; high-ceiling as strategy.

**Port effort (S/M/L)**: **S**. Clone the player mesh (grey material), push to a decoys array, AI priority targeting picks the closest of [player, decoys]. Cooldown ~20s.

**Risk**: If enemies are too dumb they ignore the decoy; if too smart they only shoot the decoy once. Script the aggro switch to always last 2s minimum.

---

## 9. Hiding spots (Doors-style safe crouch)

**Source**: Doors Hiding mechanic — E key enters a wardrobe/locker for up to 30s while a lethal entity (Rush) sweeps the corridor.

**Input**: `E` near marked spot (barrel, crate, bush). Animation plays; camera pulls inside; HUD shows stamina bar while hiding.

**Feedback loop**: Boss telegraphs a map-sweeping attack ("RUSH INCOMING" 4s warning + audio rumble) → kids scramble for a hide spot → press E → screen darkens and muffles audio → Rush sweeps past in a flash of light → exit with W → "SAFE!" banner.

**Why sticky**: Scary-safe loop. Kids LOVE controlled fear — the best-rated MM2 moments are the 2-3s of fake-out before a Rush. Our boss phases could borrow this: every 3rd wave the boss does a "you must hide" sweep.

**Port effort (S/M/L)**: **M**. Need marked hide-spot props per scene, an occlusion/safety flag, audio muffler, and at least one enemy attack type that *requires* hiding (deals full map damage otherwise). Integrates with boss phases.

**Risk**: Can slow combat pacing. Use sparingly — once per boss, not every wave.

---

## 10. Knife throw finisher (MM2 + Bad Business Infected Knife)

**Source**: MM2 Murderer's knife has a throw alt-fire; Bad Business Gun Game caps with Golden Knife + throwable variant; kids universally love the "throwing knife from cover" clip.

**Input**: Hold `V` or right-click while holding melee to wind up; release to throw. Pickup-able afterwards.

**Feedback loop**: Hold V → hand cocks back, sparkle trail on blade → release → knife flies in arc, rotating, audible "whoosh" → hits enemy → big red splash + "KNIFE!" kill feed icon + slight slow-mo (150ms). Knife sticks in ground and can be picked up with E.

**Why sticky**: Ranged melee is inherently satisfying — combines the risk of close combat with the precision of shooting. Clippable skill moment. Golden-Knife variant (unlocked at highest Gun Game tier) gives kids a power-fantasy finisher.

**Port effort (S/M/L)**: **S**. Spawn a projectile knife mesh with gravity + rotation; on hit, big damage + instakill on critical hit; leave a pickup token. 50 lines.

**Risk**: Recovering thrown knives can get fiddly. Give a 3s auto-return-to-hand if no pickup.

---

## Top 3 to steal

For a single-file ES-modules Three.js game aimed at a 7–10 year old, we want (a) minimum new code, (b) maximum new *feelings*, (c) no new input modes that collide with existing controls. The three highest-ROI picks:

### Pick A — Gun Game weapon ladder (Mechanic #1)
Biggest bang for buck. Turns our single-weapon shooter into a novelty-treadmill in ~80 lines. Every kill is a new toy. Pairs perfectly with the existing combo/magazine system — the ladder replaces magazine count as the visible progression within a round. Golden Knife at the top gives the son a meme-worthy finisher moment.

### Pick B — Round modifier slot machine (Mechanic #5)
The single best retention hook in modern Roblox shooters. Between waves, kid picks one of three round modifiers (low grav / sniper only / giant bullets / no reload / overclocked kill-timer). Multiplies replay value without new art; teaches the existing systems by stressing them individually. Low-grav wave alone turns our stomp-jump ceiling into an entire minigame.

### Pick C — Stomp ground-pound (Mechanic #3)
Smallest code change, biggest kinaesthetic surprise. Turns the existing vertical axis into a kill vector with literally one velocity check and a spring sound. Reads instantly ("bonk on head"), pairs beautifully with round modifier #5's low-grav option, and creates a second win condition a kid can brag about independent of shooting skill. Bonus: it's the gateway mechanic to later adding Rocket Jumping as a Mechanic-11 traversal verb without retrofitting.

Deliberately NOT picked for first cut: Domination/Revenge (needs persistent rival IDs we don't have yet — good phase-2), Parry (tight tuning, risk of kid-frustration on a first playthrough), Decoy (adds an AI targeting branch that complicates debugging), Playtime rewards (needs cosmetic system that doesn't exist yet), Hiding (risks pacing).
