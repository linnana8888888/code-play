# code-play vs paperclipai/paperclip

_Comparison snapshot — 2026-04-18._

Both projects orchestrate teams of AI agents against hierarchical goals. They
are **different products with overlapping primitives**: code-play is a
game-studio orchestrator that **runs the LLM loop itself**; paperclip is a
zero-human-company shell that **delegates all LLM work to external adapters**.

The rest of this doc unpacks the consequences of that single design choice.

---

## 1. One-line positioning

| | code-play | paperclip |
|---|---|---|
| Tagline | "Multi-agent game studio — 38 specialized agents build web/3D games" | "Open-source orchestration for zero-human companies" |
| Primary user | A game studio building 3D/web games | Anyone running a "company" of agents |
| Scope | Game development vertical | Domain-agnostic business operation |

## 2. Stack

| | code-play | paperclip |
|---|---|---|
| Server | Python, FastAPI | TypeScript, Express |
| UI | React 18 + Vite + TS + Tailwind v4 | React + Vite |
| DB | SQLite (per-project stores too) | Postgres (PGlite in dev, real PG/Supabase in prod) |
| ORM | Raw SQL / lightweight | Drizzle |
| Package mgr | `pip` / `venv` | `pnpm` workspaces |
| Tests | pytest (35 e2e) | Vitest + Playwright + promptfoo |
| Distribution | `git clone` + `uvicorn` | `npx paperclipai`, Docker, Vercel |

## 3. Architecture shape

| | code-play | paperclip |
|---|---|---|
| Tenancy | Single studio; multi-project | **Multi-company** in one deployment |
| Agent runtime | **In-process tool-use loop** (code-play runs the model call) | **Out-of-process** (agents = child processes or HTTP endpoints) |
| Loop trigger | On task assignment / pipeline step | **Heartbeat** per agent (`intervalSec`, ≥30s) |
| Concurrency | Multiple spawned instances per agent type | `maxConcurrentRuns = 1` per agent |
| Local-first | Yes | Yes ("no Paperclip account required") |

This is the single biggest architectural difference. code-play is a classic
tool-use LLM orchestrator — model picks a tool, we execute, we feed the result
back, loop. Paperclip is a **scheduler** — every 30s+ it wakes the agent's
binary or HTTP endpoint and lets it decide what to do; Paperclip only watches
and records.

## 4. Agent model

| | code-play | paperclip |
|---|---|---|
| Roster | 38 agents in 9 categories, defined in `agents/**/*.md` + `config/agents.yaml` | Created in DB at runtime; company-scoped |
| Definition source | Static files, git-versioned | Mutable DB rows, edited in UI |
| Hierarchy | Flat; tasks have `parent_id` | **Reporting tree** (`reports_to`, strict single-manager) |
| Backend binding | `config/agents.yaml` routes to a model (GPT-5, Opus 4.7, Sonnet 4.6, Haiku 4.5, Qwen3.5 local) | `adapter_type` binds to an executable: `process`, `http`, `claude-local`, `codex-local`, `cursor-local`, `gemini-local`, `openclaw-gateway`, … |
| Context delivery | Full message history in API call | `thin` (just IDs) or `fat` (assignments + goal + budget + recent comments) |
| Lifecycle states | running / idle / terminated (instance-level) | active / paused / idle / running / error / terminated |

Paperclip's agent is **whatever can receive a heartbeat** — a Claude Code CLI,
a `cursor-agent` binary, a shell script, a Flask endpoint. code-play's agent
is **always the same runtime** (our FastAPI tool-use loop) with a different
system prompt + model.

## 5. Runtime loop

**code-play:** task assigned → agent runtime loads skill defs + tools → API
call to LEGO proxy / OpenAI / OpenRouter / oMLX → tool calls executed by
`tool_executor.py` → loop until stop / budget / terminal condition.

**paperclip:** scheduler tick → wake eligible agents →
`adapter.invoke(agent, context)` → external process runs however it wants →
adapter polls `.status(run)` → stdout/stderr streamed to DB → on exit, optional
cost events + comments logged. One auto-retry on crash, then `blocked`.

Consequence: **code-play owns the inference contract**, paperclip **owns the
work contract**. Paperclip doesn't know what model the agent used unless the
agent POSTs a `cost_events` row.

## 6. Model router / backends

| | code-play | paperclip |
|---|---|---|
| Router | Central `llm_router.py` — LEGO proxy, Anthropic direct, OpenRouter, oMLX | **None** — no central LLM router at all |
| Model config | `config/agents.yaml` with `model` + `fallback_model` per agent | Lives inside each adapter's own config (e.g. `codex-models.ts`) |
| Cost tracking | Computed from token usage at API boundary | Received as `cost_events` posted by the agent after each run |
| Budget enforcement | Per-agent-run budget (`budget_max_tokens`, `budget_max_usd`) enforced at loop edge | Monthly agent budget; hard auto-pause at 100%, soft alert at 80% |

Paperclip's lack of a router is a feature: it means you can drop an
`openclaw-gateway` agent or a custom OpenRouter wrapper in without touching
paperclip core. The trade-off is that paperclip has **no visibility into
prompts or tool use** — just whatever the adapter reports.

## 7. Tools & governance

| | code-play | paperclip |
|---|---|---|
| Built-in tools | 16 (file_read, file_write, bash, playwright, channel_post, git_push, …) | **Zero** — tools are the adapter's concern |
| Governance model | 4-tier: builtin / standard / restricted / blocked + per-skill approval | Approval table for privileged operations (`hire_agent`, `approve_ceo_strategy`); board can pause/resume/terminate any agent |
| Audit | Governance log + per-agent cost endpoint | Append-only `activity_log` + immutable audit log on every issue |
| Skill system | `.md` skill files with permission model, injected at runtime | `skills/` folder (paperclip-create-agent, para-memory-files, …) also runtime-injected |

