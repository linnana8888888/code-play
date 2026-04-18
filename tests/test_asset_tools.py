"""Asset-pool tool tests — parsers + tool_executor handlers.

Scraping is exercised against fixture HTML. The real http calls are replaced with
a tiny httpx.MockTransport so the test suite never hits the network.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from src.runtime import asset_sources
from src.runtime.tool_executor import tool_executor


KENNEY_LISTING_HTML = """
<html><body>
<div class='row margin-top'>
  <div class='col-md-3'>
    <div class='asset'>
      <a href='https://kenney.nl/assets/1-bit-pack'>
        <div class='cover' style='background-image:url("https://kenney.nl/media/pages/assets/1-bit-pack/abc/sample-400x.png")'></div>
      </a>
      <h2><a href='https://kenney.nl/assets/1-bit-pack'>1-Bit Pack</a></h2>
      <span class='bold text-muted'><a href='https://kenney.nl/assets/category:2D'>2D</a></span>
    </div>
  </div>
  <div class='col-md-3'>
    <div class='asset'>
      <a href='https://kenney.nl/assets/platformer-art-deluxe'>
        <div class='cover' style='background-image:url("https://kenney.nl/media/pages/assets/platformer-art-deluxe/def/sample-400x.png")'></div>
      </a>
      <h2><a href='https://kenney.nl/assets/platformer-art-deluxe'>Platformer Art Deluxe</a></h2>
    </div>
  </div>
  <a href='/assets/category:2D'>Category link (should be skipped)</a>
</div>
</body></html>
"""

KENNEY_DETAIL_HTML = """
<html>
  <head>
    <meta property="og:image" content="https://kenney.nl/media/pages/assets/1-bit-pack/og.png" />
  </head>
  <body>
    <a href="/media/pages/assets/1-bit-pack/abc123/1-bit-pack.zip">Download</a>
  </body>
</html>
"""

ITCH_LISTING_HTML = """
<html><body>
<div class="browse_game_grid">
  <div data-game_id="100001" class="game_cell has_cover lazy_images" dir="auto">
    <div class="game_thumb">
      <a class="thumb_link game_link" href="https://alice.itch.io/pixel-forest">
        <img class="lazy_loaded" data-lazy_src="https://img.itch.zone/pf.png" />
      </a>
    </div>
    <div class="game_cell_data">
      <div class="game_title">
        <a class="title game_link" href="https://alice.itch.io/pixel-forest">Pixel Forest</a>
      </div>
    </div>
  </div>
  <div data-game_id="100002" class="game_cell has_cover lazy_images" dir="auto">
    <div class="game_thumb">
      <a class="thumb_link game_link" href="https://bob.itch.io/low-poly-buildings">
        <img class="lazy_loaded" data-lazy_src="https://img.itch.zone/bp.png" />
      </a>
    </div>
    <div class="game_cell_data">
      <div class="game_title">
        <a class="title game_link" href="https://bob.itch.io/low-poly-buildings">Low Poly Buildings</a>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def test_parse_kenney_extracts_packs():
    hits = asset_sources._parse_kenney(KENNEY_LISTING_HTML)
    slugs = [h.asset_id for h in hits]
    assert slugs == ["kenney:1-bit-pack", "kenney:platformer-art-deluxe"]
    assert hits[0].title == "1-Bit Pack"
    assert hits[0].page_url == "https://kenney.nl/assets/1-bit-pack"
    assert hits[0].preview_url.endswith("sample-400x.png")
    assert hits[0].pool == "kenney"


def test_parse_kenney_honours_limit():
    hits = asset_sources._parse_kenney(KENNEY_LISTING_HTML, limit=1)
    assert len(hits) == 1


def test_parse_itch_extracts_projects():
    hits = asset_sources._parse_itch(ITCH_LISTING_HTML)
    assert [h.asset_id for h in hits] == ["itch:100001", "itch:100002"]
    assert hits[0].title == "Pixel Forest"
    assert hits[0].page_url == "https://alice.itch.io/pixel-forest"
    assert hits[0].preview_url == "https://img.itch.zone/pf.png"
    assert hits[0].pool == "itch"


def _build_mock_client(routes: dict[str, tuple[int, str]]) -> httpx.AsyncClient:
    """Tiny AsyncClient whose responses come from `routes` keyed by URL prefix."""
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, (status, body) in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(status_code=status, text=body)
        return httpx.Response(status_code=404, text="not mocked")

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, follow_redirects=True)


@pytest.mark.asyncio
async def test_search_kenney_and_itch_via_mock_transport():
    async with _build_mock_client({
        "https://kenney.nl/assets/series": (200, KENNEY_LISTING_HTML),
        "https://itch.io/game-assets": (200, ITCH_LISTING_HTML),
    }) as client:
        k = await asset_sources.search_kenney("pixel", client=client)
        i = await asset_sources.search_itch("pixel", client=client)
    assert [h.asset_id for h in k] == ["kenney:1-bit-pack", "kenney:platformer-art-deluxe"]
    assert [h.asset_id for h in i] == ["itch:100001", "itch:100002"]


