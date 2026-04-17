# Game Creation Session Improvements — 2026-04-17

Running list of UX/flow issues spotted while actually driving a game build
(project: "Butt shooting Game", pipeline: phased-producer).

## 1. Human hand-off after a task completes

**Problem.** When a kanban task finishes (e.g. `concept` goes completed),
nothing in the UI points the human to the next action. You have to:
1. Notice the task flipped,
2. Remember that the gate lives on a different tab,
3. Click into the plan tab,
4. Scroll to find the ready gate,
5. Open the summary accordion to read the artifact.

That's 4 hops of tribal knowledge for a gate that's otherwise
auto-announced (ready flag, polling every 4s).

**Fix direction.**
- When a task completes AND its follow-up is a `human-gate`, raise it in
  the UI automatically:
    - Toast / banner: "Concept ready for review — [Open]"
    - Either deep-link to the plan tab with the specific gate expanded,
      OR open a modal (drawer) with the artifact rendered inline so the
      reviewer never loses kanban context.
- The artifact body today is `<pre>` raw JSON/markdown — render it
  properly (markdown → html, palette chips when the artifact has hex
  colors, thumbnail grid when it has asset_ids, etc.).
- "Next action" surface on the project header: "Your turn — review
  concept" button that jumps to the right gate.

**Suggested implementation sketch.**
- WebSocket broadcast already exists (`task_created`, similar for
  `task_updated`). Emit `gate_ready` when `_advance_pipeline` flips a
  gate's ready flag. Dashboard listens and shows a non-modal banner in
  the project header with a single primary action.
- `GatesPanel` gets an `?expanded=<task_id>` query param so the banner's
  "Open" link lands on the correct gate, pre-scrolled, pre-expanded.

## 2. Render asset previews inline on the look-and-feel gate

**Problem.** The `look-and-feel` brief references asset_ids (e.g.
`kenney:mini-arena`, `kenney:particle-pack`) and a palette of hex codes.
A human reviewing the gate today sees only text:
- `- kenney:mini-arena — modular top-down arena pieces…`
- `Palette: #FFB703, #FF4D6D, #00D1FF…`

Without seeing the actual sprites and colors, the reviewer has no
real signal for "does this feel right?" — they're approving a
description, not an aesthetic.

Compounding it: in this run `asset_fetch(kind='preview')` silently
didn't resolve for the picked asset_ids, so no thumbnails were even
downloaded to `assets/`. The agent shipped the brief anyway.

**Fix direction.**
- The gate detail view should render a small asset board:
    - Palette strip: each hex gets a swatch with the code beside it.
    - Reference grid: for each asset_id in the brief's `references`
      section, show the preview thumbnail. Hit the same
      `preview_url` that `asset_search` already returned; cache the
      bytes locally under `projects/<id>/assets/previews/` so the
      gate view is instant and offline-survivable.
    - Fallback: if a preview failed to resolve, show a broken-image
      placeholder with the asset_id and a "retry fetch" link so the
      reviewer can see exactly what's missing instead of a silent gap.
- Make `asset_fetch(kind='preview')` loud: when it fails, it should
  return an error the agent can see (not silently swallow) so the
  brief generation can either retry or clearly note the gap.
- Enforce at the pipeline level: the look-and-feel step shouldn't be
  considered "complete" if any referenced asset_id has no cached
  preview. Either the agent retries, or the gate ships with explicit
  "[preview pending for X]" markers — never a silent omission.

**Suggested implementation sketch.**
- New endpoint `GET /api/projects/{id}/assets/previews` returns the
  cached thumbnail map `{asset_id: preview_url_or_local_path}`.
- `GatesPanel` (or the artifact renderer) parses the brief markdown,
  extracts `kenney:*` / `itch:*` asset_ids from the `references`
  section, and renders them as a grid using that map.
- Palette parser: regex `#[0-9A-Fa-f]{6}` across the brief, dedupe,
  render chips.
