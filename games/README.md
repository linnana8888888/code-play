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
  kind: external | internal
  repo: https://github.com/<owner>/<repo>   # external only
  path: <relative/path>                      # internal only (relative to code-play root)
versions:
  - label: v2
    ref: <sha-or-tag-or-branch>              # pinned reference the publisher checks out
    entry: index.html                        # HTML5 entry point, relative to source root
    status: draft | qa-passing | shipped | retired
    released_at: <YYYY-MM-DD | null>
    notes: <one line>
    published:
      itch:     <url | null>
      gh_pages: <url | null>
      roblox:   <url | null>
```

## How the publisher uses this file

`publish-prep` resolves `source` → checks out `versions[*].ref` in a temp
worktree → packages the `entry` file into a flat itch-compatible zip. No
ambiguity about which commit ships.

- `source.kind: external` → `git clone --depth 1 --branch <ref>` from `source.repo`
  into a temp dir; fall back to `git fetch origin <ref> && git checkout <ref>` if
  `ref` is a sha.
- `source.kind: internal` → read directly from `<code-play-root>/<path>`.

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
4. Commit. The publisher picks it up automatically on the next run.
