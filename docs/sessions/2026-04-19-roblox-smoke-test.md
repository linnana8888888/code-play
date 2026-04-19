# Session: Roblox Open Cloud smoke test

**Date:** 2026-04-19
**Branch:** `feature/publisher-agent` → pushed as `8b39843`
**Target:** prove the publisher's rojo-build → `.rbxlx` → Open Cloud publish chain end-to-end.

## Outcome

`POST https://apis.roblox.com/universes/v1/10056703970/places/126715565755517/versions?versionType=Published` → HTTP 200 `{"versionNumber": 4}`.

- Universe: `10056703970`
- Place: `126715565755517`
- Artifact: `artifacts/roblox-smoke-test/roblox-smoke-test.rbxlx` (3708 bytes, XML, built from `default.project.json`)
- Public `/games/<placeId>` URL returns 404 — **expected**, place visibility is private. Flip in Creator Hub when ready for live play.

## What worked

- Rojo tree (baseplate + `ReplicatedStorage/SmokeTest.luau` + `ServerScriptService/Hello.server.luau`) builds clean.
- `curl -X POST … --data-binary @…rbxlx -H "x-api-key: …" -H "Content-Type: application/octet-stream"` is the right shape for the v1 endpoint. v2 `:publishVersion` returned 404 during a diagnostic — not pursued once the root cause surfaced.
- `games/roblox-smoke-test.yaml` `published.roblox` + `roblox_version_number` patched in place; status flipped to `shipped`.

## Root cause of the initial 401

First attempt returned `401 "API Key has insufficient scopes"`. The scopes were correct; the key was issued on the wrong Roblox account (BananaCoco888, `ownerId` 9559160825) while the universe belongs to a different account (`ownerId` 10484156079). Decoded the JWT payload of the replacement key to confirm `ownerId` matched before re-running.

**Takeaway for publisher agent:** add a preflight that decodes the JWT claim `ownerId` and compares against the `universe_id`'s owner before attempting publish. A scope error on Open Cloud can be either a scope problem *or* an account-mismatch problem; the error string doesn't distinguish them.

## Open follow-ups

- **Rotate the Roblox API key.** The successful key value appeared in session transcript. Revoke + reissue in Creator Dashboard.
- **Decide on place visibility.** Private is fine for a plumbing test; if the publisher's live-verification step is supposed to HEAD the listing page for real, the test universe needs to be public (or the verification step needs a "private place expected" branch).
- **Optional:** add an Open Cloud JWT-owner preflight to the publisher's Roblox-only preflight block in `config/pipelines.yaml` / `agents/production/publisher.md`.

## Git trail

- Commit: `8b39843 feat(publisher): prove Roblox Open Cloud chain end-to-end`
- Rebased on top of `f051571` (which had dropped the compliance tier) — resolved 6 hunks in `publisher.md` + `pipelines.yaml`, kept all Roblox-specific additions, dropped compliance-adjacent content.
- Files touched: `agents/production/publisher.md`, `config/pipelines.yaml`, `games/roblox-smoke-test.yaml`, `games/README.md`, `.gitignore` (+ `artifacts/roblox-smoke-test/*`).
- `.env` is gitignored; key value never committed.