- `asset_fetch` handler: return `{status, path, error}` instead of
  raising silently on miss. The agent's run_tool wrapper already
  captures tool output — propagate failures into the brief.

## 3. Do we need a tech-architecture plan before build?

**Problem.** `phased-producer` today jumps from `gate-laf` → `build`.
The `frontend-developer` agent is handed three memory keys
(concept, mechanics, laf_brief) and told "build a playable web
prototype, prefer a single HTML file, use the project's tech_stack."

That last sentence is doing a lot of work. In practice the agent
has to decide on the spot:
- Which engine? (Phaser / Three / Pixi / Babylon / plain canvas)
- Single-file or modules? Build step or no build step?
- State model (global object? ECS? scene graph?)
- Asset loader / audio pipeline / input handling shape
- How the asset_ids from the brief actually get loaded at runtime

None of that was discussed at the laf gate, and none of it is a
visual/creative decision — the look-and-feel reviewer isn't the
right person to approve Three vs Pixi. The result: every build
run picks a stack fresh, and we can't compare runs or enforce
project-level consistency.

**Fix direction.**
- Insert a lightweight `tech-plan` step between `gate-laf` and
  `build`, owned by a new (or repurposed) `tech-lead` agent:
    - Input: concept + mechanics + laf_brief from memory.
    - Output: a short plan naming the engine, file layout, key
      modules/scenes, asset-loading approach, input model, loop
      structure. One page, not a spec dump.
    - Save as `tech_plan_v1` so the builder reads it verbatim.
- Follow it with a `gate-tech` human gate — cheap sanity check:
  "Phaser 3, single HTML, arcade physics, 4 scenes. OK?"
  One click, same UX as the other gates.
- Tune the gate so it's skippable for "quick-prototype" pipelines
  but required for `phased-producer`. The whole point of phased-
  producer is catching bad bets early; tech-stack is a bet.

**Suggested implementation sketch.**
- New pipeline steps in `config/pipelines.yaml`:
  ```yaml
  - id: tech-plan
    agent: tech-lead   # or reuse frontend-developer with a narrower prompt
    depends_on: [gate-laf]
    task: |
      Read concept_options_v1 + mechanics_v1 + laf_brief_v1 from memory.
      Pick an engine from the project's tech_stack list and justify in 1-2
      sentences. Define: file layout, scene/screen list, asset loader
      strategy (map each referenced asset_id to a concrete load call),
      input model, game loop shape. Keep it to ≤ 1 page. Save as
      memory artifact 'tech_plan_v1'.
    output: tech_plan

  - id: gate-tech
    type: human-gate
    depends_on: [tech-plan]
    review_of: tech-plan
    task: "Review the tech plan. Approve the stack + structure, or
           request changes."
  ```
- `build` step's `depends_on` shifts from `[gate-laf]` to
  `[gate-tech]`, and its prompt gets a new memory key in the list:
  `tech_plan_v1`.
- For `quick-prototype`, keep current behaviour — this improvement
  is scoped to `phased-producer` where phase gates are the whole
  value proposition.

**Tradeoff.** Adds one LLM step + one human click per run. Worth it
if the build step is expensive (it is — long prompts, long codegen,
sometimes flaky) and if stack drift between runs is a real cost (it
is — no way to A/B runs if each one reinvents the engine).

## 4. One engineer or a team? Parallel vs solo build

**Problem.** `build` today is a single `frontend-developer` agent
producing one HTML file end-to-end. That's fine while the output is
a 500-line single-file prototype, but two patterns break it:
- **Long horizon.** Anything past a trivial loop (multiple scenes,
  physics + UI + audio + save-game) starts pushing context limits
  and the single agent starts dropping details already agreed in
  mechanics_v1.
- **No comparison.** One run = one opinion. If the output is weak,
  the only recourse is regenerate-and-hope; we have no way to pick
  between two credible attempts.

**Three options to consider — they're not mutually exclusive.**

**A) Keep solo.** Right answer for quick-prototype and for any build
where the whole thing fits comfortably in one pass. Don't add
coordination cost for problems that don't have it.

