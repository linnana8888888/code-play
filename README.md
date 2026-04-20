# Code PLAY

An AI game studio where 34 specialized agents collaborate to build, playtest, and ship kid-friendly web and Roblox games — from a one-line brief to a live itch.io URL.

Not a framework. A studio. You describe a game, agents design it, build it, QA it, and publish it. You make the creative calls at human gates. They do the rest.

![Code PLAY Dashboard](docs/images/dashboard.png)

## How it works

```
"a butt-themed shooter where you dodge enemies and collect power-ups"
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  phased-producer pipeline (22 steps, human-gated)       │
│                                                         │
│  concept ── mechanics ── style research ── look & feel  │
│      │          │              │                │       │
│      ▼          ▼              ▼                ▼       │
│  [gate]     [gate]                          [gate]      │
│                                                         │
│  tech plan ── build ── telemetry ── QA playtest         │
│      │          │          │            │               │
│      ▼          ▼          ▼            ▼               │
│  [gate]    game_html_v1  instrumented  [gate]           │
│                                                         │
│  code review ── scaffold iteration ── publish prep      │
│                                            │            │
│                                            ▼            │
│                                        [gate] ── ship   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
🎪 Live on itch.io — then iterate via playtest bot loop
```

Every `[gate]` is a moment where you review, approve, or redirect. Between gates, agents work autonomously.

## Shipped games

| Title | Codename | Live URL |
|-------|----------|----------|
| Cheekshot | butt-shooting-game v3 | [itch.io](https://linnana8888888.itch.io/cheekshot) |
| Roblox Smoke Test | roblox-smoke-test v1 | [Roblox](https://www.roblox.com/games/126715565755517) (private) |

## The agents

34 agents across 8 disciplines, each with a focused role and its own model routing:

| Discipline | Agents | What they do |
|-----------|--------|-------------|
| **Game Dev** | game-designer, game-audio-engineer, technical-artist, 3 roblox specialists | Mechanics, audio, art direction, Roblox Luau |
| **Design** | hud-designer, screen-flow-designer, player-researcher, juice-polisher, ux-designer | HUD layout, state machines, trend research, polish passes |
| **Engineering** | frontend-developer, code-reviewer, tech-lead, rapid-prototyper, gameplay-programmer, 5 Unity specialists | Web builds (Three.js/canvas), Unity C#, code review, tech plans |
| **Leadership** | creative-director, technical-director | Vision guardrails, architecture ownership |
| **Production** | producer, publisher | Pipeline driver, itch.io/GH Pages/Roblox shipping |
| **Testing** | qa-engineer, game-performance-tester, game-release-gate | Headless playtests, perf budgets, ship/no-ship gate |
| **Analytics** | telemetry-engineer, metrics-dashboard-builder, analytics-reporter, player-feedback-synthesizer | Instrumentation, dashboards, postmortems, comment digests |
| **Research** | style-researcher, mechanic-researcher | Visual references, mechanic teardowns |

Agents route through **Anthropic** (Claude Opus/Sonnet), **OpenAI** (GPT-5), and **oMLX** (local Qwen/Gemma) with automatic fallback chains.

## Pipelines

| Pipeline | Purpose |
|----------|---------|
| `phased-producer` | Full game production: concept to live URL with human gates at every phase |
| `iterate_artifact` | Cyclic improvement loop: playtest bot runs 5x → postmortem → 4 parallel proposals → you pick → implement → repeat |

## The iteration loop

After a game ships, `iterate_artifact` takes over. A headless playtest bot (`playtest_bot.mjs`) drives the game through `window.GameAPI`, collects telemetry, and feeds it into a cyclic pipeline:

1. **Playtest** — bot runs 5x, writes telemetry JSON
2. **Postmortem** — analytics-reporter grades each GOALS.md target (hit/miss)
3. **Propose** — 4 agents in parallel (designer, UX, artist, prototyper) each pitch 5-8 ideas
4. **Human picks** — you select which ideas to implement
5. **Budget estimate** — tech-lead forecasts token cost and proposes engineer split
6. **Implement** — frontend-developer applies changes (single or parallel engineers)
7. **Loop** — back to playtest with the new build

The bot and game communicate through a standardized `window.GameAPI` contract (start, getState, getSnapshot, pickCard) so one bot drives any game.

## Architecture

```
FastAPI orchestrator (Python)
├── Agent Runtime ─── model-agnostic tool-use loop, budget enforcement, session persistence
├── LLM Router ────── Anthropic / OpenAI / oMLX with fallback chains
├── Tool Executor ──── 16+ builtin tools, 4-tier governance, MCP bridge to Claude Code plugins
├── Task Queue ────── SQLite-backed, dependency resolution, atomic checkout
├── Pipeline Engine ── declarative YAML pipelines with human gates
├── Project Memory ── per-game SQLite store (artifacts, decisions, feedback)
├── Skill Registry ── injectable .md skills with permission model
├── Path Rules ────── auto-inject domain rules when agents touch matching files
├── Artifact Templates ─ 16 structured output templates across 9 categories
└── React Dashboard ── real-time observability, Kanban board, governance approvals
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
- 70 REST endpoints + WebSocket feed

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
├── agents/          # 34 agent definitions (.md) across 8 disciplines
├── artifacts/       # Per-game build artifacts, publish assets, project state
├── config/
│   ├── agents.yaml      # Model routing, tools, budgets per agent
│   ├── pipelines.yaml   # 6 declarative pipelines
│   ├── path_rules.yaml  # Auto-injected domain rules
│   └── artifact_templates.yaml
├── dashboard/       # React + Vite + Tailwind — real-time studio UI
├── docs/            # Design doc, iteration contract, session logs
├── games/           # Game index (YAML per game, version + publish tracking)
├── skills/          # Injectable knowledge (.md) — asset sources, coding standards
├── src/
│   ├── main.py              # FastAPI app (70 endpoints)
│   ├── runtime/             # Agent runtime, LLM router, tool executor, MCP bridge
│   ├── orchestrator/        # Registry, task queue, pipeline engine
│   ├── iteration/           # Scaffolder, bootstrap, contract validation
│   └── models/              # Pydantic models
├── templates/       # 16 artifact output templates (concept, design, QA, publish...)
└── tests/           # Integration + unit tests
```

## Tests

```bash
python3 -m pytest tests/ -v
```

## License

Private repository.
