# Proposal: Extend Asset Sources — 2026-04-18

Extend `src/runtime/asset_sources.py` + `asset_search` / `asset_fetch` tools beyond Kenney + itch. Principle: **free only, CC0 preferred, no agent-facing OAuth/key prompts.**

Companion research: [`asset-sources-research.md`](./asset-sources-research.md).

---

## TL;DR — verdicts

| Source | Verdict | Reason |
|---|---|---|
| Poly Haven | **Add (Phase 1)** | Open JSON API, CC0, HDRIs + PBR + 3D |
| ambientCG | **Add (Phase 1)** | Open JSON API, CC0, PBR textures |
| Quaternius | **Add (Phase 1)** | Static HTML, CC0, 3D + animations |
| Pixabay | **Add (Phase 2)** | Free API key, photos + music + SFX in one |
| Freesound (token-tier) | **Add (Phase 2)** | Previews + metadata only, defer OAuth |
| OpenGameArt | **Add (Phase 3)** | Wide coverage, but strict CC0 filter |
| Poly Pizza | **Defer** | Needs human-issued key |
| Incompetech | **Defer** | CC-BY attribution burden |
| **Mixamo** | **Skip** | Adobe ToS forbids automation |
| **FreePD** | **Skip** | Site permanently closed (2025) |

---

## Prerequisite refactor (non-optional)

Current `AssetHit` conflates license + content type in free-text fields. Before adding six sources, upgrade the record so governance can gate CC-BY automatically:

```python
@dataclass
class AssetLicense:
    spdx_id: str                  # "CC0-1.0" | "CC-BY-4.0" | "CC-BY-SA-4.0" | "Pixabay-Content"
    author: str | None
    attribution_url: str | None
    attribution_text: str | None  # exact credit block when CC-BY
    redistribution_ok: bool
    commercial_ok: bool

@dataclass
class AssetHit:
    pool: str
    asset_id: str
    title: str
    page_url: str
    preview_url: str | None
    download_url: str | None
    license: AssetLicense
    content_type: str             # sprite_2d | model_3d | texture | hdri | sfx | music | photo
    tags: list[str] = field(default_factory=list)
```

Then in `tool_executor._tool_asset_fetch`, gate by policy:

```python
if hit.license.spdx_id != "CC0-1.0" and not args.get("accept_attribution"):
    return json.dumps({"status": "needs_approval", "reason": "CC-BY — attribution required",
                       "attribution": hit.license.attribution_text})
```

This keeps the existing Kenney (CC0) path auto-approved while forcing governance for anything that needs a credits line.

---

## Phase 1 — Open APIs / pure CC0 (build first, no secrets)

### Poly Haven
- **Endpoints:** `https://api.polyhaven.com/assets?t=hdris|textures|models`, `/files/<slug>` for resolution map
- **Auth:** none
- **License:** CC0 — `redistribution_ok=True`, `attribution_url=None`
- **Fetcher shape:**
  ```python
  async def search_polyhaven(query, limit, kind="all", *, client=None): ...
  async def fetch_polyhaven(slug, resolution="1k", format="jpg", *, client=None) -> str: ...
  ```
- **Notes:** Prefer 1k for agents (2k–8k bloats workspace). Download URL shape: `files/<slug>/<res>_<fmt>.<ext>`.

### ambientCG
- **Endpoints:** `https://ambientcg.com/api/v2/full_json?limit=...&type=Material&q=...`
- **Auth:** none
- **License:** CC0
- **Fetcher shape:** mirror Poly Haven. Returns `downloadLink` per-resolution in JSON.
- **Tag hygiene:** keep ambientCG's controlled vocabulary (wood, metal, fabric) as `tags`.

### Quaternius
- **Endpoint:** scrape `https://quaternius.com/packs.html` once per session, cache packs list
- **Auth:** none
- **License:** CC0
- **Fetcher shape:** `search_quaternius(query)` does substring match on cached packs; `fetch_quaternius(slug)` downloads the ZIP whose `<a href>` contains the slug.
- **Notes:** Also expose `fetch_quaternius_animations()` for the Universal Animation Library — covers the Mixamo gap (humanoid only, but CC0).

**Phase 1 deliverable:** three new functions in `asset_sources.py`, three new `pool` enum values (`polyhaven | ambientcg | quaternius`), unit tests using recorded HTML/JSON fixtures.

---

## Phase 2 — Keyed APIs (add env-var config)