@pytest.mark.asyncio
async def test_resolve_kenney_zip():
    async with _build_mock_client({
        "https://kenney.nl/assets/1-bit-pack": (200, KENNEY_DETAIL_HTML),
    }) as client:
        url = await asset_sources.resolve_kenney_zip("1-bit-pack", client=client)
    assert url == "https://kenney.nl/media/pages/assets/1-bit-pack/abc123/1-bit-pack.zip"


@pytest.mark.asyncio
async def test_download_writes_file(tmp_path: Path):
    payload = b"fake-preview-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dest = tmp_path / "out" / "preview.png"
        await asset_sources.download("https://example.com/any.png", dest, client=client)
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_tool_executor_registers_asset_tools():
    schemas = {s["name"] for s in tool_executor.get_tool_schemas()}
    assert "asset_search" in schemas
    assert "asset_fetch" in schemas


@pytest.mark.asyncio
async def test_asset_search_handler_json_shape(monkeypatch):
    """The handler should merge both pools and emit JSON."""
    async def fake_kenney(query, limit=6, *, client=None):
        return [asset_sources.AssetHit(
            pool="kenney", asset_id="kenney:x", title="X",
            page_url="https://kenney.nl/assets/x", preview_url="https://kenney.nl/p.png",
        )]

    async def fake_itch(query, limit=6, *, client=None):
        return [asset_sources.AssetHit(
            pool="itch", asset_id="itch:1", title="Y",
            page_url="https://y.itch.io/z", preview_url="https://img.itch.zone/y.png",
        )]

    monkeypatch.setattr(asset_sources, "search_kenney", fake_kenney)
    monkeypatch.setattr(asset_sources, "search_itch", fake_itch)

    result = await tool_executor._tool_asset_search({"query": "pixel forest"})
    import json
    data = json.loads(result)
    assert data["query"] == "pixel forest"
    assert {h["asset_id"] for h in data["hits"]} == {"kenney:x", "itch:1"}


def test_asset_search_governance_tier():
    """Both tools must be builtin — agents use them without an approval prompt."""
    from src.models.governance import ToolPermission
    tool_executor.load_governance()
    assert tool_executor._governance.get("asset_search") == ToolPermission.BUILTIN
    assert tool_executor._governance.get("asset_fetch") == ToolPermission.BUILTIN


@pytest.mark.asyncio
async def test_asset_fetch_rejects_malformed_id():
    """Handler now returns a structured error instead of raising — agents can recover."""
    import json
    result = await tool_executor._tool_asset_fetch({"asset_id": "not-a-valid-id"})
    data = json.loads(result)
    assert data["status"] == "error"
    assert "<pool>:<slug>" in data["error"]


# --- Phase 1 parsers ------------------------------------------------------

POLYHAVEN_JSON = {
    "rocky_terrain": {"name": "Rocky Terrain", "tags": ["rock", "mountain", "outdoor"]},
    "sunny_sky": {"name": "Sunny Sky", "tags": ["sky", "outdoor", "daylight"]},
    "pine_forest": {"name": "Pine Forest", "tags": ["forest", "outdoor", "tree"]},
}


def test_parse_polyhaven_filters_by_query():
    hits = asset_sources._parse_polyhaven(POLYHAVEN_JSON, "forest", "hdris", 10)
    assert [h.asset_id for h in hits] == ["polyhaven:pine_forest"]
    assert hits[0].license.spdx_id == "CC0-1.0"
    assert hits[0].content_type == "hdri"
    assert "tree" in hits[0].tags


def test_parse_polyhaven_returns_all_when_empty_query():
    hits = asset_sources._parse_polyhaven(POLYHAVEN_JSON, "", "textures", 10)
    assert len(hits) == 3
    assert all(h.content_type == "texture" for h in hits)


AMBIENTCG_JSON = {
    "foundAssets": [
        {
            "assetId": "Wood027",
            "displayName": "Wood 027",
            "dataType": "Material",
            "tags": ["wood", "plank", "brown"],
            "previewImage": {"256-PNG": "https://ambientcg.com/prev/wood027.png"},
        },
        {
            "assetId": "Metal052",
            "displayName": "Metal 052",
            "dataType": "Material",
            "tags": ["metal", "rust"],
            "previewImage": {"256-PNG": "https://ambientcg.com/prev/metal052.png"},
        },
    ]
}


