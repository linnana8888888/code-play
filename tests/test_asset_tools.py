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
    with pytest.raises(ValueError):
        await tool_executor._tool_asset_fetch({"asset_id": "not-a-valid-id"})
