# Published Games

Index of every build that has shipped through the `publisher` agent to a live URL.
Newest first. Each row corresponds to a `publish_manifest_v<N>` in project memory.

| Date | Title | Engineering codename | itch.io | GH Pages | Roblox | Version | Rating | Agents |
|------|-------|----------------------|---------|----------|--------|---------|--------|--------|
| 2026-04-19 | Cheekshot | butt-shooting-game | 🟢 [live](https://linnana8888888.itch.io/cheekshot) (build #1623921, v4-2cb373a) | ⚪ skipped at gate | ⚪ n/a | v4 (`2cb373a`) | waived (smoke test) | publisher |
| 2026-04-19 | Roblox Smoke Test | roblox-smoke-test | ⚪ n/a | ⚪ n/a | 🟢 [live](https://www.roblox.com/games/126715565755517) (private, public URL 404s) | v1 (`HEAD`, versionNumber 4) | waived (smoke test) | publisher |
| 2026-04-19 | Cheekshot | butt-shooting-game | 🟢 [live](https://linnana8888888.itch.io/cheekshot) | ⚪ skipped at gate | ⚪ n/a | v3 (`c1fa6d8`) | waived (smoke test) | publisher |

## Column notes

- **Title** — the twisted ship name, human-approved at `gate-publish`.
- **Engineering codename** — the working slug from `artifacts/` / `docs/` (`butt-shooting-game-v2`, `dodge-meteors-v2`, etc.).
- **itch.io / GH Pages / Roblox** — `🟢 live` (+ short URL), `🟡 live-but-flagged` (console errors on live page), `⚪ skipped at gate`, `🔴 failed` (link to debug task).
- **Agents** — who touched this build, from the phased-producer chain (concept → mechanics → style-research → laf → tech-plan → build → qa → review → publish). Content rating is set by each target platform's own review process — itch.io/GH Pages/Roblox all run their own kids-audience compliance checks at submission.

## Adding a row

The `publish` step appends to this file automatically. Manual edits only for corrections (e.g., marking a retired listing, adding post-launch notes).

## Retired / taken down

_None._