def test_parse_ambientcg_emits_cc0_hits():
    hits = asset_sources._parse_ambientcg(AMBIENTCG_JSON, limit=10)
    ids = [h.asset_id for h in hits]
    assert ids == ["ambientcg:Wood027", "ambientcg:Metal052"]
    assert hits[0].license.spdx_id == "CC0-1.0"
    assert hits[0].content_type == "texture"
    assert hits[0].preview_url.endswith("wood027.png")


QUATERNIUS_HTML = """
<html><body>
<div class="pack-grid">
  <a href="/packs/LowPolyNature.html">
    <img src="img/nature.jpg" />
  </a>
  <a href="packs/SpaceKit.html">
    <img src="/img/space.jpg" />
  </a>
  <a href="/packs/UniversalAnimationLibrary.html">
    <img src="https://cdn.quaternius.com/anims.jpg" />
  </a>
</div>
</body></html>
"""


def test_parse_quaternius_extracts_packs():
    hits = asset_sources._parse_quaternius(QUATERNIUS_HTML, "", limit=10)
    ids = [h.asset_id for h in hits]
    assert ids == ["quaternius:LowPolyNature", "quaternius:SpaceKit", "quaternius:UniversalAnimationLibrary"]
    assert hits[0].license.spdx_id == "CC0-1.0"
    assert hits[0].preview_url == "https://quaternius.com/img/nature.jpg"
    assert hits[1].preview_url == "https://quaternius.com/img/space.jpg"
    assert hits[2].preview_url == "https://cdn.quaternius.com/anims.jpg"
    assert hits[0].title == "Low Poly Nature"
    assert hits[2].title == "Universal Animation Library"


def test_parse_quaternius_filters_by_query():
    hits = asset_sources._parse_quaternius(QUATERNIUS_HTML, "animation", limit=10)
    assert [h.asset_id for h in hits] == ["quaternius:UniversalAnimationLibrary"]


# --- Phase 2 parsers (work with or without API key) -----------------------

PIXABAY_JSON = {
    "hits": [
        {
            "id": 12345,
            "tags": "sunset, mountain, nature",
            "user": "Alice",
            "pageURL": "https://pixabay.com/photos/sunset-12345",
            "previewURL": "https://cdn.pixabay.com/p/12345_150.jpg",
            "largeImageURL": "https://cdn.pixabay.com/p/12345_1280.jpg",
            "webformatURL": "https://cdn.pixabay.com/p/12345_640.jpg",
        }
    ]
}


def test_parse_pixabay_encodes_attribution():
    hits = asset_sources._parse_pixabay(PIXABAY_JSON, "image", limit=10)
    assert hits[0].asset_id == "pixabay:12345"
    assert hits[0].license.spdx_id == "Pixabay-Content"
    assert hits[0].license.author == "Alice"
    assert "Alice" in hits[0].license.attribution_text
    assert hits[0].license.redistribution_ok is False


FREESOUND_JSON = {
    "results": [
        {
            "id": 77777,
            "name": "Explosion Big",
            "username": "bob",
            "license": "https://creativecommons.org/publicdomain/zero/1.0/",
            "url": "https://freesound.org/s/77777/",
            "previews": {"preview-hq-mp3": "https://cdn.freesound.org/77777.mp3"},
            "tags": ["explosion", "boom"],
        },
        {
            "id": 88888,
            "name": "Attribution Clip",
            "username": "carol",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "url": "https://freesound.org/s/88888/",
            "previews": {"preview-hq-mp3": "https://cdn.freesound.org/88888.mp3"},
            "tags": ["voice"],
        },
    ]
}


def test_parse_freesound_distinguishes_cc0_and_ccby():
    hits = asset_sources._parse_freesound(FREESOUND_JSON, limit=10)
    assert hits[0].license.spdx_id == "CC0-1.0"
    assert hits[0].license.attribution_text is None
    assert hits[1].license.spdx_id == "CC-BY-4.0"
    assert "carol" in hits[1].license.attribution_text


def test_pixabay_freesound_disabled_without_key(monkeypatch):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    # Run the coroutines inline
    import asyncio
    p = asyncio.run(asset_sources.search_pixabay("cat", 3))
    f = asyncio.run(asset_sources.search_freesound("boom", 3))
    assert isinstance(p[0], dict) and "error" in p[0]
    assert isinstance(f[0], dict) and "error" in f[0]


# --- Phase 3: OpenGameArt -------------------------------------------------

OGA_HTML = """
<html><body>
<div class="views-row">
  <a href="/content/free-pixel-tileset">Free Pixel Tileset</a>
  <img src="/files/preview/tileset.png" />
</div>
<div class="views-row">
  <a href="/content/chiptune-loop">Chiptune Loop</a>
  <img src="/files/preview/chiptune.png" />
</div>
</div>
</body></html>
"""


