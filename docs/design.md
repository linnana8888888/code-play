# Code PLAY — Multi-Agent Game Studio Platform

**Date:** 2026-04-15
**Author:** Claude + dknanlin
**Status:** Approved for implementation

---

## Vision

A centralized multi-agent platform ("Code PLAY Studio") where specialized AI agents autonomously collaborate to build simple web/3D games. Agents work individually or as teams, communicate through project channels, share a governed tool pool, and route through multiple LLM providers. The human (you) evaluates output, makes key decisions, and approves new tool additions.

**Initial focus:** Gaming studio producing web games (Three.js / Roblox Studio).

---

## Architecture Overview

```
+----------------------------------------------------------------------+
|                         CODE PLAY STUDIO                              |
|                    FastAPI Orchestrator (Python)                       |
|                                                                       |
|  +----------------------------------------------------------------+  |
|  |                    ORCHESTRATOR LAYER                            |  |
|  |                                                                 |  |
|  |  Agent Registry | Task Queue | Pipeline Engine | Governance     |  |
|  +-------+-----------------------------+--------------------------+  |
|          |                              |                            |
|  +-------v-------------------------------------------------------------+
|  |                    AGENT RUNTIME LAYER                            |  |
|  |                                                                   |  |
|  |  Agentic tool-use loop (model-agnostic):                         |  |
|  |                                                                   |  |
|  |  +----------+    +-----------+    +--------------+               |  |
|  |  |  LLM     |--->|  Tool     |--->|  Tool        |--+            |  |
|  |  |  Call     |    |  Parser   |    |  Executor    |  |            |  |
|  |  |          |<---|           |<---|              |--+            |  |
|  |  +----+-----+    +-----------+    +------+-------+               |  |
|  |       |                                  |                        |  |
|  |  +----+------------------+    +----------+------------+          |  |
|  |  |   LLM Router          |    |   Shared Tool Pool     |          |  |
|  |  |                       |    |                        |          |  |
|  |  |  OpenRouter (remote)  |    |  file_read/write       |          |  |
|  |  |  oMLX (local)         |    |  bash_execute          |          |  |
|  |  |  Anthropic (direct)   |    |  git_operations        |          |  |
|  |  |  Fallback chains      |    |  web_search            |          |  |
|  |  |  Model selection      |    |  channel_post/read     |          |  |
|  |  |                       |    |  escalate              |          |  |
|  |  +-----------------------+    |  project_memory_*      |          |  |
|  |                               |  deploy_preview        |          |  |
|  |                               |  -- built-in -----     |          |  |
|  |                               |  [user_skill_X] <- ok  |          |  |
|  |                               |  [new_plugin]   <- ask |          |  |
|  |                               +------------------------+          |  |
|  +-------------------------------------------------------------------+  |
|                                                                       |
|  +---------------+  +---------------+  +----------------+             |
|  | Project       |  | Observability |  | Communication  |             |
|  | Memory        |  | (logs, WS)    |  | Bus (channels, |             |
|  | (per-game)    |  |               |  |  @-mentions,   |             |
|  |               |  |               |  |  escalations)  |             |
|  +---------------+  +---------------+  +----------------+             |
|                                                                       |
+-----------------------------------------------------------------------+
|  React Dashboard  |  GitHub Actions (deploy)  |  MCP Server (CLI)     |
+-----------------------------------------------------------------------+
```

---

## Core Components

### 1. Agent Registry

Loads agent definitions from `.md` files (agency-agents format) and manages lifecycle.

**Agent definition format** (YAML frontmatter + markdown body):
```yaml
---
name: Game Designer
description: Systems and mechanics architect
category: game-development
default_model: openrouter/qwen/qwen3-coder:free
fallback_model: omlx/qwen3.5-9b
tools: [file_read, file_write, channel_post, channel_read, escalate, project_memory_read, project_memory_write]
---
# Game Designer Agent Personality
You are GameDesigner, a senior systems and mechanics designer...
[full system prompt from agency-agents]
```