**B) Role-split team (cooperative parallel).** Spawn specialists
downstream of `tech-plan`:
- `systems-engineer` — core loop, physics, game state
- `ui-engineer` — HUD, menus, input mapping
- `fx-audio-engineer` — particles, sounds, juice

Each writes to its own file/section; a `integrator` (or the
tech-lead) stitches at the end. The tech plan from #3 becomes the
contract: file layout + module boundaries are decided upfront, so
the specialists don't collide. Right answer when the game is
genuinely too big for one agent — i.e., when `build`'s output would
span multiple files and ~1k+ lines.

**C) A/B racing (competitive parallel).** Spawn 2–3 builders with
the same inputs, different model_overrides (e.g. GPT-5 + Opus 4.7 +
Sonnet 4.6), all producing artifact `game_html_v1_<agent_id>`. New
`gate-build-pick` lets the human (or a judge agent) compare and
select. Catches model-specific weaknesses (GPT-5 writes tight logic,
Opus writes richer UX, Sonnet is fast/cheap) without having to bet
on one up-front.

**Suggested implementation sketch.**
- Make `build` a *fan-out point* in `phased-producer`, gated by
  project size:
  - If `tech_plan_v1` estimates the game as "single-file" → solo.
  - If "multi-file" or "systems + ui + fx" → role-split team.
- Always-optional A/B flag on the project: `build_race: [opus, gpt5]`
  spawns two solo builders, or for role-split, two teams. Pick
  step after.
- The pipeline engine already supports `depends_on` arrays; a team
  of 3 agents = 3 sibling steps all depending on `gate-tech`, plus
  an `integrate` step depending on all three. The kanban UI
  visualises this naturally (columns are status, not flow).
- Memory layer needs one small upgrade: namespaced artifact keys
  per agent instance (`game_html_v1@agent-a`, etc.) so parallel
  runs don't clobber each other.

**Tradeoff.** Parallelism multiplies token spend linearly with the
number of builders. Role-split only wins when the game genuinely
exceeds one agent's working window — don't turn a hello-world into
a 4-agent ceremony. A/B racing is the cheaper, always-useful
version; it doesn't help a big game *fit*, but it does give you a
real pick instead of a hope-and-regenerate loop.

**Recommendation.** Add (C) A/B racing first — it's an orthogonal
feature (no pipeline restructuring needed, just spawning N in
parallel and a pick gate) and immediately improves output quality.
Reach for (B) role-split only once we have a concrete build that
overflowed the single-agent window.

## 5. QA agent must playtest against the mechanics doc

**Problem.** The current `review` step is a static code review:
`code-reviewer` (Haiku 4.5) reads `game_html_v1` and reports on
bugs, performance, and security. That's the wrong level of test
for a game.

This run's output shipped as "completed" with a clean review, but
on first open the game had:
- **no movement keys bound at all** (no WASD, no arrow keys — and
  mechanics_v1 presumably called for twin-stick movement)
- only a start screen + mouse-aim + click-shoot wiring
- an empty scene because the player never moved

None of those are syntactically broken — a static reviewer flags
none of them. They're only visible if someone actually plays it.
And I didn't — I reported completion off the pipeline status and
the file being well-formed. That's the exact failure mode the
`build` step is prone to, and static review can't catch it.

**Fix direction.**
- New step `qa-playtest` between `build` and `review` (or replacing
  the current static `review` with this richer version). Owned by
  a new `qa-engineer` agent whose job is:
    1. Launch `game_html_v1` in a headless browser (Playwright).
    2. Watch console for errors during load and first ~30 s of
       gameplay. Any console error = fail.
    3. Parse `mechanics_v1` for the documented verbs/systems (move,
       shoot, dash, score, pickups, etc.).
    4. For each verb, drive the corresponding input and assert
       observable state change:
         - move: press WASD + arrow keys, screenshot before/after,
           assert player pixel position changed.
         - shoot: click, assert projectile spawned (DOM or canvas
           pixel diff in front of player).
         - dash/pickup/etc.: same pattern, one check per verb.
    5. Take 3–5 screenshots at known beats (title, first move,
       first shot, first hit) and save under
       `projects/<id>/assets/qa/`.
    6. Emit a structured report: `{verb, pass/fail, evidence_path}`
       per mechanic + overall verdict + a list of missing or dead
       features.