def test_parse_oga_returns_cc0_hits():
    hits = asset_sources._parse_oga(OGA_HTML, limit=10)
    ids = [h.asset_id for h in hits]
    assert ids == ["oga:free-pixel-tileset", "oga:chiptune-loop"]
    assert all(h.license.spdx_id == "CC0-1.0" for h in hits)


# --- Policy hook: CC-BY content downloads require accept_attribution ------

@pytest.mark.asyncio
async def test_fetch_blocks_non_cc0_without_attribution(monkeypatch, tmp_path):
    """Pixabay hits are Pixabay-License (non-CC0). kind=content should be blocked."""
    import json as _json

    async def fake_pixabay_search(query, limit=8, *, client=None, **kw):
        return [asset_sources.AssetHit(
            pool="pixabay",
            asset_id="pixabay:555",
            title="cat",
            page_url="https://pixabay.com/photos/cat-555",
            preview_url="https://cdn.pixabay.com/p/555_150.jpg",
            download_url="https://cdn.pixabay.com/p/555_1280.jpg",
            license=asset_sources.AssetLicense(
                spdx_id="Pixabay-Content",
                author="Alice",
                attribution_text="Image by Alice from Pixabay",
                redistribution_ok=False,
                commercial_ok=True,
            ),
            content_type="photo",
        )]

    monkeypatch.setattr(asset_sources, "search_pixabay", fake_pixabay_search)

    result = await tool_executor._tool_asset_fetch({
        "asset_id": "pixabay:555",
        "kind": "content",
        "accept_attribution": False,
    })
    data = _json.loads(result)
    assert data["status"] == "needs_approval"
    assert "Pixabay-Content" in data["reason"]


@pytest.mark.asyncio
async def test_fetch_allows_cc0_content_without_attribution(monkeypatch, tmp_path):
    """Kenney is CC0 — kind=zip should fetch without accept_attribution."""
    import json as _json
    from pathlib import Path as _Path

    # Patch resolver to return a controlled URL, and download() to write a file.
    async def fake_zip(slug, *, client=None):
        return "https://example.invalid/kenney.zip"

    written: dict = {}

    async def fake_download(url, dest, *, client=None, max_bytes=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"ZIP-BYTES")
        written["url"] = url
        written["dest"] = str(dest)
        return dest

    monkeypatch.setattr(asset_sources, "resolve_kenney_zip", fake_zip)
    monkeypatch.setattr(asset_sources, "download", fake_download)

    from src.runtime.tool_executor import ToolExecutor
    monkeypatch.setattr(
        ToolExecutor, "_safe_path",
        lambda self, p, project_id, agent_instance_id: tmp_path / p,
    )

    result = await tool_executor._tool_asset_fetch({
        "asset_id": "kenney:test-pack",
        "kind": "content",
    })
    data = _json.loads(result)
    assert data["status"] == "ok", data
    assert data["license"]["spdx_id"] == "CC0-1.0"
    assert data["credits_appended"] is None  # CC0 → no CREDITS entry


@pytest.mark.asyncio
async def test_fetch_appends_credits_when_accepted(monkeypatch, tmp_path):
    """With accept_attribution=true on a CC-BY asset, CREDITS.md gets a new line."""
    import json as _json

    async def fake_search(query, limit=8, *, client=None, **kw):
        return [asset_sources.AssetHit(
            pool="freesound",
            asset_id="freesound:999",
            title="Boom",
            page_url="https://freesound.org/s/999/",
            preview_url="https://cdn.freesound.org/999.mp3",
            download_url="https://cdn.freesound.org/999.mp3",
            license=asset_sources.AssetLicense(
                spdx_id="CC-BY-4.0",
                author="dave",
                attribution_url="https://freesound.org/s/999/",
                attribution_text='"Boom" by dave (CC-BY-4.0)',
                redistribution_ok=True,
                commercial_ok=True,
            ),
            content_type="sfx",
        )]

    async def fake_download(url, dest, *, client=None, max_bytes=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MP3-BYTES")
        return dest

    monkeypatch.setattr(asset_sources, "search_freesound", fake_search)
    monkeypatch.setattr(asset_sources, "download", fake_download)

    from src.runtime.tool_executor import ToolExecutor
    monkeypatch.setattr(
        ToolExecutor, "_safe_path",
        lambda self, p, project_id, agent_instance_id: tmp_path / p,
    )

    result = await tool_executor._tool_asset_fetch({
        "asset_id": "freesound:999",
        "kind": "content",
        "accept_attribution": True,
    })
    data = _json.loads(result)
    assert data["status"] == "ok", data
    assert data["license"]["spdx_id"] == "CC-BY-4.0"
    assert data["credits_appended"] is not None
    credits = (tmp_path / "CREDITS.md").read_text(encoding="utf-8")
    assert "freesound:999" in credits
    assert "dave" in credits