**Lifecycle states:** `idle` -> `assigned` -> `running` -> `completed` | `blocked` | `failed`

**Registry operations:**
- `register(agent_md_path)` — load and validate agent definition
- `spawn(agent_id, task, project)` — create a running agent instance
- `list(filters)` — query agents by category, status, project
- `terminate(instance_id)` — stop a running agent
- `hot_reload()` — re-scan agent directory for new/changed definitions

**Agent directory structure:**
```
agents/
  game-development/
    game-designer.md              # absorbs narrative + level (2026-04-19)
    game-audio-engineer.md
    technical-artist.md
    roblox-systems-scripter.md
    roblox-experience-designer.md
    roblox-avatar-creator.md
  engineering/
    frontend-developer.md
    code-reviewer.md
    tech-lead.md
    rapid-prototyper.md
  analytics/                        # rewritten as game-analytics team (2026-04-19)
    telemetry-engineer.md           # instrumentation → telemetry_spec_v1/_diff_v1
    metrics-dashboard-builder.md    # sqlite + 4-chart dashboard → metrics_store_spec_v1 + dashboard_html_v1
    analytics-reporter.md           # 4-section postmortem + trend_v1 + publish_blurb → postmortem_{tag}
    player-feedback-synthesizer.md  # itch/GH/Roblox comment digest → player_feedback_v{N}
  design/                           # narrowed to kid-game scope (2026-04-19)
    hud-designer.md                 # 6-screen HUD + menu layout → hud_spec_v1
    screen-flow-designer.md         # 5-state machine + transitions → screen_flow_v1
    player-researcher.md            # trend + behavior research → trend_report_v1
    juice-polisher.md               # post-QA juice pass → juice_pass_v1
  production/                       # collapsed 3 orphans to 1 driver (2026-04-19)
    producer.md                     # end-to-end process owner → production_status_v1
    publisher.md                    # ship gate (itch.io + GH Pages + Roblox) → publish_manifest
  testing/
    qa-engineer.md
    game-performance-tester.md
    game-release-gate.md
```

### 2. Agent Runtime

The agentic tool-use loop. Model-agnostic — works with any LLM that supports tool calling.

**Execution loop (per task):**
```
1. Build context: agent system prompt + task description + project memory + channel history
2. Send to LLM with available tools
3. LLM responds with text OR tool_call
4. If tool_call:
   a. Check governance (is this tool approved?)
   b. If approved: execute tool, get result
   c. If not approved: queue for human approval, block agent
   d. Feed result back to LLM, goto 3
5. If text: capture output, mark task step complete
6. If task has more steps: goto 1 with updated context
7. Finalize: store results in project memory, post to channel
```

**Concurrency:** Multiple agents can run in parallel (asyncio tasks). Each agent instance has its own conversation state. File system access is per-project (agents are sandboxed to their project directory).

**Token/cost tracking:** Every LLM call is metered — model, input tokens, output tokens, cost. Logged per agent instance per task.

### 3. LLM Router

Routes agent requests to the right provider based on agent config and availability.

**Providers:**
| Provider | Use case | Config |
|----------|----------|--------|
| OpenRouter | Remote models (Qwen, Nemotron, Gemini, Claude) | API key in .env |
| oMLX | Local models (Qwen3.5-9B) | localhost:8000 |
| Anthropic | Claude direct (when needed) | API key in .env |

**Routing logic:**
1. Check agent's `default_model` provider
2. If provider is healthy → route there
3. If provider is down → try `fallback_model`
4. If all fail → queue task, notify human

**Tool-use format translation:** Different providers use different tool-calling formats. The router normalizes:
- Anthropic: native tool_use blocks
- OpenRouter (OpenAI-compatible): function_calling format
- oMLX: OpenAI-compatible (Qwen supports tool calling)

### 4. Task Queue

Manages work items with assignment, dependencies, and status tracking.

