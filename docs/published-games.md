# Published Games

Index of every build that has shipped through the `publisher` agent to a live URL.
Newest first. Each row corresponds to a `publish_manifest_v<N>` in project memory.

| Date | Title | Engineering codename | itch.io | GH Pages | Roblox | Version | Rating | Agents |
|------|-------|----------------------|---------|----------|--------|---------|--------|--------|
| _—_ | _no ships yet_ | | | | | | | |

## Column notes

- **Title** — the twisted ship name, human-approved at `gate-publish`.
- **Engineering codename** — the working slug from `artifacts/` / `docs/` (`butt-shooting-game-v2`, `dodge-meteors-v2`, etc.).
- **itch.io / GH Pages / Roblox** — `🟢 live` (+ short URL), `🟡 live-but-flagged` (console errors on live page), `⚪ skipped at gate`, `🔴 failed` (link to debug task).
- **Rating** — from `compliance_audit_v1`. No publish happens without one.
- **Agents** — who touched this build, from the phased-producer chain (concept → mechanics → style-research → laf → tech-plan → build → qa → review → publish).

## Adding a row

The `publish` step appends to this file automatically. Manual edits only for corrections (e.g., marking a retired listing, adding post-launch notes).

## Retired / taken down

_None._
