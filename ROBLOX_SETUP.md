# Roblox Open Cloud Setup — publishing credentials

One-time setup for the `publisher` agent to push `.rbxlx` builds to Roblox via
Open Cloud. Do this yourself; don't delegate to an agent. The API key lives on
your machine only.

Note: compliance-auditor is no longer in the pipeline. The publisher does its
own kids-audience tone check at `gate-publish`. Roblox moderates post-hoc, so
the tone-check bar is stricter for Roblox targets than for itch.io — when in
doubt on a Roblox publish, surface the concern at the gate rather than shipping.

## 1. Create a Roblox creator account (skip if you have one)

- Go to https://www.roblox.com/CreateAccount
- Date of birth must be 13+ to access Creator Hub and Open Cloud
- Verify your email (Account Settings → Account Info → Add Email)
- Optional but recommended: enable 2FA — Open Cloud keys are tied to this account

## 2. Install Rojo (the build tool)

Rojo converts a filesystem tree of Luau scripts + Rojo project JSON into an
uploadable `.rbxlx`. macOS:

```bash
# Option A: Foreman (Rojo's recommended toolchain manager, preferred)
brew install foreman
cd <your-roblox-game-repo>
foreman install         # installs rojo + any other tools pinned in foreman.toml

# Option B: direct via cargo
cargo install rojo
```

Verify:
```bash
rojo --version
# should print: Rojo 7.X.Y
```

## 3. Create the universe + place on Roblox (the equivalent of itch's draft page)

Open Cloud refuses to publish to a universe/place that doesn't exist yet.
Create them first via Roblox Studio or the Creator Hub:

1. Open https://create.roblox.com/dashboard/creations
2. Click **Create Experience**
3. Pick a genre (doesn't matter — the publisher doesn't use this)
4. Creation name: anything — the publisher will rename at first publish via the
   Experiences API (not wired yet; for v1 set the listing name in the Creator
   Hub UI and let the publisher only update the place contents)
5. Privacy: **Private** for now — flip to public after your first smoke test
6. Save — this creates both a **Universe** (the game as a whole, with listing
   metadata) and a **Place** (the startup place, where the code actually lives)
7. From the Creations list, click into your new experience and grab:
   - **Universe ID** — URL looks like
     `https://create.roblox.com/dashboard/creations/experiences/{UNIVERSE_ID}/...`
   - **Place ID** — Under **Places**, find the startup place and copy its ID
     (also visible in the URL: `/places/{PLACE_ID}/...`)
8. Record both IDs — they go into `games/<slug>.yaml` under `roblox:` (see
   `games/README.md` for the shape).

## 4. Generate the Open Cloud API key

1. Go to https://create.roblox.com/dashboard/credentials
2. Click **Create API Key**
3. Name: something identifiable (e.g. `code-play-publisher-<slug>`)
4. Access Permissions:
   - Experience: **Place Management**
   - Universe: the one you created in step 3
   - Operations: **Write** (this is what `versionType=Published` needs)
5. Accepted IP Addresses: your dev machine's public IP (find it with
   `curl ifconfig.me`). Use `0.0.0.0/0` only if you really need to — IP pinning
   is cheap insurance.
6. Expiration: 30-180 days is a reasonable sweet spot. Shorter = more rotation
   churn; longer = more exposure if leaked.
7. **Save & Generate** — copy the key immediately. Roblox shows it once. If you
   lose it, delete the key and make a new one.

## 5. Store the key in `.env`

```bash
# ~/code-play/.env
ROBLOX_OPEN_CLOUD_KEY=<paste the key here>
```

The env var name you use here must match the `roblox.api_key_env` field in
`games/<slug>.yaml`. `ROBLOX_OPEN_CLOUD_KEY` is the suggested default, but you
can use per-game names if you're rotating a different key per title.

Make sure `.env` is in `.gitignore`. It is by default in this project — verify
with `grep -n ".env" .gitignore`.

## 6. Smoke-test Open Cloud from your machine

Before you let an agent touch it, prove it works yourself. Use any small
Rojo project for this — a bare `default.project.json` with one BasePart will
do.

```bash
# 1. Build a tiny .rbxlx
cd <your-test-rojo-project>
rojo build --output /tmp/smoke-test.rbxlx

# 2. Upload via curl (wildly more auditable than agent tooling for a first test)
curl -X POST \
  "https://apis.roblox.com/universes/v1/<UNIVERSE_ID>/places/<PLACE_ID>/versions?versionType=Published" \
  -H "x-api-key: $ROBLOX_OPEN_CLOUD_KEY" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @/tmp/smoke-test.rbxlx

# Expected response:
# {"versionNumber": N}   — N starts at 1 and increments each publish
```

If you get `401` the key is wrong. `403` usually means the key isn't scoped
to that universe or the IP allowlist blocks your current address. `413`
means the `.rbxlx` exceeds Roblox's size limit for Open Cloud (check the
current cap in the Roblox docs — it has moved over time).

Then eyeball the live listing:
```
open https://www.roblox.com/games/<PLACE_ID>
```
You should see the default Roblox lobby rendering at the place you just pushed
— that's the smoke test passing.

## 7. What the `publisher` agent does with the key

- Reads `ROBLOX_OPEN_CLOUD_KEY` (or whatever the game's `roblox.api_key_env`
  points at) from `.env` via the project's existing secret loader.
- Wraps the `POST /universes/v1/.../versions` call behind the restricted
  `roblox_publish` tool — the same approval-queue pattern as `itchio_publish`.
- The key is never logged, never echoed in agent transcripts, never sent to an
  LLM request body. If you see it surfacing anywhere, that's a bug — flag it.
- Records the returned `versionNumber` in `publish_manifest_v1` so the next
  publish knows what to roll back to via `copySourceVersion={N-1}`.

## 8. Rollback

Roblox supports one-call rollback via `copySourceVersion`. To re-point the
place at version `N-1`:

```bash
curl -X POST \
  "https://apis.roblox.com/universes/v1/<UNIVERSE_ID>/places/<PLACE_ID>/versions?versionType=Published&copySourceVersion=<N-1>" \
  -H "x-api-key: $ROBLOX_OPEN_CLOUD_KEY"
# Response: {"versionNumber": N+1}  — it creates a new version whose content
# is a copy of <N-1>. No body required.
```

The publisher always records the prior `version_number` in the manifest so
this operation is a single command away.

## 9. Rotation

If the key ever leaks:

1. Go to https://create.roblox.com/dashboard/credentials
2. Find the key, click **⋮ → Delete** — this invalidates it server-side
3. Create a new one with the same scopes
4. Update `.env` with the new value

Roblox has no "rotate in place" — delete-and-create is the only path. This is
why scoping the key tightly (one universe, IP pinned) matters more than it
does for butler.

## 10. What this does NOT cover

- **Listing metadata** (title, description, thumbnails, genre) — those live on
  the universe, not the place, and use a different Open Cloud endpoint
  (`/cloud/v2/universes/{universe_id}`). For v1 the publisher only updates the
  place contents; metadata is set in the Creator Hub UI.
- **Monetization / passes / gamepasses** — separate setup.
- **Multi-place universes** — only the startup place is currently supported by
  the publisher. If a game uses teleport-linked secondary places, adding them
  is a future extension.

## Reference

- Roblox Open Cloud docs: https://create.roblox.com/docs/cloud
- Publish Place API reference: https://create.roblox.com/docs/cloud/reference/Place
- Rojo docs: https://rojo.space/docs/
