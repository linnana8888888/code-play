# Code PLAY

An AI game studio where 37 specialized agents collaborate to build, playtest, and ship kid-friendly web and Roblox games — from a one-line brief to a live itch.io URL.

Not a framework. A studio. You describe a game, agents design it, build it, QA it, and publish it. You make the creative calls at human gates. They do the rest.

![Code PLAY Dashboard](docs/images/dashboard.png)

## How it works

```
"a butt-themed shooter where you dodge enemies and collect power-ups"
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  phased-producer pipeline — orchestrated live by Producer               │
│                                                                         │
│  ▸ acquire project lock (≤3 concurrent)  ▸ inject cross-game lessons    │
│                                                                         │
│  concept ── mechanics ── { style-research ∥ mechanic-research ∥ CD }    │
│      │          │                       │                               │
│      ▼          ▼                       ▼                               │
│  [gate]      [gate]               (parallel)                            │
│                                                                         │
│  look & feel ── tech plan ── build ── telemetry ── QA playtest          │
│      │             │           │          │            │                │
│      ▼             ▼         game_html  instrumented   ▼                │
│  [gate+kid-safety][gate]                           [gate+kid-safety]    │
│                                                                         │
│  code review ↻×3 ── peer review ── scaffold iteration ── publish prep   │
│                                                                  │      │
│                                                                  ▼      │
│                                                              [gate]     │
│                                                                  │      │
│                                           publish (idempotent) ──┤      │
│                                                    │             │      │
│                                                    ▼             ▼      │
│                                                 🎪 live      ↩ rollback │
│                                                    │                    │
│                                                    ▼                    │
│                                         record lessons → next run       │
│                                                                         │
│  ─── governance rail on every step ───                                  │
│  schema hard-block · peer review on-request · WS live status feed ·     │
│  handoff-summarizer briefs before each [gate]                           │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
🎪 Live on itch.io / gh-pages / Roblox — then iterate via playtest bot loop
```

Every `[gate]` is a moment where you review, approve, or redirect. A **handoff-summarizer** agent writes a short brief before each gate so you land on context. Between gates, agents work autonomously under the Producer orchestrator.

Full visual diagrams: [`docs/flowcharts/index.html`](docs/flowcharts/index.html) — open the file locally for interactive new-game / iterate tabs.

## Shipped games

