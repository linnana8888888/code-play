"""Asset library integrations.

Shared resource pools for agents:
  - kenney    — kenney.nl CC0 game art packs (2D, 3D, audio, UI, fonts)
  - itch      — itch.io game-assets marketplace (mixed licenses)
  - polyhaven — polyhaven.com CC0 HDRIs, PBR textures, 3D models
  - ambientcg — ambientcg.com CC0 PBR textures, decals, HDRIs
  - quaternius — quaternius.com CC0 low-poly 3D packs + universal animations
  - pixabay   — pixabay.com photos/video/music/SFX (Pixabay License, free key)
  - freesound — freesound.org SFX/music (CC0/CC-BY, free token)
  - oga       — opengameart.org CC0-filtered subset

The module exposes:
  * `search_<pool>` — async search
  * `_parse_<pool>` — pure HTML/JSON parsers (unit-testable without network)
  * `fetch_<pool>` — resolve and download an asset by id
  * `download` — generic stream-to-file helper

Every `AssetHit` carries a structured `AssetLicense` so the tool executor can
gate non-CC0 downloads behind governance and emit CREDITS entries for CC-BY.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import quote_plus

import httpx

USER_AGENT = "code-play-agent/1.0 (asset-search)"
TIMEOUT = 20.0


# --- license + hit records ------------------------------------------------

@dataclass
class AssetLicense:
    spdx_id: str                        # "CC0-1.0" | "CC-BY-4.0" | "Pixabay-Content" | "Unknown"
    author: str | None = None
    attribution_url: str | None = None
    attribution_text: str | None = None  # exact credit string, required for CC-BY
    redistribution_ok: bool = True
    commercial_ok: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


CC0 = AssetLicense(spdx_id="CC0-1.0", redistribution_ok=True, commercial_ok=True)
UNKNOWN_LICENSE = AssetLicense(spdx_id="Unknown", redistribution_ok=False, commercial_ok=False)


@dataclass
class AssetHit:
    pool: str
    asset_id: str
    title: str
    page_url: str
    preview_url: str | None
    download_url: str | None = None
    license: AssetLicense = field(default_factory=lambda: AssetLicense(spdx_id="Unknown"))
    content_type: str = "unknown"       # sprite_2d | model_3d | texture | hdri | sfx | music | photo | pack
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# --- kenney.nl ------------------------------------------------------------

KENNEY_BASE = "https://kenney.nl"


async def search_kenney(query: str, limit: int = 8, *, client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    url = f"{KENNEY_BASE}/assets/series:?search={quote_plus(query)}"
    html = await _get(url, client=client)
    return _parse_kenney(html, limit)


def _parse_kenney(html: str, limit: int = 8) -> list[AssetHit]:
    pattern = re.compile(
        r"""<a\s+[^>]*href=['"]((?:https?://kenney\.nl)?/assets/([A-Za-z0-9][A-Za-z0-9_\-]*))['"][^>]*>"""
        r"""\s*<div[^>]*class=['"][^'"]*cover[^'"]*['"][^>]*style=['"][^'"]*background-image\s*:\s*url\(["']?([^"')]+)["']?\)"""
        r"""[^>]*>\s*</div>\s*</a>\s*"""
        r"""<h2[^>]*>\s*<a[^>]*>([^<]+)</a>""",
        re.DOTALL,
    )
    hits: list[AssetHit] = []
    seen: set[str] = set()
    for m in pattern.finditer(html):
        slug = m.group(2)
        if slug in seen:
            continue
        seen.add(slug)
        preview = m.group(3)
        if preview.startswith("/"):
            preview = KENNEY_BASE + preview
        hits.append(AssetHit(
            pool="kenney",
            asset_id=f"kenney:{slug}",
            title=m.group(4).strip(),
            page_url=f"{KENNEY_BASE}/assets/{slug}",
            preview_url=preview,
            license=CC0,
            content_type="pack",
        ))
        if len(hits) >= limit:
            break
    return hits


async def resolve_kenney_zip(slug: str, *, client: httpx.AsyncClient | None = None) -> str | None:
    html = await _get(f"{KENNEY_BASE}/assets/{slug}", client=client)
    m = re.search(
        r"""['"](https?://kenney\.nl/media/pages/assets/[^'"]+\.zip|/media/pages/assets/[^'"]+\.zip)['"]""",
        html,
    )
    if not m:
        return None
    url = m.group(1)
    return url if url.startswith("http") else KENNEY_BASE + url