**Task model:**
```python
class Task:
    id: str
    project_id: str
    title: str
    description: str
    assigned_to: str | None          # agent instance ID
    status: Literal["pending", "assigned", "running", "blocked", "completed", "failed"]
    depends_on: list[str]            # task IDs that must complete first
    created_by: str                  # agent ID or "human"
    priority: int
    result: dict | None              # output when completed
    created_at: datetime
    updated_at: datetime
```

**Operations:**
- `create(task)` — add to queue, check dependencies
- `assign(task_id, agent_id)` — atomic assignment (prevents double-work)
- `complete(task_id, result)` — mark done, trigger dependent tasks
- `block(task_id, reason)` — waiting on human/other agent
- `list(project_id, status)` — query tasks

**Auto-spawn:** When a task's dependencies are met and it has no assignee, the orchestrator can auto-spawn the appropriate agent type based on the task's category.

### 5. Communication Bus

Agents communicate through project channels and direct mentions.

**Primitives (exposed as tools to agents):**

```python
# Tools available to all agents
tools = {
    "channel_post": {
        "params": {
            "channel": "str",     # "general", "review", "decisions"
            "message": "str",
            "mentions": ["str"]   # agent names to @-mention
        }
    },
    "channel_read": {
        "params": {
            "channel": "str",
            "since": "timestamp",
            "limit": "int"
        }
    },
    "escalate": {
        "params": {
            "question": "str",
            "options": ["str"],
            "context": "str",
            "blocking": "bool"    # if true, agent waits for response
        }
    }
}
```

**Channel types per project:**
- `#general` — all team communication
- `#review` — code reviews and feedback
- `#decisions` — escalations to human (triggers dashboard notification + Telegram)

**Wake triggers:**
| Trigger | Action |
|---------|--------|
| Task assignment | Agent spawns immediately |
| @-mention | Orchestrator wakes mentioned agent with message context |
| Pipeline step complete | Next agent auto-spawns |
| Human response to escalation | Blocked agent resumes |

**Message persistence:** All messages stored in project database. Full conversation history available for observability and replay.

### 6. Pipeline Engine

Declarative agent chains for multi-step game production workflows.

**Pipeline definition (YAML):**
```yaml
pipelines:
  new-game:
    name: "New Game Production"
    steps:
      - id: concept
        agent: game-designer
        task: "Produce mechanics_v1 from concept: {input}"
        output: mechanics_v1

      - id: prototype
        agent: frontend-developer
        depends_on: [concept]
        task: "Build Three.js prototype from mechanics_v1 core loop"
        output: prototype_code

      - id: review
        agent: code-reviewer
        depends_on: [prototype]
        task: "Review prototype code quality and security"
        output: review_feedback

      - id: human-review
        type: human-gate
        depends_on: [prototype, narrative]
        task: "Review prototype and narrative. Approve to continue."
```

**Execution modes:**
- **Sequential:** step A → step B → step C
- **Parallel:** steps B and C run simultaneously after A
- **Human gate:** pipeline pauses until you approve in dashboard
- **Conditional:** branch based on previous step output

### 7. Project Memory

Per-game knowledge store. All agents working on a project share this context.

**Storage:** SQLite database per project (lightweight, portable, git-friendly).

**Memory types:**
| Type | Content | Example |
|------|---------|---------|
| `decision` | Design decisions with rationale | "Core loop: endless runner. Why: simple to prototype, high replayability" |
| `artifact` | References to produced files | "GDD at docs/gdd.md, prototype at src/game.js" |
| `feedback` | Human feedback on output | "Gravity flip feels too slow — speed up 2x" |
| `context` | Project-wide facts | "Target: Three.js, web-only, casual audience" |

**Tools (available to agents):**
```python
tools = {
    "memory_write": {
        "params": {"type": "str", "key": "str", "content": "str"}
    },
    "memory_read": {
        "params": {"type": "str", "key": "str | None", "query": "str | None"}
    },
    "memory_search": {
        "params": {"query": "str", "limit": "int"}
    }
}
```

**Context injection:** When an agent spawns for a project, the runtime auto-injects:
1. Recent decisions (last 10)
2. Relevant artifacts
3. Recent channel messages (last 20)
4. Any human feedback