### Pixabay
- **Endpoint:** `https://pixabay.com/api/` (images), `/videos/`, `/api/music/` (audio)
- **Auth:** free API key via user account, header `key=<key>` in query string
- **Config:** `PIXABAY_API_KEY` env var; startup logs "Pixabay integration disabled — no key" instead of erroring
- **License:** Pixabay License — CC0-ish but **no reselling unaltered copies** and **no identifiable people in sensitive contexts**. Model as `spdx_id="Pixabay-Content"`, `redistribution_ok=False`.
- **Rate limit:** 100 req/60s — surface `X-RateLimit-Remaining` in tool response so agents back off.

### Freesound (token tier only)
- **Endpoint:** `https://freesound.org/apiv2/search/text/?query=...&token=<key>`
- **Auth:** free API key via account registration; header `Authorization: Token <key>`
- **Config:** `FREESOUND_API_KEY` env var
- **Scope:** search + metadata + **preview MP3** downloads only. Full-quality WAV needs OAuth2 — defer.
- **License:** per-sound; filter `license:"Creative Commons 0"` in query to stay CC0-only for auto-pull.
- **Rationale:** SFX agents rarely need lossless; preview MP3 is production-grade for game jam quality.

**Phase 2 deliverable:** two sources behind env flags, graceful disable when key missing, governance check that blocks non-CC0 Pixabay/Freesound unless agent passes `accept_attribution=true`.

---

## Phase 3 — Mixed-license scraping (strict filter)

### OpenGameArt
- **Endpoint:** `https://opengameart.org/art-search-advanced?keys=<q>&sort_by=count&field_art_licenses_tid%5B%5D=4` (4 = CC0)
- **Auth:** none, but respect robots.txt
- **License filter:** **only emit assets tagged purely CC0 in the search response** — assets with OR-licensing (CC0 OR CC-BY-SA) are rejected at parse time because enforcement downstream is brittle.
- **Content:** 2D sprites, tilesets, SFX loops, music — complements Kenney where Kenney lacks pixel-art variety.
- **Risk:** Drupal HTML changes periodically; pin a BeautifulSoup parser with regression fixtures.

**Phase 3 deliverable:** OpenGameArt source with hard CC0 filter, clear error if 0 results ("expand search or switch pool").

---

## Explicit "do NOT add"

### Mixamo — skip permanently
- Adobe ID OAuth, ToS forbids automated access, raw-file redistribution prohibited.
- Community scrapers break every time Adobe rotates tokens.
- If humanoid animations are genuinely needed, Quaternius' Universal Animation Library is the CC0 substitute.

### FreePD — skip, site closed
- Banner on freepd.com confirms permanent closure (2025). Replace with Pixabay Music + Freesound `music` tag queries.

### Poly Pizza — defer
- Free but key is human-issued via contact form. Revisit once someone has manually acquired a key and stored it.

### Incompetech — defer
- CC-BY 4.0 requires exact attribution per track in-game. Attribution-emitter subsystem is worth building only once multiple CC-BY sources are in play; until then Pixabay Music + Kenney Jingles cover the gap.

---

## Proposed work breakdown

1. **Refactor `AssetHit` + `AssetLicense`** — mechanical, blocks everything else. Update Kenney/itch parsers to emit the new shape. (~150 LOC + tests)
2. **Policy hook in `_tool_asset_fetch`** — gate non-CC0 behind `accept_attribution` flag; auto-emit `projects/<proj>/assets/CREDITS.md` line when used. (~60 LOC)
3. **Phase 1 sources** — Poly Haven, ambientCG, Quaternius with fixture-based tests. (~400 LOC + fixtures)
4. **Update skill doc** — append Phase 1 sources to `skills/asset-sources.md` with decision-tree deltas and sample agent flows.
5. **Phase 2 sources** behind env flags — Pixabay, Freesound token-tier. (~300 LOC)
6. **Phase 3** — OpenGameArt with CC0-only filter. (~250 LOC)
7. **Integration test** — full round-trip: agent searches "space explosion sfx" → picks top hit → fetches preview → workspace file exists → CREDITS updated.

Phase 1 alone gives agents CC0 3D + HDRIs + PBR — the biggest current gap (Kenney 3D is limited, no HDRIs at all). Phases 2-3 are additive and can ship independently.

---

## Open questions for you

1. **CC-BY policy:** auto-allow with CREDITS emission, or always route through governance approval? I've assumed governance in the proposal.
2. **Pixabay key:** you have an account to register with, or should I scope Phase 2 around Freesound-only?
3. **Workspace bloat:** should `fetch_polyhaven` default to 1k resolution? HDRI 8k files are ~80 MB each.
