# Agent Coordination Map

Single source of truth for which agents participate in which pipeline phases,
who delegates to whom, and which agents are available but not yet wired in.

## Pipeline: phased-producer (22 steps)

### Phase 1 — Concept (steps 1-3)

```
concept ──→ gate-concept ──→ cd-concept-check
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| concept | **game-designer** | Drafts 3 concept directions (pitch, core loop, feel) |
| gate-concept | *human* | Picks one direction |
| cd-concept-check | **creative-director** | Validates core fantasy, pillars, unique hook, age-appropriateness |

### Phase 2 — Mechanics (steps 4-6)

```
mechanics ──→ gate-mechanics ──→ cd-mechanics-check
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| mechanics | **game-designer** | Expands concept into player verbs, progression, win/lose, signature systems |
| gate-mechanics | *human* | Reviews mechanics doc |
| cd-mechanics-check | **creative-director** | Validates MDA alignment, loop structure, flow state, kid-appropriate tuning |

### Phase 3 — Visual Identity (steps 7-10)

```
style-research ──→ look-and-feel ──→ gate-laf ──→ cd-laf-check
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| style-research | **style-researcher** | Finds 6-10 reference games, synthesizes palette + character design + anti-patterns |
| look-and-feel | **technical-artist** | Grounds visual direction with concrete asset picks, palette, art style, audio tone |
| gate-laf | *human* | Reviews LAF brief against style research |
| cd-laf-check | **creative-director** | Validates visual/audio coherence with pillars, age-appropriateness |

### Phase 4 — Technical Planning (steps 11-12)

```
tech-plan ──→ gate-tech
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| tech-plan | **tech-lead** | Engine choice, file layout, asset strategy, input model, game loop, test hooks |
| gate-tech | *human* | Approves stack and structure |

### Phase 5 — Build + Instrumentation (steps 13-15)

```
build ──→ telemetry-spec ──→ telemetry-instrument
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| build | **frontend-developer** | Builds playable web prototype from all approved artifacts |
| telemetry-spec | **telemetry-engineer** | Maps player verbs to 8-event catalogue, defines payload schemas, identifies KPIs |
| telemetry-instrument | **frontend-developer** | Wires telemetry events into game code, preserves test hooks |

### Phase 6 — Quality (steps 16-19)

```
qa-playtest ──→ gate-qa ──→ review ──→ scaffold-iteration
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| qa-playtest | **qa-engineer** | Headless playtest: console errors, test hooks, per-verb verification, screenshots |
| gate-qa | *human* | Reviews QA report + plays the game |
| review | **code-reviewer** | Lint, performance, security review (code quality only, not gameplay) |
| scaffold-iteration | **rapid-prototyper** | Writes iteration kit: GOALS.md, ITERATION_CONTRACT.md, playtest_bot.mjs |

### Phase 7 — Publish (steps 20-22)

```
publish-prep ──→ gate-publish ──→ publish
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| publish-prep | **publisher** | Pre-flight checklist, title candidates, listing metadata, packaging |
| gate-publish | *human* | Final ship gate — slug, title, metadata, target list |
| publish | **publisher** | Push to itch.io / gh-pages / Roblox, verify liveness, write manifest |

### Agent Summary — phased-producer

| Agent | Steps | Appearances |
|-------|-------|-------------|
| game-designer | concept, mechanics | 2 |
| creative-director | cd-concept-check, cd-mechanics-check, cd-laf-check | 3 |
| style-researcher | style-research | 1 |
| technical-artist | look-and-feel | 1 |
| tech-lead | tech-plan | 1 |
| frontend-developer | build, telemetry-instrument | 2 |
| telemetry-engineer | telemetry-spec | 1 |
| qa-engineer | qa-playtest | 1 |
| code-reviewer | review | 1 |
| rapid-prototyper | scaffold-iteration | 1 |
| publisher | publish-prep, publish | 2 |
| **Total unique agents** | | **11** |

---

## Pipeline: iterate_artifact (cyclic, 8 steps per cycle)

### Phase A — Measure (step 1)

```
playtest
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| playtest | **qa-engineer** | Runs 5 headless playthroughs via iteration_runner, aggregates telemetry |

### Phase B — Analyze (step 2)

```
postmortem
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| postmortem | **analytics-reporter** | Writes per-goal hit/miss report, top 3 problems ranked by player-impact |

### Phase C — Propose (steps 3-6, parallel)

```
propose-designer ──┐
propose-ux ────────┼──→ (all run in parallel)
propose-artist ────┤
propose-proto ─────┘
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| propose-designer | **game-designer** | One mechanics-level change targeting the biggest miss |
| propose-ux | **hud-designer** | One HUD/flow/legibility change (not mechanics, not FX) |
| propose-artist | **technical-artist** | One art/feedback/readability change (silhouette, palette, juice) |
| propose-proto | **frontend-developer** | One code-level change (refactor, tuning, bug fix, perf) |

### Phase D — Select + Guard (steps 7-8)

