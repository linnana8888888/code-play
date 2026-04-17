"""Asset library integrations.

Two shared resource pools for agents:
  - kenney.nl  — CC0 game art packs (pixel, 2D, 3D kits)
  - itch.io    — game-assets marketplace (mix of free and paid)

The module exposes:
  * `search_kenney` / `search_itch` — async search against the public pages
  * `_parse_kenney` / `_parse_itch` — pure HTML parsers (easy to unit-test)
  * `resolve_kenney_zip` — discover the zip download URL on a pack page
  * `download` — stream a URL to a project-relative path

All scraping targets public pages and uses a friendly User-Agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import quote_plus

import httpx

USER_AGENT = "code-play-agent/1.0 (asset-search)"
TIMEOUT = 20.0


@dataclass
class AssetHit:
    pool: str              # "kenney" | "itch"
    asset_id: str          # "kenney:<slug>" or "itch:<project_id>"
    title: str
    page_url: str
    preview_url: str | None
    download_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- kenney.nl ------------------------------------------------------------

KENNEY_BASE = "https://kenney.nl"


async def search_kenney(query: str, limit: int = 8, *, client: httpx.AsyncClient | None = None) -> list[AssetHit]:
    url = f"{KENNEY_BASE}/assets/series:?search={quote_plus(query)}"
    html = await _get(url, client=client)
    return _parse_kenney(html, limit)


def _parse_kenney(html: str, limit: int = 8) -> list[AssetHit]:
    """Scrape kenney asset cards. Live HTML looks like:

        <div class='asset'>
          <a href='https://kenney.nl/assets/<slug>'>
            <div class='cover' style='background-image:url("<preview>")'></div>
          </a>
          <h2><a href='.../assets/<slug>'>Title</a></h2>
          ...
        </div>

    The regex is quote-agnostic because the source uses single quotes.
    """
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
        ))
        if len(hits) >= limit:
            break
    return hits


async def resolve_kenney_zip(slug: str, *, client: httpx.AsyncClient | None = None) -> str | None:
    html = await _get(f"{KENNEY_BASE}/assets/{slug}", client=client)
    # Kenney uses single quotes on pack pages, and the zip URL may be absolute.
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
    """Scrape itch.io game-asset cards. Live HTML looks like:

        <div data-game_id="123" class="game_cell has_cover ..." ...>
          <div class="game_thumb" ...>
            <a class="thumb_link game_link" ... href="https://user.itch.io/foo" ...>
              <img class="lazy_loaded" data-lazy_src="https://img.itch.zone/..." ... />
            </a>
          </div>
          <div class="game_cell_data">
            <div class="game_title">
              <a class="title game_link" href="https://user.itch.io/foo" ...>Title</a>
            </div>
            ...
          </div>
        </div>

    NOTE: `data-game_id` appears BEFORE `class=...` in the real markup.
    """
    # Scan cell starts (data-game_id may appear before class=), use next start
    # as terminator — balanced-div regex is hopeless.
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
        ))
        if len(hits) >= limit:
            break
    return hits


# --- downloader ----------------------------------------------------------

async def download(url: str, dest: Path, *, client: httpx.AsyncClient | None = None, max_bytes: int = 50 * 1024 * 1024) -> Path:
    """Stream `url` to `dest`. Returns the written path."""
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