# --- itch.io -------------------------------------------------------------

ITCH_BASE = "https://itch.io"


async def search_itch(query: str, limit: int = 8, *, client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    url = f"{ITCH_BASE}/game-assets?q={quote_plus(query)}"
    html = await _get(url, client=client)
    return _parse_itch(html, limit)


def _parse_itch(html: str, limit: int = 8) -> list[AssetHit]:
    start_rx = re.compile(r'<div\b[^>]*\bdata-game_id="(\d+)"[^>]*class="[^"]*game_cell')
    starts = [(m.group(1), m.start()) for m in start_rx.finditer(html)]
    if not starts:
        return []

    href_rx = re.compile(
        r'<a[^>]*class="[^"]*title[^"]*"[^>]*href="(https?://[^"]+\.itch\.io/[^"#?]+)"'
    )
    title_rx = re.compile(r'class="[^"]*title[^"]*"[^>]*>([^<]+)</a>')
    preview_rx = re.compile(r'data-lazy_src="([^"]+)"')

    hits: list[AssetHit] = []
    for idx, (game_id, start) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(html)
        inner = html[start:end]
        href = href_rx.search(inner)
        title = title_rx.search(inner)
        preview = preview_rx.search(inner)
        if not href or not title:
            continue
        hits.append(AssetHit(
            pool="itch",
            asset_id=f"itch:{game_id}",
            title=title.group(1).strip(),
            page_url=href.group(1),
            preview_url=preview.group(1) if preview else None,
            license=UNKNOWN_LICENSE,
            content_type="pack",
        ))
        if len(hits) >= limit:
            break
    return hits


# --- polyhaven.com -------------------------------------------------------

POLYHAVEN_API = "https://api.polyhaven.com"
_PH_KIND_TO_TYPE = {"hdris": "hdri", "textures": "texture", "models": "model_3d"}


async def search_polyhaven(query: str, limit: int = 8, kind: str = "all", *,
                           client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    """Poly Haven has a single `/assets` endpoint with a `t` filter.

    `kind` is "all" | "hdris" | "textures" | "models". We filter client-side by
    query (case-insensitive substring on slug/name/tags) because the API doesn't
    accept a text query.
    """
    kinds = ["hdris", "textures", "models"] if kind == "all" else [kind]
    hits: list[AssetHit] = []
    for k in kinds:
        body = await _get_json(f"{POLYHAVEN_API}/assets?t={k}", client=client)
        hits.extend(_parse_polyhaven(body, query, k, limit - len(hits)))
        if len(hits) >= limit:
            break
    return hits[:limit]


def _parse_polyhaven(body: dict, query: str, kind: str, limit: int) -> list[AssetHit]:
    q = (query or "").lower().strip()
    out: list[AssetHit] = []
    for slug, entry in (body or {}).items():
        name = entry.get("name") or slug
        tags = [t.lower() for t in entry.get("tags", [])]
        blob = f"{slug} {name.lower()} {' '.join(tags)}"
        if q and q not in blob:
            continue
        out.append(AssetHit(
            pool="polyhaven",
            asset_id=f"polyhaven:{slug}",
            title=name,
            page_url=f"https://polyhaven.com/a/{slug}",
            preview_url=f"https://cdn.polyhaven.com/asset_img/thumbs/{slug}.png?width=256&height=256",
            license=CC0,
            content_type=_PH_KIND_TO_TYPE.get(kind, "unknown"),
            tags=tags,
        ))
        if len(out) >= limit:
            break
    return out


async def resolve_polyhaven(slug: str, resolution: str = "1k", fmt: str = "jpg", *,
                            client: httpx.AsyncClient | None = None) -> dict:
    """Return {download_url, content_type, ext} for a Poly Haven asset.

    Chooses HDRI vs texture vs model by inspecting `/files/<slug>`.
    """
    files = await _get_json(f"{POLYHAVEN_API}/files/{slug}", client=client)
    # HDRI: files["hdri"][res][fmt] = {url}
    if "hdri" in files:
        hdri = files["hdri"]
        res = resolution if resolution in hdri else next(iter(hdri))
        chosen_fmt = fmt if fmt in hdri[res] else next(iter(hdri[res]))
        entry = hdri[res][chosen_fmt]
        return {"download_url": entry["url"], "content_type": "hdri", "ext": chosen_fmt}
    # Texture: files["<map>"][res][fmt] — pick Diffuse/Color preferred
    for map_name in ("Diffuse", "Color", "nor_gl", "AO"):
        if map_name in files:
            maps = files[map_name]
            res = resolution if resolution in maps else next(iter(maps))
            chosen_fmt = fmt if fmt in maps[res] else next(iter(maps[res]))
            entry = maps[res][chosen_fmt]
            return {"download_url": entry["url"], "content_type": "texture", "ext": chosen_fmt}
    # Model: files["blend"][res][fmt] or ["gltf"][res][fmt]
    for mkey in ("gltf", "fbx", "blend"):
        if mkey in files:
            maps = files[mkey]
            res = resolution if resolution in maps else next(iter(maps))
            chosen_fmt = mkey if mkey in maps[res] else next(iter(maps[res]))
            entry = maps[res][chosen_fmt]
            return {"download_url": entry["url"], "content_type": "model_3d",
                    "ext": "zip" if mkey == "gltf" else mkey}
    raise ValueError(f"No recognised file map for polyhaven:{slug}")


# --- ambientcg.com -------------------------------------------------------

AMBIENTCG_API = "https://ambientcg.com/api/v2/full_json"


async def search_ambientcg(query: str, limit: int = 8, *,
                           client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    url = f"{AMBIENTCG_API}?limit={limit}&q={quote_plus(query)}&include=downloadData,imageData,tagData"
    body = await _get_json(url, client=client)
    return _parse_ambientcg(body, limit)


def _parse_ambientcg(body: dict, limit: int = 8) -> list[AssetHit]:
    out: list[AssetHit] = []
    for asset in (body.get("foundAssets") or []):
        slug = asset.get("assetId") or ""
        if not slug:
            continue
        preview = None
        imgs = asset.get("previewImage") or {}
        preview = imgs.get("256-PNG") or imgs.get("128-PNG") or imgs.get("1024-PNG")
        out.append(AssetHit(
            pool="ambientcg",
            asset_id=f"ambientcg:{slug}",
            title=asset.get("displayName") or slug,
            page_url=f"https://ambientcg.com/view?id={slug}",
            preview_url=preview,
            license=CC0,
            content_type={"Material": "texture", "HDRI": "hdri", "Atlas": "texture",
                          "Decal": "texture", "3DModel": "model_3d"}.get(
                              asset.get("dataType"), "texture"),
            tags=asset.get("tags") or [],
        ))
        if len(out) >= limit:
            break
    return out


async def resolve_ambientcg(slug: str, resolution: str = "1K", fmt: str = "JPG", *,
                            client: httpx.AsyncClient | None = None) -> dict:
    url = f"https://ambientcg.com/api/v2/full_json?id={slug}&include=downloadData"
    body = await _get_json(url, client=client)
    assets = body.get("foundAssets") or []
    if not assets:
        raise ValueError(f"ambientcg:{slug} not found")
    asset = assets[0]
    downloads = asset.get("downloadFolders", {}).get("default", {}).get("downloadFiletypeCategories", {})
    # ambientcg groups by Category → Asset → Variations; pick first match
    for category in downloads.values():
        for a in category.get("downloads", []):
            attr = a.get("attribute") or ""
            if resolution in attr and fmt.upper() in attr.upper():
                return {"download_url": a["downloadLink"], "content_type": "texture", "ext": "zip"}
    # fallback: first download
    for category in downloads.values():
        for a in category.get("downloads", []):
            return {"download_url": a["downloadLink"], "content_type": "texture", "ext": "zip"}
    raise ValueError(f"No downloadable variation for ambientcg:{slug}")


# --- quaternius.com ------------------------------------------------------

QUATERNIUS_BASE = "https://quaternius.com"


async def search_quaternius(query: str, limit: int = 8, *,
                            client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    # Quaternius lists every pack on the homepage `/`; legacy `/packs.html` is 404.
    html = await _get(f"{QUATERNIUS_BASE}/", client=client)
    return _parse_quaternius(html, query, limit)


def _parse_quaternius(html: str, query: str, limit: int = 8) -> list[AssetHit]:
    """Quaternius homepage lists packs as anchors to `/packs/<slug>.html` with a thumbnail <img>.

    The title is not in the anchor — derive from slug (camelCaseWords).
    """
    anchor_rx = re.compile(
        r'<a[^>]*href="/?packs/([A-Za-z0-9_]+)\.html"[^>]*>\s*<img[^>]*src="([^"]+)"',
        re.DOTALL,
    )
    q = (query or "").lower().strip()
    out: list[AssetHit] = []
    seen: set[str] = set()
    for m in anchor_rx.finditer(html):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        thumb = m.group(2)
        title = _humanize_slug(slug)
        if q and q not in (slug + " " + title).lower():
            continue
        if thumb.startswith("/"):
            thumb = QUATERNIUS_BASE + thumb
        elif not thumb.startswith("http"):
            thumb = f"{QUATERNIUS_BASE}/{thumb}"
        out.append(AssetHit(
            pool="quaternius",
            asset_id=f"quaternius:{slug}",
            title=title,
            page_url=f"{QUATERNIUS_BASE}/packs/{slug}.html",
            preview_url=thumb,
            license=CC0,
            content_type="model_3d",
        ))
        if len(out) >= limit:
            break
    return out


def _humanize_slug(slug: str) -> str:
    """`ultimateSpaceKit` / `ultimatespacekit` → 'Ultimate Space Kit'. Best-effort."""
    # Split on camelCase boundaries; if none, capitalise the whole thing.
    parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|$)|\d+', slug)
    if not parts:
        return slug
    return " ".join(p.capitalize() for p in parts)


async def resolve_quaternius_download(slug: str, *, client: httpx.AsyncClient | None = None) -> dict | None:
    """Scrape a pack page for its download link.

    Quaternius currently routes downloads through quaternius.itch.io pages
    (and previously Google Drive folders). Neither can be streamed without a
    human session — return the URL plus `requires_manual=True` so the fetch
    tool surfaces it to the agent/human instead of trying to curl it.
    """
    html = await _get(f"{QUATERNIUS_BASE}/packs/{slug}.html", client=client)
    # Preferred: direct .zip (rare).
    zip_m = re.search(r'href="(https?://[^"]+\.zip)"', html)
    if zip_m:
        return {"download_url": zip_m.group(1), "requires_manual": False, "ext": "zip"}
    # Itch.io download page (current).
    itch_m = re.search(r"(https?://quaternius\.itch\.io/[a-z0-9\-]+)", html)
    if itch_m:
        return {"download_url": itch_m.group(1), "requires_manual": True,
                "note": "Quaternius routes downloads via itch.io — human must click through to download"}
    # Legacy: Google Drive folder URL in the download popup.
    drive_m = re.search(r"(https://drive\.google\.com/[^'\"\s<>]+)", html)
    if drive_m:
        return {"download_url": drive_m.group(1), "requires_manual": True,
                "note": "Quaternius hosts on Google Drive — human must click through to download"}
    return None


# --- pixabay.com ---------------------------------------------------------

PIXABAY_API = "https://pixabay.com/api/"
PIXABAY_LICENSE = AssetLicense(
    spdx_id="Pixabay-Content",
    attribution_text=None,  # attribution not required but appreciated
    redistribution_ok=False,
    commercial_ok=True,
)


def pixabay_key() -> str | None:
    return os.environ.get("PIXABAY_API_KEY")


async def search_pixabay(query: str, limit: int = 8, kind: str = "image", *,
                         client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    """kind = image | video | music. Music/SFX use a separate endpoint (beta)."""
    key = pixabay_key()
    if not key:
        return [{"error": "Pixabay disabled: set PIXABAY_API_KEY to enable"}]  # type: ignore[list-item]
    if kind == "video":
        url = f"https://pixabay.com/api/videos/?key={key}&q={quote_plus(query)}&per_page={max(3, limit)}"
    else:
        url = f"{PIXABAY_API}?key={key}&q={quote_plus(query)}&per_page={max(3, limit)}"
    body = await _get_json(url, client=client)
    return _parse_pixabay(body, kind, limit)


def _parse_pixabay(body: dict, kind: str, limit: int = 8) -> list[AssetHit]:
    out: list[AssetHit] = []
    for item in (body.get("hits") or []):
        pid = str(item.get("id"))
        if not pid:
            continue
        if kind == "video":
            preview = (item.get("videos") or {}).get("tiny", {}).get("url")
            download = (item.get("videos") or {}).get("medium", {}).get("url")
            ctype = "video"
        else:
            preview = item.get("previewURL") or item.get("webformatURL")
            download = item.get("largeImageURL") or item.get("webformatURL")
            ctype = "photo"
        author = item.get("user")
        out.append(AssetHit(
            pool="pixabay",
            asset_id=f"pixabay:{pid}",
            title=item.get("tags", "") or pid,
            page_url=item.get("pageURL", f"https://pixabay.com/?id={pid}"),
            preview_url=preview,
            download_url=download,
            license=AssetLicense(
                spdx_id="Pixabay-Content",
                author=author,
                attribution_url=item.get("pageURL"),
                attribution_text=f'Image by {author} from Pixabay' if author else None,
                redistribution_ok=False,
                commercial_ok=True,
            ),
            content_type=ctype,
            tags=(item.get("tags") or "").split(", "),
        ))
        if len(out) >= limit:
            break
    return out


# --- freesound.org (token tier only) -------------------------------------

FREESOUND_API = "https://freesound.org/apiv2"


def freesound_key() -> str | None:
    return os.environ.get("FREESOUND_API_KEY")


async def search_freesound(query: str, limit: int = 8, cc0_only: bool = True, *,
                           client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    key = freesound_key()
    if not key:
        return [{"error": "Freesound disabled: set FREESOUND_API_KEY to enable"}]  # type: ignore[list-item]
    filt = 'license:"Creative Commons 0"' if cc0_only else ""
    url = (f"{FREESOUND_API}/search/text/?query={quote_plus(query)}"
           f"&filter={quote_plus(filt)}&fields=id,name,username,license,previews,tags,url"
           f"&page_size={limit}&token={key}")
    body = await _get_json(url, client=client)
    return _parse_freesound(body, limit)


def _parse_freesound(body: dict, limit: int = 8) -> list[AssetHit]:
    out: list[AssetHit] = []
    for item in (body.get("results") or []):
        sid = str(item.get("id"))
        if not sid:
            continue
        lic_url = item.get("license") or ""
        spdx = "CC0-1.0" if "publicdomain/zero" in lic_url else (
            "CC-BY-4.0" if "by/4.0" in lic_url else (
                "CC-BY-3.0" if "by/3.0" in lic_url else (
                    "CC-BY-NC-4.0" if "by-nc" in lic_url else "Unknown")))
        author = item.get("username")
        previews = item.get("previews") or {}
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        out.append(AssetHit(
            pool="freesound",
            asset_id=f"freesound:{sid}",
            title=item.get("name") or sid,
            page_url=item.get("url") or f"https://freesound.org/s/{sid}/",
            preview_url=preview_url,
            download_url=preview_url,  # preview MP3 is our safe download in token tier
            license=AssetLicense(
                spdx_id=spdx,
                author=author,
                attribution_url=item.get("url"),
                attribution_text=(f'"{item.get("name")}" by {author} ({lic_url})'
                                  if spdx.startswith("CC-BY") else None),
                redistribution_ok=spdx != "Unknown",
                commercial_ok=spdx in ("CC0-1.0", "CC-BY-4.0", "CC-BY-3.0"),
            ),
            content_type="sfx",
            tags=item.get("tags") or [],
        ))
        if len(out) >= limit:
            break
    return out


# --- opengameart.org (CC0-only filter) -----------------------------------

OGA_BASE = "https://opengameart.org"
# License tid 4 = CC0. Enforce hard via URL + post-parse check.
OGA_CC0_TID = "4"


async def search_oga(query: str, limit: int = 8, *,
                     client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    url = (f"{OGA_BASE}/art-search-advanced?keys={quote_plus(query)}"
           f"&field_art_licenses_tid%5B%5D={OGA_CC0_TID}&sort_by=count")
    html = await _get(url, client=client)
    return _parse_oga(html, limit)


def _parse_oga(html: str, limit: int = 8) -> list[AssetHit]:
    """OGA result rows sit inside `.views-row`; each row has one `/content/<slug>` anchor
    and optionally a thumbnail <img>. We scan row-by-row so thumbnails bind to the right row.
    """
    # Split on views-row openings — regex for the row *start* is enough; each row owns
    # everything up to the next row start.
    row_start_rx = re.compile(r'<div[^>]*class="[^"]*views-row[^"]*"[^>]*>')
    starts = [m.start() for m in row_start_rx.finditer(html)]
    if not starts:
        return []
    out: list[AssetHit] = []
    title_rx = re.compile(r'<a[^>]*href="(/content/[^"]+)"[^>]*>([^<]+)</a>')
    img_rx = re.compile(r'<img[^>]*src="([^"]+)"')
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(html)
        inner = html[start:end]
        tm = title_rx.search(inner)
        if not tm:
            continue
        href = tm.group(1)
        title = tm.group(2).strip()
        slug = href.rsplit("/", 1)[-1]
        thumb_m = img_rx.search(inner)
        thumb = thumb_m.group(1) if thumb_m else None
        if thumb and thumb.startswith("/"):
            thumb = OGA_BASE + thumb
        out.append(AssetHit(
            pool="oga",
            asset_id=f"oga:{slug}",
            title=title,
            page_url=f"{OGA_BASE}{href}",
            preview_url=thumb,
            license=CC0,
            content_type="pack",
        ))
        if len(out) >= limit:
            break
    return out


async def resolve_oga(slug: str, *, client: httpx.AsyncClient | None = None) -> dict | None:
    """Fetch an OGA asset page, verify it really is CC0, return first file link."""
    html = await _get(f"{OGA_BASE}/content/{slug}", client=client)
    # License names appear inside <div class="field-name-field-art-licenses">.
    lic_block_m = re.search(
        r'field-name-field-art-licenses.*?</div>\s*</div>', html, re.DOTALL,
    )
    lic_block = lic_block_m.group(0) if lic_block_m else ""
    licenses = set(re.findall(r'>([A-Z0-9 .\-/]+?)</a>', lic_block))
    # If anything other than CC0 is listed, refuse (OR-licensing is ambiguous).
    non_cc0 = {lic.strip() for lic in licenses if lic.strip() and lic.strip() != "CC0"}
    if non_cc0:
        return None
    # First download file link
    m = re.search(r'href="(/sites/default/files/[^"]+)"', html)
    if not m:
        return None
    return {"download_url": OGA_BASE + m.group(1), "content_type": "pack",
            "ext": Path(m.group(1)).suffix.lstrip(".") or "zip"}


# --- downloader ----------------------------------------------------------

async def download(url: str, dest: Path, *, client: httpx.AsyncClient | None = None,
                   max_bytes: int = 100 * 1024 * 1024) -> Path:
    """Stream `url` to `dest`. Returns the written path. Default cap 100 MB
    (Poly Haven 1k HDRIs fit under this; 8k exceeds it deliberately)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    owns = client is None
    if owns:
        client = httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT)
    try:
        written = 0
        async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(f"Download exceeded max_bytes={max_bytes}")
                    f.write(chunk)
        return dest
    finally:
        if owns:
            await client.aclose()


async def _get(url: str, *, client: httpx.AsyncClient | None = None) -> str:
    owns = client is None
    if owns:
        client = httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT)
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.text
    finally:
        if owns:
            await client.aclose()


async def _get_json(url: str, *, client: httpx.AsyncClient | None = None) -> dict:
    owns = client is None
    if owns:
        client = httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT)
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp.raise_for_status()
        try:
            return resp.json()
        except json.JSONDecodeError:
            return json.loads(resp.text)
    finally:
        if owns:
            await client.aclose()


# --- registry ------------------------------------------------------------

SEARCH_REGISTRY = {
    "kenney": search_kenney,
    "itch": search_itch,
    "polyhaven": search_polyhaven,
    "ambientcg": search_ambientcg,
    "quaternius": search_quaternius,
    "pixabay": search_pixabay,
    "freesound": search_freesound,
    "oga": search_oga,
}

ALL_POOLS = tuple(SEARCH_REGISTRY.keys())