| Title | Codename | Live itch build | Notes |
|-------|----------|-----------------|-------|
| Cheekshot | butt-shooting-game v8 (latest) | [itch.io](https://linnana8888888.itch.io/cheekshot) build #1636527 | session-time + achievements + 3D backdrop |
| Cheekshot | butt-shooting-game v6.1 | itch build #1626386 | mobile-responsive HUD, iOS AudioContext fix |
| Cheekshot | butt-shooting-game v4 | itch build #1623921 | XP gems, level-up modal, stomp |
| Cheekshot | butt-shooting-game v3 | itch build #1623215 | module split + playtest bot |
| Roblox Smoke Test | roblox-smoke-test v1 | [Roblox](https://www.roblox.com/games/126715565755517) (private) | orchestrator Roblox pipeline smoke |

Latest `main` @ `8f480f9` merges PR #3 (v8). v7 (aesthetic levels — per-level skydome+floor shaders, Toxic Swamp, Void Dimension) merged to main but superseded by v8 on itch.

## The agents

37 agents across 9 disciplines, each with a focused role and its own model routing:

| Discipline | Agents | What they do |
|-----------|--------|-------------|
| **Game Dev** | game-designer, game-audio-engineer, technical-artist, 3 roblox specialists | Mechanics, audio, art direction, Roblox Luau |
| **Design** | hud-designer, screen-flow-designer, player-researcher, juice-polisher, ux-designer | HUD layout, state machines, trend research, polish passes |
| **Engineering** | frontend-developer, code-reviewer, tech-lead, rapid-prototyper, gameplay-programmer, 5 Unity specialists | Web builds (Three.js/canvas), Unity C#, code review, tech plans |
| **Leadership** | creative-director, technical-director | Vision guardrails, architecture ownership |
| **Production** | producer, publisher, **handoff-summarizer** | Pipeline driver, itch.io/GH Pages/Roblox shipping, brief writer before each human gate |
| **Testing** | qa-engineer, game-performance-tester, game-release-gate, **kid-safety-reviewer** | Headless playtests, perf budgets, ship/no-ship gate, kid-safety checks |
| **Analytics** | telemetry-engineer, metrics-dashboard-builder, analytics-reporter, player-feedback-synthesizer | Instrumentation, dashboards, postmortems, comment digests |
| **Research** | style-researcher, mechanic-researcher | Visual references, mechanic teardowns (run in parallel) |
| **Shared** | common base template | Shared conventions across agents |

Agents route through **Anthropic** (Claude Opus/Sonnet/Haiku), **OpenAI** (GPT-5 via LEGO proxy), and **oMLX** (local Qwen/Gemma — text-only tasks) with automatic fallback chains. Each agent gets scoped tools (lean `core` tier + role-specific extras) and curated skills (brainstorming for designers, TDD for devs, data-viz for analytics, etc.).

## Pipelines

| Pipeline | Purpose |
|----------|---------|
| `phased-producer` | Full game production: concept to live URL with human gates at every phase |
| `iterate_artifact` | Cyclic improvement loop: playtest bot runs 5x → postmortem → 4 parallel proposals → you pick → implement → repeat |

## The iteration loop

After a game ships, `iterate_artifact` takes over. A headless playtest bot (`playtest_bot.mjs`) drives the game through `window.GameAPI`, collects telemetry, and feeds it into a cyclic pipeline:

```
live game v{n} on itch.io
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  iterate_artifact — cyclic improvement loop                             │
│                                                                         │
│  ▸ acquire project lock   ▸ inject cross-game lessons                   │
│  ▸ qa-engineer snapshots baseline metrics (regression guard)            │
│                                                                         │
│  generate bot ── playtest ×5 ── postmortem                              │
│      │              │              │                                    │
│      ▼              ▼              ▼                                    │
│  bot_gen_{{tag}}  telemetry   per-level grade                           │
│                                                                         │
│  ─── propose (parallel, all read postmortem) ───                        │
│     ┌─────────┬─────────┬──────────┬──────────┐                         │
│     │ designer│ hud/ux  │ art/juice│ code/perf│                         │
│     └─────────┴─────────┴──────────┴──────────┘                         │
│                      │                                                  │
│                      ▼                                                  │
│              [synthesis gate]  ◄── handoff-summarizer brief             │
│                      │                                                  │
│                      ▼                                                  │
│              CD proposal check (Opus) ── budget estimate                │
│                      │                                                  │
│                      ▼                                                  │
│  implement ── code review ↻×3 ── peer review ── regression test         │
│  (per-level difficulty tuning)                     │                    │
│                                                    │                    │
│               ┌────────────────────────────────────┤                    │
│               ▼                                    ▼                    │
│      ↩ loop back to playtest             re-publish (idempotent)        │
│      (or halt if budget exhausted)                 │                    │
│                                                    ▼                    │
│                                             🎪 updated build            │
│                                                    │                    │
│                                                    ▼                    │
│                                    record cycle lessons → next run      │
│                                                                         │
│  ─── governance rail on every step ───                                  │
│  schema hard-block · peer review on-request · WS live status feed ·     │
│  before/after regression guard (auto-REVISE on regress)                 │
└─────────────────────────────────────────────────────────────────────────┘
```

0. **Cycle entry** — Producer acquires project lock, cross-game lessons injected, qa-engineer snapshots baseline metrics for regression guard
1. **Generate bot** — QA engineer reads game source, writes a game-specific bot (not a random walk)
2. **Playtest** — bot runs 5x, writes telemetry JSON
3. **Postmortem** — analytics-reporter grades each GOALS.md target (hit/miss) with per-level breakdown
4. **Propose** — 4 agents in parallel (designer, UX, artist, prototyper) each pitch 5-8 ideas
5. **Human picks** — you select which ideas to implement (handoff-summarizer briefs you first)
6. **CD check + budget estimate** — creative-director verdict, tech-lead forecasts token cost and proposes engineer split
7. **Implement** — frontend-developer applies changes with per-level difficulty tuning (single or parallel engineers)
8. **Review** — code-reviewer (loop ×3) + peer review through message bus
9. **Before/after regression** — if any baseline metric regresses in v{n+1}, auto-REVISE before shipping
10. **Outcome** — loop back to playtest OR idempotent re-publish (noop if ref already shipped)
11. **Record lessons** — cycle hits/misses written to `agent_lessons.py` for future runs

The bot and game communicate through a standardized `window.GameAPI` contract (start, getState, getSnapshot, pickCard) so one bot drives any game. On cycle 1, the QA engineer generates a game-specific bot using entity screen coordinates from `getSnapshot()`. On subsequent cycles, the existing bot is reused or tuned.

## Architecture

```
FastAPI orchestrator (Python)
├── Agent Runtime ───────── model-agnostic tool-use loop, budget enforcement, session persistence
├── LLM Router ──────────── Anthropic / OpenAI / oMLX with fallback chains
├── Tool Executor ───────── 2-tier governance (core 19 tools / builtin 35), MCP bridge, mcp:<server> prefix filtering
├── Task Queue ──────────── SQLite-backed, dependency resolution, atomic checkout, per-project locking (max 3 concurrent games)
├── Pipeline Engine ─────── declarative YAML pipelines with human gates + producer live orchestration
├── Producer Orchestrator ─ drives each phase, writes handoff briefs, streams status via WebSocket feed
├── Message Bus ─────────── agent-to-agent peer review protocol (structured critique + reply cycles)
├── Project Memory ──────── per-game SQLite store (artifacts, decisions, feedback) + schema hard-block on write
├── Agent Lessons ───────── cross-game lesson store: failures are distilled into reusable rules for future runs
├── Skill Registry ──────── 445 available skills, role-curated injection (18 agents get 1-4 skills each)
├── Path Rules ──────────── auto-inject domain rules when agents touch matching files
├── Artifact Templates ──── 16 structured output templates across 9 categories
└── React Dashboard ─────── real-time observability, Kanban board, governance approvals, Producer Feed panel
```

## Quick start

```bash
# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your API keys
python3 -m uvicorn src.main:app --port 8080

# Dashboard (dev)
cd dashboard && npm install && npm run dev
```

- Dashboard: http://localhost:8080/app
- API docs: http://localhost:8080/docs
- 89 REST endpoints + WebSocket feed (incl. Producer live status stream)

## Game index

Games live in `games/*.yaml` — each file tracks the source repo, version history, and publish status:

```yaml
slug: butt-shooting-game
title: Butt Shooting Game
source:
  kind: external
  repo: https://github.com/linnana8888888/butt-shooting-game
versions:
  - label: v3
    ref: c1fa6d8
    status: shipped
    shipped_as: Cheekshot
    published:
      itch: https://linnana8888888.itch.io/cheekshot
```

## Project structure

```
code-play/
├── agents/          # 37 agent definitions (.md) across 9 disciplines
├── artifacts/       # Per-game build artifacts, publish assets, project state
├── config/
│   ├── agents.yaml          # Model routing, scoped tools + skills, budgets per agent
│   ├── governance.yaml      # Tool tiers: core (19), builtin (35), restricted, blocked
│   ├── pipelines.yaml       # 6 declarative pipelines
│   ├── path_rules.yaml      # Auto-injected domain rules
│   ├── artifact_schemas.yaml # Required fields per memory artifact key (hard-block on write)
│   └── artifact_templates.yaml
├── dashboard/       # React + Vite + Tailwind — real-time studio UI (incl. ProducerFeed panel)
├── docs/
│   ├── flowcharts/  # Pipeline diagrams (new game + iterate_artifact)
│   └── qa/          # Phase QA reports
├── games/           # Game index (YAML per game, version + publish tracking)
├── skills/          # Injectable knowledge (.md) — asset sources, coding standards
├── src/
│   ├── main.py                           # FastAPI app (89 endpoints)
│   ├── runtime/                          # Agent runtime, LLM router, tool executor, MCP bridge
│   ├── orchestrator/
│   │   └── producer_orchestrator.py      # Drives pipelines, live status stream
│   ├── communication/
│   │   └── message_bus.py                # Agent-to-agent peer review protocol
│   ├── memory/
│   │   └── agent_lessons.py              # Cross-game lesson store
│   ├── iteration/                        # Scaffolder, bootstrap, contract validation, per-level difficulty tuning
│   └── models/                           # Pydantic models
├── templates/       # 16 artifact output templates (concept, design, QA, publish...)
└── tests/           # Unit + integration + live + Phase 1-4 regression suites
```

## Quality gates

Every artifact written to project memory is validated against `config/artifact_schemas.yaml` — required fields are **hard-blocked** at write time (not just warned). Producer re-queues the upstream agent on schema miss.

The **Creative Director** agent issues APPROVE / CONCERNS / REJECT verdicts after every concept, mechanics, and look-and-feel phase. A REJECT automatically re-queues the upstream agent (max 2 retries before escalating to a human gate).

The **playtest bot** acts as a hard gate: if average session length < 90s or level-1 death rate > 3/min, the build is automatically sent back for revision without requiring human review.

A **kid-safety-reviewer** agent (Claude Haiku) runs before the LAF and QA human gates, checking every build against a 7-point checklist for ages 9-12 (violence, controls, readability, humor tone, session length, difficulty, language). Game-designer carries the same 9-12 constraints into concept + mechanics output.

The **handoff-summarizer** agent writes a short brief before every human gate so the reviewer lands on context, not raw artifacts.

**Agent peer review** — any agent can route a structured critique to a peer via the message bus; the peer replies inline before the original task completes. Used for cross-discipline sanity checks (e.g., designer ↔ tech-lead on feasibility).

**Cross-game lessons** — every failed run distills into a reusable rule in `src/memory/agent_lessons.py`; future game-designer runs read matching lessons at task start.

**Publish idempotency** — re-running a publish step is a no-op if the artifact already shipped at that ref; rollback protocol cleans partial ships if an intermediate step fails.

**Per-project locking** — at most 3 games build concurrently; further launches queue until a slot frees. Prevents tool/MCP contention.

**Per-level difficulty tuning** in `iterate_artifact` applies targeted tweaks to individual levels after postmortem, with a before/after regression test guarding against global regressions.

## Tests

```bash
# Unit + integration tests
python3 -m pytest tests/ -v

# Live integration tests (requires running service)
CODE_PLAY_URL=http://localhost:8080 python3 -m pytest tests/test_integration_live.py -v
```

**Test health (phase 4):** Phase 1, 2, 3, 4 suites all green; Phase 3 QA fixed the 3 pre-existing failures from phase1-improvements. New coverage: producer orchestrator, cross-game lessons, publish idempotency, peer review, multi-game parallelism, per-level iteration.

## Changelog

### phase4 (2026-04-25)
- **Agent peer-review protocol** — message bus lets agents critique each other before task completion; structured request/reply
- **Per-project locking** — max 3 concurrent games; further launches queue; test suite `test_multi_game_parallelism.py`
- **Tool executor** refactor — cleaner boundary for peer-review calls

### phase3 (2026-04-25)
- **Cross-game lesson store** (`src/memory/agent_lessons.py`) — distill failures into reusable rules injected into future runs
- **Game-designer kids 9-12 constraints** — baked into concept + mechanics prompts
- **Per-level difficulty tuning** in `iterate_artifact` with before/after regression test
- **Publish idempotency** — re-running a shipped publish is a no-op; rollback protocol for partial publishes
- **Phase 3 test suite** — `test_phase3_iteration.py`, `test_cross_game_lessons.py`, `test_publish_idempotency.py` + 3 pre-existing test fixes

### phase2 (2026-04-25)
- **Producer as live orchestrator** — `producer_orchestrator.py` drives pipelines, emits WebSocket status stream
- **Producer Feed panel** in React dashboard (`dashboard/src/components/producer/ProducerFeed.tsx`)
- **Handoff-summarizer agent** — short brief written before every human gate so reviewers land on context
- **Parallelized research** — style-researcher + mechanic-researcher run concurrently
- **Model tiering audit** — per-agent model routing rebalanced for cost vs quality
- **Schema hard-block** — artifact writes now reject on malformed structure (was warning-only)
- **Pipeline flowcharts** (`docs/flowcharts/index.html`) for both pipelines
- **Phase 2 test suite** (`tests/test_phase2.py`) + e2e adjustments for handoff-summarizer steps

### phase1-improvements (2026-04-25)
- **Artifact schema validation** — `config/artifact_schemas.yaml` defines required fields for all 11 memory artifact keys; `task_validator.py` warns on malformed writes
- **CD verdict enforcement** — Creative Director REJECT now re-queues upstream agent (max 2 retries → human escalation)
- **Playtest hard gate** — auto-REVISE if session < 90s or death rate > 3/min in level 1
- **Kid-safety-reviewer agent** — Haiku-powered 7-point safety check before LAF and QA gates
- **Model routing fix** — oMLX removed from fallback chains for all tool-use agents; replaced with Claude Haiku
- **Bug fix** — `workspace.py` git worktree cleanup fallback now runs correctly on git failure
- **+24 live integration tests** covering Phase 1 wiring end-to-end

## License

Private repository.