**Future extension:** Studio-wide memory layer for cross-project design consistency.

### 8. Tool Governance

Controls which tools agents can use. Existing tools are auto-approved; new additions need human approval.

**Permission tiers:**
| Tier | Tools | Approval |
|------|-------|----------|
| **Built-in** | file_read, file_write, bash_execute, git_*, web_search, channel_*, memory_* | Always allowed |
| **Pre-approved** | Your existing Claude Code skills/plugins (list in config) | Always allowed |
| **Restricted** | New tools, npm install, pip install, external API calls to unknown endpoints | **Requires human approval** |
| **Blocked** | Destructive ops (rm -rf outside project dir, force push to main, drop tables) | Always denied |

**Governance flow:**
1. Agent makes a tool call
2. Runtime checks the governance registry
3. If `built-in` or `pre-approved` → execute immediately
4. If `restricted` → create approval request, push to dashboard + Telegram, block agent
5. If `blocked` → deny, tell agent why, continue
6. Human approves/denies in dashboard → agent resumes/adapts

**Approval persistence:** Approved tools are remembered. "Allow npm install for this project" means future npm install calls in that project auto-approve.

**Audit log:** Every tool call logged with: agent, tool, params, governance decision, timestamp, result.

### 9. Observability

Structured logging, metrics, and real-time feed for the dashboard.

**Log levels:** Every agent action produces a structured log entry:
```json
{
    "timestamp": "2026-04-15T15:30:00Z",
    "project": "space-runner",
    "agent": "frontend-developer",
    "instance": "fd-001",
    "event": "tool_call",
    "tool": "file_write",
    "params": {"path": "src/game.js"},
    "governance": "approved",
    "duration_ms": 45,
    "tokens": {"input": 2400, "output": 800},
    "cost_usd": 0.003
}
```

**Metrics tracked:**
- Tokens used per agent/project/provider
- Cost per agent/project/pipeline
- Task completion rate and duration
- Tool call frequency by type
- Escalation rate
- Pipeline throughput

**Real-time feed:** WebSocket endpoint streams events to the dashboard. Filter by project, agent, event type.

### 10. React Dashboard

Standalone web application for studio management.

**Pages:**
| Page | Purpose |
|------|---------|
| **Studio Overview** | Active projects, running agents, recent activity feed |
| **Project Board** | Kanban-style task board for a specific game project |
| **Agent Monitor** | Live view of all agent instances — status, current task, logs |
| **Channel View** | Real-time project communication (like Slack) |
| **Approval Queue** | Pending tool/permission requests with approve/deny buttons |
| **Output Review** | Game preview (iframe to GitHub Pages), screenshots, artifacts |
| **Cost Dashboard** | Token usage, cost breakdown by agent/project/provider |
| **Settings** | Agent registry, tool governance rules, LLM provider config |

**Tech:** React + Vite, WebSocket for real-time updates, dark theme.

### 11. Deploy Service

Auto-deploy game output to GitHub Pages for review.

**Flow:**
1. Agent commits code to project repo branch
2. GitHub Actions workflow triggers
3. Build step (if needed — npm build, bundle)
4. Deploy to GitHub Pages (`https://{user}.github.io/{project}/`)
5. Orchestrator receives webhook, updates project with preview URL
6. Dashboard shows live preview in iframe

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestrator | Python 3.11+, FastAPI, uvicorn |
| Database | SQLite (project memory + task queue + message bus) |
| Dashboard | React + Vite + TypeScript |
| Real-time | WebSocket (FastAPI native) |
| LLM clients | httpx (async) for OpenRouter/oMLX/Anthropic |
| Notifications | Telegram bot (@ChocobanaaBot) |
| Deployment | GitHub Actions → GitHub Pages |
| Agent definitions | Markdown + YAML frontmatter |
| Config | YAML (agents, pipelines) + .env (API keys) |

---

## Game Studio Agent Roster (Initial)

