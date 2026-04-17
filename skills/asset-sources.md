---
name: Asset Sources
description: Approved external art, audio, and game-asset sources agents can pull from. Use for technical-artist, game-audio-engineer, level-designer, frontend-developer, and roblox-* roles.
permission: standard
---

# Asset Sources

When a game needs visuals, audio, fonts, or ready-made assets, pull from these two sources first. Both are legally safe for studio use (commercial-friendly licenses) and ship in consumable formats (PNG/SVG/WAV/MP3).

Always record the asset's source URL, author, license, and game project ID in `projects/<proj-id>/assets/MANIFEST.md` when you add anything so the producer can audit provenance later.

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

## Decision tree

```
Need 2D sprites or audio?
  ├─ Quick + cohesive + no attribution → Kenney first
  ├─ Pixel art / unusual style Kenney doesn't cover → itch.io (CC0 tag)
  └─ Very specific theme → itch.io search, then license-check

Need UI or fonts?
  └─ Kenney UI Pack almost always has it.

Need 3D assets?
  └─ Kenney has some (Space Kit, City Kit). itch.io coverage is thinner — ask producer.

Need music loops?
  ├─ Short jingles → Kenney Music Jingles
  └─ Full background track → itch.io CC0 music
```

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
