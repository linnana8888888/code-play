# Asset Sources Research — 2026-04-18

Consolidated findings for extending `src/runtime/asset_sources.py` beyond Kenney + itch.

## Feasibility table

| Source | API? | Auth | License | Content | Verdict |
|---|---|---|---|---|---|
| OpenGameArt.org | No (scrape) | none | **Mixed** CC0/CC-BY/CC-BY-SA/GPL/OGA-BY — multi-license OR | 2D sprites, 3D, textures, music, SFX | Add, CC0-filter only |
| Quaternius | No (static HTML) | none | **CC0** | 3D glTF/FBX, animations | Add |
| Poly Pizza | Yes `api.poly.pizza` | **free key (manual request)** | CC-BY + CC0 | 3D low-poly glTF | Defer — key gating |
| Poly Haven | Yes `api.polyhaven.com` (open) | none | **CC0** | HDRIs, PBR textures, 3D | Add first |
| ambientCG | Yes `ambientcg.com/api/v3/` | none | **CC0** | PBR textures, HDRIs, decals | Add first |
| Mixamo | No public API | Adobe OAuth, ToS forbids automation | Adobe custom, no redistribution | Rigged chars + anims | **Skip** |
| Freesound.org | Yes `apiv2` | key for search; OAuth2 for full dl | Mixed CC (CC0, CC-BY, CC-BY-NC, Sampling+) | Audio / SFX | Add, token-tier only (previews + metadata) |
| FreePD | — | — | — | — | **Skip — site permanently closed** |
| Incompetech | No | none | **CC-BY 4.0** — attribution required | Music | Defer — attribution burden |
| Pixabay | Yes `/api/` | free key | Pixabay License (CC0-ish carve-outs) | Photos, video, music, SFX | Add |

## Gotchas (what makes this non-trivial)

- **FreePD is dead** — banner confirms site closed; substitute with Incompetech + Pixabay for music.
- **Mixamo is a legal trap** — Adobe ToS prohibits automated access, raw-file redistribution forbidden.
- **OpenGameArt license soup** — single asset may list multiple licenses with OR semantics; must record ALL and surface attribution from the "Copyright/Attribution Notice" field.
- **Poly Pizza key is manual** — contact-form issued, no self-service; plan secrets file + manual onboarding.
- **Poly Haven + ambientCG are the gold standard** — open JSON, CC0, stable URLs. Implement first to validate the abstraction.
- **Freesound is two-tier**: token auth for search/metadata/previews; OAuth2 only for full-quality downloads.
- **Pixabay API ≠ HTML** — API blessed, HTML Cloudflare-gated. Never fall back to scraping.
- **Incompetech attribution is prescriptive** — exact credit block required per-track; fetcher must emit CREDITS.
- **Quaternius is scrape-safe** — single static HTML page lists every pack; trivial regex.

## Architecture implications

Before wiring six more sources, refactor `AssetHit` into a richer record:

```python
@dataclass
class AssetLicense:
    spdx_id: str              # "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", ...
    author: str | None
    attribution_url: str | None
    attribution_text: str | None  # exact credit string when required
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
    content_type: str        # "sprite_2d" | "model_3d" | "texture" | "hdri" | "sfx" | "music" | "photo"
```

This enables a single CC0-filter policy ("agents may auto-pull CC0; CC-BY requires governance approval") and auto-generation of CREDITS.md.

## Recommended integration order

1. **Poly Haven** — easiest, highest value (HDRIs + PBR for 3D scenes)
2. **ambientCG** — same shape, complements Poly Haven textures
3. **Quaternius** — static scrape, pure CC0 3D models
4. **Pixabay** — photos/music/SFX, one API key covers three content types
5. **Freesound (token tier)** — SFX search with previews; defer OAuth
6. **OpenGameArt** — CC0 filter only; skip mixed-license listings
7. **Poly Pizza** — after key obtained
8. **Incompetech** — only if music gap remains; requires attribution-emitter

Skip: **Mixamo, FreePD**
