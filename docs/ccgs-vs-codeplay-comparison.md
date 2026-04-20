# Claude-Code-Game-Studios vs code-play: Comparison

**Date:** 2026-04-20  
**CCGS repo:** https://github.com/Donchitos/Claude-Code-Game-Studios.git  
**code-play repo:** https://github.com/linnana8888888/code-play

---

## 1. Architecture Philosophy — the fundamental split

| | **Claude-Code-Game-Studios** | **code-play** |
|---|---|---|
| **Runtime** | **Zero infrastructure.** Pure Claude Code native — agents are `.claude/agents/*.md`, skills are `.claude/skills/*/SKILL.md`, hooks are `.claude/hooks/*.sh`. No server, no database, no dependencies beyond git + Claude Code. | **Full-stack platform.** FastAPI backend + SQLite task queue + React dashboard + WebSocket feed + LLM Router. It's a standalone service that wraps Claude/OpenRouter/oMLX. |
| **Agent execution** | Claude Code spawns subagents natively via the Agent tool. Agent definitions are markdown with YAML frontmatter (`model:`, `tools:`, `skills:`, `memory:`). | Custom `agent_runtime.py` runs a model-agnostic tool-use loop with budget enforcement, session persistence, and goal ancestry. Agents are YAML configs dispatched by the orchestrator. |
| **State** | File-on-disk: `production/active.md`, session hooks, git. No database. | SQLite-backed task queue, project memory store, session store, per-agent cost tracking. |

**Takeaway:** CCGS is a *template* you drop into any project. Code-play is a *platform* you operate. CCGS has near-zero onboarding friction; code-play has far richer observability and runtime control.

---

## 2. Agent Depth — breadth vs. vertical integration