- Gate it: `gate-qa` human-review shows the screenshots/video
  inline (builds on improvement #2's artifact renderer) so the
  reviewer can glance at pass/fail + visual evidence. Kicks back
  to `build` with specific feedback if anything's missing.
- The existing static `review` step doesn't go away — keep it for
  security/perf concerns, but demote it from "ship gate" to
  "lint report". QA is the ship gate.

**Suggested implementation sketch.**
- `qa-engineer` agent config:
  ```yaml
  qa-engineer:
    model: "anthropic/anthropic.claude-sonnet-4-6"
    fallback_model: "omlx/Qwen3.5-9B-MLX-4bit"
    description: "Playtest web games against the mechanics spec"
    tools: [builtin, playwright_browser]
  ```
- Playwright as a first-class tool (`playwright_browser`) wrapping
  navigate / click / press / screenshot / console_logs. We already
  use Playwright in the `digest` skill, so we can lift that setup.
- The mechanics parser doesn't need to be smart — the `mechanics`
  step already saves a structured artifact (player verbs,
  progression, signature systems). QA iterates over those sections
  verbatim and runs one sub-test per verb.
- Failure loop: `gate-qa` "request changes" writes the QA report
  into the `build` task's review notes and flips it back to
  `pending` with an updated prompt ("the previous build failed QA:
  [report]. Fix these specific issues only.").

**Tradeoff.** Adds runtime cost (headless browser + Sonnet/Qwen
call per verb) and makes the pipeline longer. But every single
game this session has shipped with a static review that missed
real gameplay bugs — this is the one gap that keeps producing
false "completed" states, and it's the one that matters most for
a game studio. Pay the cost.

**Related pipeline hygiene.** While we're here, the build step
should **not** mark itself complete just because the agent emitted
HTML. Right now the pipeline trusts the agent's say-so; add a
cheap post-check (file parseable as HTML + has a `<canvas>` tag +
has at least one input listener) so obvious stubs fail before QA
even runs.

## 6. One-click "Play the game" at the human review gate

**Problem.** Even after a QA pass and the build artifact is
saved, there is no way for the human reviewer to actually play it
from the dashboard. In this session I had to manually run
`open /tmp/butt-shooting-game.html` from the CLI every time the
user wanted to see it. The dashboard shows a gate card with an
artifact body (raw HTML text, or in the near-term a screenshot
grid from #5), but no "launch this game" affordance.

That breaks the whole value proposition of the gate: the gate is
where the human feels the thing and decides ship-or-kick-back.
Reading HTML source is not feeling it.

**Fix direction.**
- Serve the `game_html_v1` artifact from an orchestrator endpoint:
  `GET /api/projects/{project_id}/game/preview` → renders the
  latest HTML directly (Content-Type: `text/html`). Versioned
  variant: `…/game/preview?version=v2` once we have multiple
  artifact revisions (improvement #4 A/B + improvement #5 retry
  loop both produce them).
- Gate UI changes:
    - **Primary** button "Play in new tab" → target="_blank" to the
      preview endpoint.
    - **Secondary** button "Play inline" → mounts an `<iframe
      sandbox="allow-scripts allow-pointer-lock">` inside the gate
      drawer so the reviewer stays in the dashboard. Sandbox keeps
      artifact code from touching the parent dashboard.
    - Under it, a small "Open screenshots" accordion showing the
      `/tmp/qa/` shots produced by the QA agent (#5).
- Approval UX: keep "Approve / Request changes" where it is today,
  but the gate doesn't let you approve until the preview has been
  opened at least once in-session. (Soft check — a client-side
  flag, not a server enforcement. Just nudge, don't block.)

**Suggested implementation sketch.**
- New endpoint, ~15 lines:
  ```python
  @app.get("/api/projects/{project_id}/game/preview")
  async def game_preview(project_id: str, version: str = "v1"):
      html = memory_store.read_artifact(project_id, f"game_html_{version}")
      if not html:
          raise HTTPException(404, "no build artifact yet")
      # Keep it in the same origin as the dashboard so the reviewer's
      # cookies/session don't leak into the game's iframe.
      return Response(content=html, media_type="text/html")
  ```
- `GatesPanel` gate card detects when the gate's `review_of` step
  wrote a `game_html_*` artifact, and swaps the generic `<pre>`
  JSON renderer for:
  ```
  [ ▶ Play in new tab ]    [ ◨ Play inline ]
  ┌─ QA evidence ─────┐
  │  title.png        │
  │  post_move.png    │
  │  mid_combat.png   │
  └───────────────────┘
  [ ✓ Approve ]  [ ⎌ Request changes ]
  ```
- `iframe` uses `allow-scripts allow-pointer-lock allow-same-origin
  = false` to isolate it from the parent page.
- For A/B racing (improvement #4): the preview endpoint takes a
  `?agent=<id>` param, gate shows one "Play" button per candidate
  build + a pick radio group.

**Why this pairs with #1 and #5.** Improvement #1 auto-surfaces the
gate to the human. Improvement #5 certifies the build is not
statically broken. #6 is the last mile — making "review this" mean
actually playing it, not reading a code dump.

## 7. Visual style research — Roblox-grade 3D, on-brief

**Problem.** The shipped Butt Shooting Game has two compounding failures
the existing pipeline can't catch:

- **It glitches visually.** Even after the render-at-(0,0) fixes, the
  game feels cheap: flat 2D polygons on a flat canvas, abstract shapes
  with no material/lighting, no readable character silhouette. It
  reads as "arena demo," not as a game a kid would actually open.
- **It betrayed its own concept.** The brief is "Butt Shooting Game"
  — the whole joke is the butt, the recoil, the cheeky physicality of
  it. `laf_brief_v1` sanitized all of that into a generic "Cheeky
  Arena" palette with a cyan hexagon as the player. The literal
  subject of the game is missing from its own look-and-feel.

Both failures come from the same gap: neither the `technical-artist`
nor the `frontend-developer` has any grounding reference for
*what good looks like* in this genre on a platform kids actually
play. They're riffing off asset-pool thumbnails and generic
"palette + font" prompts. The output looks nothing like a Roblox
game because no one on the pipeline has been told to look at one.

**Fix direction.**
- Before `look-and-feel`, insert a `style-research` step owned by a
  `research-agent`. Its whole job is to be the eyes for the rest of
  the pipeline:
    1. Search Roblox for popular games in the same genre (top-down /
       arena / shooter / comedic-physics), including the obvious
       neighbours: *Blox Fruits*, *Arsenal*, *Da Hood*, physics-joke
       games, *Strongman Simulator*-style cheeky-body games.
    2. For each relevant reference, capture: game name, cover art URL,
       2–3 in-game screenshot URLs, a one-line note on *why it reads*
       (silhouette, palette, material vibe, camera angle, UI chrome).
    3. Also pull 2–3 references that match the *comedic subject* of
       the brief (for this game: cheeky/butt-themed Roblox avatars,
       meme-physics games, rag-doll shooters) so the laf step is
       forced to engage with the joke instead of sanitizing it.
    4. Emit a `style_research_v1` artifact: markdown with an embedded
       image grid of the references + a one-paragraph synthesis of
       "the style this project should target" (e.g. "low-poly 3D,
       stylized flat-shaded materials, bright saturated palette,
       chunky outlined UI, third-person chase camera, exaggerated
       character proportions").
- Change `look-and-feel`'s prompt to *require* it reads
  `style_research_v1` and match it: palette derived from reference
  shots (not a generic "pick 3 hex codes"), art style named as one
  of a concrete short list (low-poly 3D / stylized-3D / voxel /
  2.5D / 2D-painterly), and — crucially — an explicit "character
  design" section describing the player and enemies literally
  (silhouette, proportions, colors, attitude), not a vague mood.
- Change `frontend-developer` default to lead with 3D: prefer
  `three.js` or `babylon.js` for any project whose style research
  picks a 3D reference. Plain canvas 2D stays available, but it's
  no longer the path of least resistance.
- Make the `gate-laf` reviewer see the research grid + the chosen
  references inline (builds on improvement #2's artifact renderer),
  so "approve" means "yes, that's the target" rather than reading
  a paragraph of adjectives.

**Suggested implementation sketch.**
- New agent in `config/agents.yaml`:
  ```yaml
  style-researcher:
    model: "anthropic/anthropic.claude-opus-4-7"
    fallback_model: "anthropic/anthropic.claude-sonnet-4-6"
    description: "Research visual style references from live games"
    tools: [builtin, web_search, web_fetch, playwright_browser]
  ```
  `web_search` + `web_fetch` for Roblox listings and blog posts;
  `playwright_browser` for capturing a few cover/gameplay screenshots
  (Roblox game pages render them in-browser). Cache everything under
  `projects/<id>/assets/research/` so the gate renderer has local
  paths.
- New pipeline step in `phased-producer`, before `look-and-feel`:
  ```yaml
  - id: style-research
    agent: style-researcher
    depends_on: [gate-mechanics]
    task: |
      Read concept_options_v1 + mechanics_v1 from memory. The target
      platform style reference is Roblox. Find 6-10 live Roblox games
      that match this game's genre AND its comedic subject. For each:
      save game name, cover_url, 2-3 screenshot_urls (download locally
      to assets/research/), and a one-line note on why it reads.
      Close with a 1-paragraph synthesis: the concrete style this
      project should target (engine class, palette feel, material
      vibe, camera, character silhouette). Save to memory as
      'style_research_v1'.
    output: style_research
  ```
- `look-and-feel` step `depends_on` shifts from `[gate-mechanics]`
  to `[style-research]`; its prompt gets `style_research_v1` added
  to the required memory keys and a new "character design" output
  section that must name the player and enemies literally (for this
  game: "player is a cartoon butt with recoil-based movement;
  projectiles are …").
- `frontend-developer` prompt addendum: "If `style_research_v1`
  picks a 3D style, use three.js or babylon.js — a 3D scene is not
  optional. Fall back to 2D canvas only if the research explicitly
  calls for 2D." Include `style_research_v1` as a required memory
  read so the builder can't skip it.
- QA step from #5 gains one more assertion: the built scene must
  include a `<canvas>` that is being driven by WebGL (check
  `getContext('webgl')` returns non-null) when the research targets
  3D. Still-life 2D canvas on a 3D brief is a QA fail.

**Tradeoff.** Adds one research step + one art-asset fetch pass per
run. Roblox page scraping needs to be polite (rate-limited, cached
aggressively). But the alternative is what we shipped: an "arena
demo" where the literal subject of the game is absent and the
visual style is whatever the agent defaulted to. Kids who play
Roblox will bounce off that in 5 seconds. One research pass per
project is cheap compared to shipping something nobody plays.

**Why this pairs with #2, #3, and #5.** #2 makes asset references
visible; #7 makes them *right* by grounding the brief in live
games. #3's `tech-plan` picks the engine; #7 gives `tech-plan` a
real basis for choosing 3D. #5's QA enforces that the built game
matches the brief; #7 gives the brief enough teeth to enforce.

**Scope note — specific to this game.** For Butt Shooting Game
right now: run `style-research` once against Roblox comedy/shooter
references, then kick the current `gate-laf` back with feedback
"re-do the look-and-feel per style_research_v1, keep the butt
literal, target low-poly 3D." That's the path from the broken 2D
prototype we have to a version that actually looks like its name.