Both have skills. Both have approval queues. code-play owns the tool
sandboxing; paperclip outsources it.

## 8. Task / work queue

| | code-play | paperclip |
|---|---|---|
| Backing store | SQLite `tasks` table | Postgres `issues` table |
| Atomic checkout | Yes — race-condition safe SQL update | Yes — single-SQL `UPDATE…WHERE` returning 409 on conflict |
| Hierarchy | `parent_id` within a project | `parent_id` + `goal_id` ancestry mandatory |
| Dependencies | Yes | `blockedByIssueIds` |
| Assignee | Agent instance | Single `assignee_agent_id` XOR `assignee_user_id` |
| State machine | pending / assigned / running / done | backlog / todo / in_progress / in_review / done / blocked / cancelled |
| Goal linkage | Project has a goal; tasks inherit | **Every issue must trace to a company goal** — enforced |

Paperclip's queue is stricter: richer states, mandatory goal linkage, separate
`checkoutRunId` and `executionRunId` locks. code-play's queue is adequate for
a studio; paperclip's is built for "don't let agents wander."

## 9. Observability / UI

| | code-play | paperclip |
|---|---|---|
| Dashboard | 6 views at `/app` — Studio Overview, Agent Roster, Task Board, Channels, Governance, Project View | Board, Companies, Org chart, Tasks, Agents, Costs, Approvals, Activity |
| Real-time | WebSocket feed at `/ws` | Not documented; polling expected |
| Unique UI | Slack-like channels, pipeline launcher | **Org chart**, multi-company switcher, MTD spend vs budget card |
| Design philosophy | "Real-time observability" | "No silent background failures — every failed run visible" |

Both are dark, operator-focused. Paperclip leans heavier into
**org / finance** (cost dashboards, approval queues, company templates);
code-play leans heavier into **collaboration** (channels, pipelines).

## 10. State & memory

| | code-play | paperclip |
|---|---|---|
| Session persistence | `session_store` saves agent conversations for resume | `heartbeat_runs.context_snapshot` jsonb + `external_run_id` |
| Workspace isolation | **Git worktree per agent instance** (or dir copy) | Not built-in; adapters manage their own filesystem |
| Per-project memory | SQLite `project_memory` store (decisions, artifacts, feedback) | `documents` + `document_revisions` (append-only) + `issue_documents(plan/design/notes)` |
| Long-term memory | None explicit | Roadmap: provider-adapter contract (mem0, supermemory, memsearch) |
| Binary assets | Filesystem in workspace | `assets` + `issue_attachments` (local_disk or s3) |

code-play's workspace-per-agent is paperclip's missing piece; paperclip's
revisioned documents and assets table is code-play's missing piece.

## 11. Standout features unique to each

**code-play only**
- 38 pre-built, game-industry-tuned agents out of the box
- Central LLM router with 5 providers wired in
- Git worktree per agent instance (true isolation, no adapter contract needed)
- `pipelines.yaml` — named flows (`full-game`, `art`, `qa-sweep`)
- Playwright-enabled qa-engineer for live game playtest
- Slack-like per-project channels with @-mentions + blocking escalation
- Per-project memory store
- Kids-audience compliance competency (COPPA / PEGI / ESRB / cultural review)

**paperclip only**
- Multi-company multi-tenant model in a single deployment
- Heartbeat-driven scheduler instead of on-demand loop
- Adapter plugin ecosystem (`~/.paperclip/adapter-plugins.json`) with 7 shipped
- Bring-your-own-agent via `process` or `http` adapter — zero lock-in
- Reporting tree with strict single-manager
- Approval queue for `hire_agent` and `approve_ceo_strategy`
- Monthly budget hard-stop with 80% warn + 100% auto-pause
- Revisioned documents + assets + issue_documents(plan/design/notes)
- Company templates — export/import whole orgs (`companies.sh`)
- Planned skills and plugin catalog (`awesome-paperclip`)
- Mintlify docs + homepage (`paperclip.ing`) + extensive SPEC.md

## 12. Maturity signal

| | code-play | paperclip |
|---|---|---|
| GitHub stars | (private/personal repo) | **55,465** |
| Forks | — | 9,376 |
| Open issues | — | 2,414 |
| Docs | `design.md` + README | SPEC.md, SPEC-implementation.md (881 lines), execution-semantics.md, memory-landscape.md, DATABASE.md, Mintlify site |
| Community | Internal | Discord, plugin registry |
| Age | Phase 2b just complete | Created 2026-03-02, actively pushing |

---

## The honest summary

Paperclip is **a better-engineered product** at the orchestration layer:
stricter goal ancestry, richer issue states, multi-tenant, revisioned
documents, plugin adapters, company templates, 55k stars of community
feedback.

code-play is **a better-equipped studio** at the execution layer: 38 tuned
agents, a real LLM router, worktree isolation, built-in tools, playtest
automation, channels, a compliance competency specific to kids audiences.

Two natural moves if we want to converge:

1. **Adopt paperclip's data model.** Steal the `goal_id` mandatory linkage,
   the `blockedByIssueIds` graph, the `checkoutRunId` / `executionRunId`
   split, the `document_revisions` table, the approvals for hires and
   strategy, the monthly budget auto-pause. These are table migrations, not
   rewrites.
2. **Expose code-play agents as paperclip adapters.** Wrap our FastAPI
   runtime in an `http` adapter so our 38 game-tuned agents become pluggable
   into any paperclip deployment. We keep the router + tools + worktrees;
   paperclip supplies the multi-company shell, approval queue, and org
   chart.

The converse — rebuilding paperclip's scheduler in Python — is the wrong
trade. Paperclip's runtime wins; code-play's agents win.