| | **CCGS (49 agents)** | **code-play (21 agents)** |
|---|---|---|
| **Scope** | Covers the entire AAA studio org chart: creative director, technical director, producer + department leads + engine-specific specialists (Godot, Unity, Unreal sub-trees). | Covers a lean web/3D game studio: game-designer, frontend-developer, QA, publisher, style-researcher, analytics, Roblox specialists. |
| **Engine coverage** | Godot 4, Unity, Unreal 5 — with sub-specialists (GDScript, C#, DOTS, Shaders, Blueprints, GAS, Replication). | Web engines only (Three.js, Pixi, Phaser, Babylon) + Roblox (Luau/Rojo). |
| **Agent prompts** | Extremely detailed — the creative-director alone is 360 lines with MDA framework, pillar methodology, player psychology theory, scope-cut prioritization, worked examples. | Shorter personality docs focused on tool grants and pipeline role. The depth is in the *pipeline YAML*, not the agent prompt. |

**Takeaway:** CCGS agents carry domain knowledge *in themselves* (game design theory, player psychology). Code-play agents are thinner but gain structure from the orchestrator pipeline. If you want agents that can reason independently about game design trade-offs, CCGS's agent prompt depth is worth studying.

---

## 3. Workflow / Pipeline Design

| | **CCGS** | **code-play** |
|---|---|---|
| **Pipeline model** | **72 slash commands** forming a loose, user-driven workflow. Skills call agents but the user chooses which skill to run and when. 7-phase workflow catalog (concept -> design -> architecture -> sprint -> build -> QA -> release) with `/gate-check` for phase transitions. | **Declarative pipeline YAML** with `depends_on`, `human-gate`, `model_override`, and even a `cyclic: true` iterate loop. The orchestrator resolves the DAG and runs it. |
| **Human gates** | Review modes (full/lean/solo). Director agents produce GATE verdicts (`APPROVE`/`CONCERNS`/`REJECT`). User decides when to proceed. | Explicit `type: human-gate` steps in the pipeline YAML. The dashboard surfaces the gate for review. |
| **Iteration** | Manual — run `/dev-story` again, run `/code-review`, etc. | **Built-in iteration loop** (`iterate_artifact` pipeline): headless playtest 5x -> postmortem -> 4 parallel proposals -> human pick -> implement -> loop. This is genuinely novel. |
| **A/B racing** | Not present. | `phased-producer-race` pipeline fans out two builders on different models (GPT-5 vs Opus 4.7) and lets you pick the winner. Creative use of model diversity. |

**Takeaway:** Code-play's declarative pipelines with cyclic iteration are more advanced as an *orchestration system*. CCGS's slash-command approach is more flexible for ad-hoc work. The iterate_artifact loop is code-play's standout feature.

---

## 4. Safety & Governance

| | **CCGS** | **code-play** |
|---|---|---|
| **Hooks** | 12 bash hooks on git events, session lifecycle, compaction, and agent audit trail. All fail-safe (exit 0 on irrelevant). | Governance tiers in YAML (builtin/pre_approved/restricted/blocked). Dashboard approval queue for restricted tools. |
| **Path-scoped rules** | 11 `.claude/rules/*.md` files — when you edit `src/gameplay/**`, the AI sees gameplay-specific coding standards. When you edit `src/networking/**`, it sees security rules. | 4 skills (coding-standards, git-workflow, testing-patterns, asset-sources) injected into agents. Less granular. |
| **Permission model** | Claude Code native `settings.json` allow/deny lists. | Custom `tool_executor.py` with 4-tier governance. More control but more code to maintain. |

**Takeaway:** CCGS's path-scoped rules are clever — they're essentially "this code region has these invariants" without any custom infrastructure. Worth stealing for code-play.

---

## 5. What code-play has that CCGS doesn't

- **Actual running backend** with REST API, WebSocket, cost tracking per agent
- **React dashboard** for real-time observability
- **Multi-model LLM routing** (OpenRouter + local oMLX + Anthropic direct)
- **Automated iteration loops** with headless playtesting + telemetry
- **A/B model racing** in pipelines
- **Publishing pipeline** to itch.io, GitHub Pages, and Roblox
- **Per-agent workspaces** (git worktrees or directory copies)
- **Asset source integration** (Kenney, itch, Polyhaven, etc.)

---

## 6. What CCGS has that code-play doesn't

- **Zero-dependency setup** — clone and go, no server needed
- **Deep game design theory** baked into agent prompts (MDA, SDT, flow state, ludonarrative consonance)
- **Engine-specific expertise** (Godot/Unity/Unreal sub-specialists with engine-aware coding standards)
- **Path-scoped coding rules** that activate based on which file you're editing
- **39 document templates** (GDD, ADR, sprint plan, pitch doc, character sheet, difficulty curve, etc.)
- **Session lifecycle hooks** (pre/post compaction, session start/stop state preservation)
- **Agent audit trail** (SubagentStart/SubagentStop hooks)
- **Conflict resolution protocol** — formal escalation paths between agents
- **Collaborative decision protocol** — agents always present options, user always decides

---

## 7. What to learn / steal

1. **Agent prompt depth** — CCGS's creative-director and producer prompts are essentially embedded textbooks. The pillar methodology, MDA framework usage, and scope-cut prioritization logic could be ported into code-play agent configs to make them reason better about game design.

2. **Path-scoped rules** — simple, powerful, zero-infrastructure. code-play could implement these as skill injections that trigger based on which files an agent is editing.

3. **Document templates** — CCGS has 39. Code-play's GDD/art-brief generation is currently ad-hoc in pipeline task descriptions. Extracting these into templates would make the output more consistent.

4. **Session state hooks** — CCGS preserves context across compaction events (`pre-compact.sh` saves progress, `post-compact.sh` restores it). code-play's session store does this programmatically, but the hook approach is more resilient for Claude Code native usage.

5. **Escalation protocol** — the vertical delegation / horizontal consultation / conflict resolution model is well-thought-out. code-play's agents don't have formal escalation paths.

6. **Review intensity modes** (full/lean/solo) — letting the user dial the review strictness per-run is a good UX pattern. Code-play's gates are all-or-nothing currently.

7. **Unity expertise** — CCGS has 5 Unity specialists (core, DOTS, shaders, addressables, UI). Code-play has zero Unity capability.

---

## 8. Model tiering note (LEGO proxy)

CCGS uses a 3-tier model strategy (Opus for synthesis, Sonnet for implementation, Haiku for lookups). On the LEGO proxy, Haiku is actually Sonnet underneath, so the 3-tier split offers no cost benefit. Effectively a 2-tier system: Opus + Sonnet.