### Core Team (from agency-agents)
1. **Game Designer** — GDD, gameplay loops, economy balance
2. **Narrative Designer** — story, dialogue, lore architecture
3. **Level Designer** — spatial design, pacing, encounter design
4. **Game Audio Engineer** — sound design specs, adaptive audio
5. **Technical Artist** — shader specs, VFX, performance budgets

### Engineering Team (from agency-agents + custom)
6. **Frontend Developer** — Three.js/WebGL implementation (custom agent)
7. **Code Reviewer** — code quality, security review
8. **DevOps Automator** — CI/CD, deployment pipelines

### Roblox Team (from agency-agents)
9. **Roblox Systems Scripter** — Luau, client-server, DataStore
10. **Roblox Experience Designer** — engagement loops, monetization

### Support
11. **QA Engineer** — testing, bug reporting (from agency-agents)

---

## Project Structure

```
code-play/
  README.md
  .env                          # API keys (not committed)
  .env.example
  config/
    agents.yaml                 # Agent roster + model routing
    pipelines.yaml              # Pipeline definitions
    governance.yaml             # Tool permission rules
  agents/                       # Agent .md definitions
    game-development/
    engineering/
    testing/
  src/
    main.py                     # FastAPI app entry
    orchestrator/
      agent_registry.py         # Load + manage agent definitions
      task_queue.py             # Task CRUD + assignment
      pipeline_engine.py        # Declarative pipeline executor
    runtime/
      agent_runtime.py          # Agentic tool-use loop
      llm_router.py             # Multi-provider LLM routing
      tool_executor.py          # Execute tools with governance
    communication/
      message_bus.py            # Channels, @-mentions, escalation
    memory/
      project_memory.py         # Per-project knowledge store
    governance/
      tool_governance.py        # Permission checks + approval queue
    observability/
      logger.py                 # Structured logging
      metrics.py                # Token/cost tracking
      websocket_feed.py         # Real-time dashboard feed
    deploy/
      github_pages.py           # Deploy integration
    models.py                   # Pydantic models
    settings.py                 # Config from .env
    database.py                 # SQLite connection
  dashboard/
    package.json
    src/
      App.tsx
      pages/
        StudioOverview.tsx
        ProjectBoard.tsx
        AgentMonitor.tsx
        ChannelView.tsx
        ApprovalQueue.tsx
        OutputReview.tsx
        CostDashboard.tsx
        Settings.tsx
      components/
      hooks/
  tests/
  projects/                     # Game project workspaces (gitignored)
```

---

## Implementation Phases

### Phase 1: Foundation (MVP)
- Agent Registry (load .md files, spawn/terminate)
- Agent Runtime (tool-use loop with OpenRouter)
- LLM Router (OpenRouter only, oMLX as stretch)
- Shared Tool Pool (file_read, file_write, bash_execute, git_operations)
- Task Queue (basic CRUD + assignment)
- Communication Bus (channel_post, channel_read, escalate)
- Project Memory (SQLite, basic read/write/search)
- Observability (structured logging, token tracking)
- Minimal CLI or API to create a project + run a pipeline
- Test: spawn Game Designer, produce a GDD, hand off to Frontend Developer

### Phase 2: Governance + Dashboard
- Tool Governance (permission tiers, approval queue)
- React Dashboard (studio overview, agent monitor, approval queue)
- WebSocket real-time feed
- Telegram notifications for escalations
- Pipeline Engine (YAML-defined pipelines)
- GitHub Pages deploy integration

### Phase 3: Polish + Scale
- oMLX local model support
- Anthropic direct API support
- Fallback chains in LLM Router
- Cost dashboard
- Studio-wide memory layer
- Pipeline conditional branching
- Output review with inline feedback
- Roblox Studio agent integration

---

## Research Sources

- `~/code-play-research/paperclip-analysis.md` — Paperclip orchestration patterns
- `~/code-play-research/agency-agents-analysis.md` — 268 agent definitions, 20 game-dev agents
- `~/code-play-research/orchestrator-audit.md` — Existing agent-orchestrator reusable components
