# Games Index

One YAML file per title. This is the studio's catalog — not where code lives.
Each game is its own repo (or a subdirectory of this one, historically) and
every version/iteration is pinned to an explicit `ref` so the publisher can
reproduce a build exactly.

## Shape

```yaml
slug: <engineering-codename>      # matches filename: games/<slug>.yaml
title: <engineering title>         # ship title is chosen at gate-publish, not here
status: active | archived | draft
source:
  kind: external | internal | rojo
  repo: https://github.com/<owner>/<repo>   # external or rojo
  path: <relative/path>                      # internal only (relative to code-play root)
  project: default.project.json              # rojo only — Rojo project file at repo root
roblox:                                      # required when any version targets Roblox (source.kind = rojo)
  universe_id: <int>                         # from https://create.roblox.com/dashboard/creations (URL)
  place_id:    <int>                         # the startup place ID under that universe
  visibility:  public | private
  api_key_env: ROBLOX_OPEN_CLOUD_KEY         # env var NAME (never the literal key)
versions:
  - label: v2
    ref: <sha-or-tag-or-branch>              # pinned reference the publisher checks out
    entry: index.html                        # HTML5 entry point — HTML targets only
    rojo_entry: default.project.json         # Rojo project override — Roblox targets only (optional)
    status: draft | qa-passing | shipped | retired
    released_at: <YYYY-MM-DD | null>
    notes: <one line>
    published:
      itch:                    <url | null>
      gh_pages:                <url | null>
      roblox:                  <url | null>                   # https://www.roblox.com/games/<place_id>
      roblox_version_number:   <int | null>                   # Open Cloud versionNumber — needed for rollback
```

## How the publisher uses this file

`publish-prep` resolves `source` → checks out `versions[*].ref` in a temp
worktree → packages the build for whichever targets are approved. No ambiguity
about which commit ships.

- `source.kind: external` → `git clone --depth 1 --branch <ref>` from `source.repo`
  into a temp dir; fall back to `git fetch origin <ref> && git checkout <ref>` if
  `ref` is a sha. Used for HTML5 games (itch.io, gh-pages).
- `source.kind: internal` → read directly from `<code-play-root>/<path>`. Also
  HTML5.
- `source.kind: rojo` → clone like `external`, then run
  `rojo build --output artifacts/<slug>/dist/<label>/<slug>.rbxlx` against
  `source.project` (default `default.project.json`). The `.rbxlx` is the
  uploadable artifact — Open Cloud wants the raw file in the POST body.
  Roblox-only; HTML targets are skipped.

## Updating this index

- **New version of an existing game:** add a new entry to `versions:`, pin
  `ref` to a tag or sha (not a branch name unless the branch is intentionally
  the tip).
- **New game:** add a file `games/<slug>.yaml`. No other registration needed —
  the publisher discovers games by filename.
- **Shipped a build:** `publish` writes the `published.<target>` URL and flips
  `status: shipped`. Manual edits only for corrections.

## Adding a game

1. Ensure the game has a live git repo (external or internal path).
2. Copy the shape above into `games/<slug>.yaml`.
3. Pin each historical version's `ref` to a sha — branches move, sha's don't.
4. For Roblox targets: create the universe + place in Roblox first (see
   `../ROBLOX_SETUP.md`), add the `roblox:` block with those IDs, and make
   sure the env var named by `roblox.api_key_env` is set in `.env`.
5. Commit. The publisher picks it up automatically on the next run.

## Worked example: a Roblox game

```yaml
slug: moonrump
title: Moonrump (Roblox)
status: active
source:
  kind: rojo
  repo: https://github.com/linnana8888888/moonrump
  project: default.project.json
roblox:
  universe_id: 4871234567
  place_id:    7701234567
  visibility:  private
  api_key_env: ROBLOX_OPEN_CLOUD_KEY
versions:
  - label: v1
    ref: a1b2c3d
    rojo_entry: default.project.json
    status: draft
    released_at: null
    notes: Initial Rojo build — bare lobby + player character.
    published:
      itch:                    null
      gh_pages:                null
      roblox:                  null
      roblox_version_number:   null
```

Note the absence of a compliance-auditor step in the pipeline — the publisher
does its own kids-audience tone check at `gate-publish`. For Roblox the bar is
stricter because Roblox moderates post-hoc, so the publisher will flag borderline
titles/descriptions for human review rather than pushing through.