```
synthesis_gate ──→ cd-proposal-check
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| synthesis_gate | *human* | Picks one proposal from the four |
| cd-proposal-check | **creative-director** | Validates the chosen change preserves pillars, emotional arc, kid tone |

### Phase E — Implement (step 9, then loops to Phase A)

```
implement ──→ (cycle back to playtest)
```

| Step | Agent | Role in Phase |
|------|-------|---------------|
| implement | **frontend-developer** | Applies the approved proposal, saves new build, commits to iteration branch |

### Agent Summary — iterate_artifact

| Agent | Steps | Appearances |
|-------|-------|-------------|
| qa-engineer | playtest | 1 |
| analytics-reporter | postmortem | 1 |
| game-designer | propose-designer | 1 |
| hud-designer | propose-ux | 1 |
| technical-artist | propose-artist | 1 |
| frontend-developer | propose-proto, implement | 2 |
| creative-director | cd-proposal-check | 1 |
| **Total unique agents** | | **7** |

---

## Orchestration Layer (not a pipeline step)

| Agent | Role |
|-------|------|
| **producer** | Auto-spawns on project creation. Runs the pipeline, tracks step completion, bumps stalled gates, enforces scope. Not a step — it IS the orchestrator. |

---

## Delegation Hierarchy

```
human
├── producer (orchestrates all pipelines)
├── creative-director (creative authority, reviews at 3 create gates + 1 iterate gate)
│   ├── game-designer (mechanics, balance, systems)
│   ├── technical-artist (visual identity, asset selection)
│   └── style-researcher (reference gathering, competitive positioning)
├── technical-director (architecture authority, escalation target)
│   ├── tech-lead (per-project tech plans, routes to specialists)
│   │   ├── frontend-developer (web builds, instrumentation, iteration implementation)
│   │   ├── gameplay-programmer (Unity/Roblox C# implementation)
│   │   └── unity-specialist (Unity patterns, delegates to sub-specialists)
│   │       ├── unity-dots-specialist
│   │       ├── unity-shader-specialist
│   │       ├── unity-addressables-specialist
│   │       └── unity-ui-specialist
│   └── code-reviewer (code quality, security)
├── qa-engineer (playtesting, verification)
├── analytics-reporter (postmortems, metric analysis)
│   └── telemetry-engineer (event specs, instrumentation design)
├── publisher (packaging, listing, deployment, liveness)
├── rapid-prototyper (iteration scaffolding)
└── hud-designer (HUD/UX proposals in iterate)
```

## Conflict Resolution

| Conflict Type | Escalation Target |
|---|---|
| Design vs. technical feasibility | technical-director |
| Design vs. creative vision | creative-director |
| Two agents disagree on scope | producer |
| Performance budget violation | technical-director → tech-lead |
| Kid-safety or age-appropriateness | creative-director (overrides all) |

---

## Unwired Agents (available, not in any pipeline step)

These agents exist in `agents/` but are not assigned to any pipeline step.
They are available for ad-hoc use, future pipelines, or pipeline enrichment.

### Design Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| juice-polisher | Screen shake, particles, hit-stop, feedback signals | Add as step between build and QA, or as iterate proposer |
| screen-flow-designer | Screen flow diagrams, navigation architecture | Add to concept or mechanics phase for UI-heavy games |
| player-researcher | Player interviews, competitive analysis, persona development | Pre-concept research phase |

### Analytics Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| metrics-dashboard-builder | Builds HTML dashboards from telemetry JSON | Post-iterate visualization |
| player-feedback-synthesizer | Synthesizes external feedback (comments, reviews) into themes | Iterate enrichment — add alongside postmortem |

### Engineering Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| gameplay-programmer | Unity/Roblox C# implementation | Alternative to frontend-developer for non-web builds |
| unity-specialist | Unity architecture, MonoBehaviour vs DOTS routing | Tech-plan phase for Unity projects |
| unity-dots-specialist | ECS, Jobs, Burst optimization | Unity performance phase |
| unity-shader-specialist | Shader Graph, VFX Graph, render pipeline | Unity visual quality phase |
| unity-addressables-specialist | Asset loading, memory lifecycle, content updates | Unity build optimization |
| unity-ui-specialist | UI Toolkit, UGUI, data binding | Unity UI implementation |

### Game Development Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| game-audio-engineer | Sound design, music, mix | LAF phase or post-build audio pass |
| roblox-avatar-creator | Avatar customization, UGC accessories | Roblox-specific pipeline |
| roblox-experience-designer | Roblox game design (already in roblox-experience pipeline) | — |
| roblox-systems-scripter | Luau implementation (already in roblox-experience pipeline) | — |

### Testing Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| game-performance-tester | FPS, memory, load time profiling | Post-build performance gate |
| game-release-gate | Pre-release checklist verification | Between review and publish-prep |

### Research Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| mechanic-researcher | Researches published game mechanics for inspiration | Pre-concept or design phase |

### Leadership Agents
| Agent | Purpose | Pipeline Opportunity |
|-------|---------|---------------------|
| technical-director | Architecture authority | Escalation only (not a pipeline step) |

---

## Cross-Pipeline Agent Overlap

Agents that appear in BOTH pipelines:

| Agent | Create Role | Iterate Role |
|-------|-------------|--------------|
| game-designer | Concept + mechanics author | Mechanics proposal |
| creative-director | Gate reviewer (×3) | Proposal reviewer (×1) |
| technical-artist | LAF brief author | Art/feedback proposal |
| frontend-developer | Build + instrumentation | Code proposal + implementation |
| qa-engineer | QA playtest | Iteration playtest |
