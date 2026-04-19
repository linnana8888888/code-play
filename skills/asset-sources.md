---
name: Asset Sources
description: Approved external art, audio, texture, 3D, and game-asset sources agents can pull from. Use for technical-artist, game-audio-engineer, frontend-developer, and roblox-* roles.
permission: standard
---

# Asset Sources

When a game needs visuals, audio, fonts, textures, HDRIs, or 3D models, use the `asset_search` and `asset_fetch` tools. They wrap eight vetted pools. Always record the asset's source URL, author, license, and game project ID in `projects/<proj-id>/assets/MANIFEST.md` when you add anything.

**License policy (enforced by `asset_fetch`):**
- CC0 content → auto-approved, no credits required.
- Non-CC0 content (CC-BY, Pixabay License, etc.) → the tool returns `status: needs_approval`. Re-invoke with `accept_attribution: true` and the tool will append a line to `CREDITS.md` automatically.
- Previews (thumbnails) are always allowed regardless of license; use them for look-dev without commitment.

## Pool cheat sheet

| Pool | Type | License | Key needed | Best for |
|---|---|---|---|---|
| `kenney` | 2D sprites, UI, audio, fonts, some 3D | CC0 | no | Default for sprites, UI, SFX |
| `itch` | Packs (mixed) | Unknown per-pack | no | Look-dev only; manual license check |
| `polyhaven` | HDRIs, PBR textures, 3D models | CC0 | no | 3D scenes, lighting |
| `ambientcg` | PBR textures, decals, HDRIs | CC0 | no | Material library |
| `quaternius` | Low-poly 3D packs + animations | CC0 | no | 3D characters/props; Mixamo substitute |
| `pixabay` | Photos, video, music, SFX | Pixabay License | `PIXABAY_API_KEY` | Stock photo, music beds |
| `freesound` | SFX, field recordings | Mixed CC (CC0 filter available) | `FREESOUND_API_KEY` | Specific SFX search |
| `oga` | OpenGameArt (CC0-only, strict filter) | CC0 | no | Niche 2D art Kenney lacks |

## Decision tree

```
Need 2D sprites / UI / fonts?
  └─ kenney first; oga if Kenney lacks the style
Need SFX or music?
  ├─ Quick jingle → kenney
  ├─ Specific sound → freesound (needs key; filter cc0)
  └─ Music bed → pixabay (needs key)
Need 3D models?
  ├─ Low-poly → quaternius
  ├─ Realistic → polyhaven
  └─ Character animations (humanoid) → quaternius Universal Animation Library (Mixamo is blocked — no API)
Need textures / HDRIs?
  ├─ PBR material → ambientcg or polyhaven
  └─ Environment lighting → polyhaven hdris
```

## Agent workflow (look-dev phase)

1. `asset_search` with `pool="all"` for broad exploration, or a specific pool for targeted work.
2. Pick a hit, call `asset_fetch` with `kind="preview"` to pull a thumbnail for look-dev.
3. When ready, `asset_fetch` with `kind="content"` (or `kind="zip"` for Kenney/Quaternius/OGA).
4. For Poly Haven / ambientCG pass `resolution="1k"` + `format="jpg"` (default). Use `"2k"` / `"4k"` only when you have a reason — 8k HDRIs exceed the 100 MB cap.
5. If `status: needs_approval` comes back, read the license, and if you accept the attribution, re-call with `accept_attribution=true`. A line is auto-appended to the project's `CREDITS.md`.

---

## 1. Kenney.nl — preferred for sprites, UI, audio (CC0 — no attribution required)

**Root:** https://kenney.nl/assets

**License:** Creative Commons CC0 1.0 Universal — free for any use, commercial or personal, no attribution required.

**Strengths:** Cohesive style per pack, consistent naming, PNG + SVG + spritesheets, mobile-friendly sizes, 2D/3D/audio all covered.

### Packs most useful for Code PLAY games

| Genre | Pack | Direct URL |
|-------|------|------------|
| Space / meteor / dodge | Space Shooter Redux | https://kenney.nl/assets/space-shooter-redux |
| Platformer | Platformer Art Deluxe | https://kenney.nl/assets/platformer-art-deluxe |
| Puzzle / match | Puzzle Pack | https://kenney.nl/assets/puzzle-pack |
| Top-down RPG | Tiny Town / Tiny Dungeon | https://kenney.nl/assets/tiny-town |
| UI | UI Pack (Space Expansion) | https://kenney.nl/assets/ui-pack-space-expansion |
| UI general | UI Pack (RPG Expansion) | https://kenney.nl/assets/ui-pack-rpg-expansion |
| SFX | Interface Sounds | https://kenney.nl/assets/interface-sounds |
| SFX | Digital Audio / Impact Sounds | https://kenney.nl/assets/impact-sounds |
| Music | Music Jingles | https://kenney.nl/assets/music-jingles |
| Fonts | Kenney Fonts | https://kenney.nl/assets/kenney-fonts |

### How to pull a Kenney pack (agent flow)

1. Visit the pack URL and click the download button. Kenney serves a ZIP directly (no login, no token).
2. Save ZIP to `projects/<proj-id>/assets/raw/kenney-<pack-slug>.zip`.
3. Unzip into `projects/<proj-id>/assets/<pack-slug>/`.
4. Append an entry to `projects/<proj-id>/assets/MANIFEST.md`:
   ```
   - kenney/space-shooter-redux — CC0 — https://kenney.nl/assets/space-shooter-redux — sprites, particle FX
   ```
5. Reference sprites by relative path in code — never hotlink to kenney.nl.

### Shell snippet agents can run

