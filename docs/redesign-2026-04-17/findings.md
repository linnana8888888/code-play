# Code PLAY Redesign — 2026-04-17

User requested 4 changes. Current state + proposed direction below.

## 1. Governance — show tools available to agents

**Current state:**
- `config/governance.yaml` defines 4 tiers: `builtin` (15 tools), `pre_approved` (4), `restricted` (6), `blocked` (4).
- Dashboard `GovernancePanel.tsx` renders only: Pending Approvals, Skills grid, Audit Log.
- Agents in `config/agents.yaml` each have hand-picked `tools: [...]` subsets.
- No "tool catalog" view. User can't see what agents CAN do at a glance.
- Claude Code's own toolbelt (Read, Edit, Write, Grep, Glob, WebFetch, WebSearch, Skill, TaskCreate, Bash, Agent) is NOT exposed as a superset agents can borrow from.

**User ask:** Governance screen shows the tools each agent can invoke. Tools the current Claude agent possesses should be freely usable by other agents.

**Proposed:**
- Add a **Tool Catalog** section to GovernancePanel: list all tools, tier (builtin/pre-approved/restricted/blocked), and which agents hold each.
- Expand `governance.yaml` builtin list to mirror Claude Code's native tools: `read`, `edit`, `write`, `grep`, `glob`, `web_fetch`, `web_search`, `skill_invoke`, `task_create`, `agent_spawn`, plus the MCP tools we already allow.
- In `agents.yaml`, replace per-agent `tools: [...]` with `tools: builtin + [extras]` — default is "everything builtin"; agents opt out or add extras.
- Surface this on the dashboard: per-agent tool chips, filter by tool to see which agents have it.

## 2. Producer flow — human-in-the-loop on plan

**Current state:**
- `config/pipelines.yaml` has 3 pipelines: `new-game`, `quick-prototype`, `roblox-experience`.
- `new-game` has a `human-gate` step but it runs AFTER concept, narrative, prototype, review — too late to change direction.
- User fills a single "input" text field in `PipelineLauncher.tsx` and the pipeline runs autonomously.
- No concept review, mechanics review, or look-and-feel review BEFORE build starts.

**User ask:** Be involved at the beginning on concept, mechanics, look-and-feel. Review plan with the possibility to change design direction.

**Proposed:**
- Split `new-game` into phases gated by human approval:
  1. `concept` → game-designer drafts 3 directions (logline, core loop, target feel)
  2. **HUMAN GATE — pick / edit / regenerate**
  3. `mechanics` → game-designer expands chosen direction into mechanics doc
  4. **HUMAN GATE — approve mechanics**
  5. `look-and-feel` → technical-artist + narrative-designer draft mood board (palette, refs, tone)
  6. **HUMAN GATE — approve aesthetic**
  7. `build` → frontend-developer implements
  8. `review` → code-reviewer + qa-engineer
- Dashboard: new "Plan Review" view showing the concept/mechanics/mood-board artifacts with approve/edit/regen buttons. Existing `human-gate` primitive can be extended.

## 3. Look-and-feel — shared resource pools

**Current state:**
- `technical-artist` writes a text-only art brief (palette hex, sprite style, font name) into memory.
- `frontend-developer` generates HTML from the GDD — no reference images, no asset library, no brand kit.
- Resulting games look like programmer art because the pipeline has zero visual inputs.

**User ask:** Two shared resource pools exist. Create tools so agents can retrieve creatives from them, or otherwise ensure they do.

**OPEN QUESTION:** What are the two pools?
- Candidate A — Kids LEGO brand assets / MinerU / obsidian-vault?
- Candidate B — A Figma library? A Google Drive folder? A local asset dir?

**Proposed (once pools identified):**
- New tools: `asset_search(pool, query)` → returns asset paths/URLs with metadata; `asset_fetch(asset_id)` → downloads/embeds into workspace.
- Add both tools to `builtin` in governance.yaml so every agent can use them.
- Update `look-and-feel` pipeline step: technical-artist MUST call `asset_search` and return ≥1 reference from each pool before proposing a direction.
- Frontend-developer receives asset paths in its context — writes `<img src>` / CSS backgrounds against real assets, not text descriptions.

## 4. Assign agents + LLMs in the plan

**Current state:**
- `config/agents.yaml` hardcodes one model per agent (e.g., `game-designer: openai/gpt-5`, `level-designer: omlx/Qwen3.5`).
- Pipeline steps reference agents by type; model is determined at spawn time from the yaml.
- No UI to choose, per-task, whether GPT-5 / Opus / Sonnet / Haiku / Qwen runs the step.

**User ask:** Assign agents as part of the plan, choose which LLM (Claude / GPT / Qwen) executes each task.

**Proposed:**
- Dashboard "Plan Review" view (from #2) renders a table: Step | Agent | Model (dropdown) | Budget cap.
- Dropdown populated from approved model set (5 options currently).
- On "Launch," the plan is saved as a concrete run config; each task spawn reads its model override instead of agent yaml default.
- Backend: extend `TaskCreate` API to accept `model_override` and pass it to `AgentRuntime.spawn(model=...)`.
- Show estimated cost per step (local = free, Haiku ~$0.01/k, Sonnet ~$0.003/k in, Opus ~$0.015/k in, GPT-5 ~$0.005/k in reasoning) so user can budget consciously.

## Implementation order (suggested)

1. Ask user: which two resource pools? → unblocks #3
2. Expand governance builtin tools + add Tool Catalog UI (#1) — cheap, high visibility
3. Add `model_override` on tasks + plan-edit UI (#4) — unblocks #2 phase gating
4. Split new-game pipeline into phased human gates (#2)
5. Build asset_search / asset_fetch tools and wire into look-and-feel step (#3)
