# Code PLAY

Multi-agent game studio platform. Specialized AI agents collaborate autonomously to build web/3D games (Three.js, Pixi.js, Phaser, Babylon.js).

## Architecture

Centralized FastAPI orchestrator with:

- **Agent Registry** — 21 specialized agents across game-dev, engineering, and testing categories
- **Agent Runtime** — model-agnostic tool-use loop with budget enforcement, session persistence, goal ancestry, and skill injection
- **LLM Router** — OpenRouter, oMLX (local Qwen3.5), Anthropic direct
- **Tool Executor** — 16 builtin tools, 4-tier governance (builtin/standard/restricted/blocked), workspace-aware path resolution
- **Task Queue** — SQLite-backed with dependency resolution and atomic checkout (race-condition safe)
- **Communication Bus** — project channels, @-mentions, blocking human escalation
- **Project Memory** — per-game SQLite knowledge store (decisions, artifacts, feedback)
- **Session Store** — save/resume agent conversations across runs
- **Workspace Manager** — git worktree (or directory copy) per agent instance
- **Skill Registry** — `.md` skill definitions with builtin/restricted permission model
- **React Dashboard** — real-time observability, agent lifecycle, governance approvals

## Quick Start

```bash
# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
python -m uvicorn src.main:app --port 8080

# Dashboard (dev)
cd dashboard
npm install
npm run dev
```

Dashboard: http://localhost:8080/app  
API docs: http://localhost:8080/docs

## Dashboard

Dark-themed React dashboard served at `/app` with:

| View | Description |
|------|-------------|
| **Studio Overview** | Stats cards, project grid, live WebSocket activity feed, pipeline launcher |
| **Agent Roster** | 21 agents by category, spawn with one click, instance table with cost/budget tracking |
| **Task Board** | 4-column Kanban (pending/assigned/running/done), create tasks per project |
| **Channels** | Slack-like chat per project channel, real-time message polling |
| **Governance** | Pending approval queue, skill cards, audit log with decision badges |
| **Project View** | Combined tasks + agents + channels for a single project |

**Stack:** Vite + React 18 + TypeScript + Tailwind CSS v4

## API

37+ REST endpoints + WebSocket feed. Key routes:

```
GET    /api/health                    # Server health + provider status
GET    /api/stats                     # Dashboard statistics

POST   /api/projects                  # Create project (with goal)
GET    /api/projects                  # List projects
GET    /api/projects/:id              # Get project

GET    /api/agents/definitions        # 21 agent definitions
POST   /api/agents/spawn              # Spawn agent instance
GET    /api/agents/instances          # List running instances
POST   /api/agents/:id/terminate      # Stop agent
POST   /api/agents/:id/resume         # Resume from saved session
GET    /api/agents/:id/cost           # Per-agent cost breakdown

POST   /api/tasks                     # Create task
GET    /api/tasks?project_id=...      # List tasks
POST   /api/tasks/:id/assign          # Assign to agent (atomic checkout)

POST   /api/messages                  # Post to channel
GET    /api/messages                  # Read channel messages
GET    /api/messages/channels          # List channels

GET    /api/governance/approvals      # Pending tool/skill approvals
GET    /api/governance/log            # Audit trail
GET    /api/skills                    # Available skills
POST   /api/skills/:id/approve        # Approve skill for agent type

POST   /api/pipelines/:name/run       # Launch pipeline (full-game, art, qa-sweep)
WS     /ws                            # Real-time event stream
```

## Tests

```bash
python -m pytest tests/test_e2e.py -v
```

35 integration tests covering health, projects, tasks, agents, messages, governance, budget enforcement, atomic checkout, goal ancestry, session persistence, workspaces, and skills.

## Design

See [docs/design.md](docs/design.md) for the full architecture spec.

## Status

- Phase 1 (Foundation) — complete
- Phase 2a (Backend Hardening) — complete
- Phase 2b (React Dashboard) — complete