```bash
PACK="space-shooter-redux"
PROJ_DIR="projects/$PROJECT_ID/assets"
mkdir -p "$PROJ_DIR/raw"
curl -L "https://kenney.nl/content/3-assets/12-space-shooter-redux/space-shooter-redux.zip" \
  -o "$PROJ_DIR/raw/kenney-$PACK.zip"
unzip -q "$PROJ_DIR/raw/kenney-$PACK.zip" -d "$PROJ_DIR/$PACK"
```

(URLs occasionally change — if the direct ZIP 404s, scrape the pack page for the latest download link.)

---

## 2. itch.io — broader catalog, mixed licenses (always check)

**Root:** https://itch.io/game-assets/free

**License:** Per-creator. **Always read the asset page's license before using.** Common licenses: CC0, CC-BY 4.0 (attribution required), free-for-personal-use (not safe for studio), custom. When in doubt, skip.

**Strengths:** Larger variety, unique art styles, pixel-art heavy, quirky audio, fills gaps Kenney doesn't cover.

### Useful search filters

- **Free + CC0:** https://itch.io/game-assets/free/tag-public-domain
- **Free + CC-BY:** https://itch.io/game-assets/free (check each page)
- **By type:** https://itch.io/game-assets/tag-sprites  ·  https://itch.io/game-assets/tag-audio  ·  https://itch.io/game-assets/tag-music

### How to pull an itch.io asset (agent flow)

1. Open the asset page (e.g., `https://itch.io/assetpack/example-pack`).
2. **Check license.** Record exact wording. If "free-for-personal-use only" → abort, do not use for studio games.
3. If creator requires attribution (CC-BY), capture the attribution string required.
4. Click Download. Some packs require setting a $0 price at the "name your price" prompt — that is fine.
5. Save ZIP to `projects/<proj-id>/assets/raw/itch-<creator>-<pack>.zip`, unzip into `projects/<proj-id>/assets/<pack>/`.
6. Append MANIFEST entry **with attribution string** if CC-BY:
   ```
   - itch/<creator>/<pack> — CC-BY 4.0 — https://itch.io/... — "Art by <creator>" (must appear in credits)
   ```

### Safety rules for itch.io

- **Never auto-purchase.** If the listing isn't $0, flag it to the producer via governance approval request — don't spend money without sign-off.
- **No scraping of paid assets.** If a creator gated the download, respect it.
- **Credit page.** Every game with CC-BY assets must emit a `CREDITS.md` at the project root listing each required attribution.

---

## 3. Poly Haven — CC0 HDRIs, PBR textures, 3D models

**Root:** https://polyhaven.com · **API:** https://api.polyhaven.com

CC0, no attribution. Best for 3D scene lighting (HDRIs), realistic PBR materials, and high-quality 3D props. Default to 1k resolution (`"1k"`) for agent use — 4k/8k blow past the 100 MB download cap.

## 4. ambientCG — CC0 PBR textures, decals, HDRIs

**Root:** https://ambientcg.com

CC0, no attribution. Complements Poly Haven with a larger material library (3,000+ PBR materials). Use ambientcg for tiling textures, decals, and substance-style materials; use Poly Haven for HDRIs and curated 3D models.

## 5. Quaternius — CC0 low-poly 3D + animations

**Root:** https://quaternius.com

CC0. Low-poly packs (nature, space, medieval, sci-fi) and the **Universal Animation Library** (humanoid animations, CC0). This is the Mixamo substitute — Mixamo itself is blocked because Adobe ToS forbids automated access.

## 6. Pixabay — photos, video, music, SFX (key required)

**Root:** https://pixabay.com · **API:** https://pixabay.com/api/

Free API key (set `PIXABAY_API_KEY` env var). **Not CC0** — uses the Pixabay Content License: commercial OK, but selling unaltered copies is prohibited and identifiable people in sensitive contexts is forbidden. `asset_fetch` will require `accept_attribution=true` for this source.

## 7. Freesound — SFX / music (key required)

**Root:** https://freesound.org · **API:** https://freesound.org/apiv2/

Free API key (set `FREESOUND_API_KEY` env var). Mixed CC (CC0, CC-BY, CC-BY-NC). By default `search_freesound` filters to CC0 only; pass `cc0_only=False` for broader search (then `asset_fetch` will gate CC-BY behind `accept_attribution`). The token tier returns preview MP3s — adequate for game-jam quality; full-quality WAV requires OAuth2 (not implemented).

## 8. OpenGameArt — CC0 filter only

**Root:** https://opengameart.org

OpenGameArt allows mixed and OR-licensing, which is a compliance nightmare. Our scraper **only returns assets tagged purely CC0** — other licenses are dropped silently at search time, and `asset_fetch` double-checks the asset page before downloading.

---

## Do NOT use

- **Mixamo** — Adobe ToS forbids automated access; raw-file redistribution is prohibited. Use Quaternius' Universal Animation Library instead.
- **FreePD** — site permanently closed (2025).
- **Incompetech** — CC-BY 4.0 requires per-track attribution; defer until a dedicated attribution subsystem exists.
- **Poly Pizza** — API free but key is human-issued via contact form; revisit once a key is obtained and stored in env.

---

## Manifest format

Every project that uses external assets must have `projects/<proj-id>/assets/MANIFEST.md`:

```markdown
# Asset Manifest — <project name>

## External packs
- kenney/space-shooter-redux — CC0 — https://kenney.nl/assets/space-shooter-redux — sprites, projectiles
- itch/creator-name/pack — CC-BY 4.0 — https://itch.io/... — attribution: "Art by Creator Name"

## Credits required in-game
- Creator Name (itch.io) — for the pack-name asset pack

## Generated assets
- (list any AI-generated or custom-drawn assets here)
```
