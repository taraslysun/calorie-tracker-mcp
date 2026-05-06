from __future__ import annotations

import httpx
import pytest

from tablycja_client import TablycjaClient


@pytest.mark.asyncio
async def test_autocomplete(router, autocomplete_payload):
    @router.on("GET", "/autocomplete/foodstuff-activity-meal")
    def _h(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("query") == "курк"
        assert req.url.params.get("format") == "json"
        return httpx.Response(200, json=autocomplete_payload)

    async with TablycjaClient(transport=router.transport()) as c:
        hits = await c.catalog.autocomplete("курк")

    assert len(hits) == 2
    assert hits[0].id == "4363328b663259c5"
    assert hits[0].title == "Курка тушкована"
    assert hits[0].clazz == "foodstuff"


@pytest.mark.asyncio
async def test_search_food_with_macros(router):
    from mcp_server.tools import catalog as catalog_tools
    raw = {
        "requestId": None,
        "count": 73,
        "data": [
            {"id": "abc", "title": "Яблуко червоне", "url": "yabluko-chervone",
             "energy": "73.2", "energyUnit": "kcal",
             "protein": "0.4", "carbohydrate": "17", "fat": "0", "fiber": "2",
             "sugar": "12", "saturatedFattyAcid": "0", "salt": "0",
             "calcium": "5", "sodium": "0", "cholesterol": "0"},
        ],
    }
    @router.on("GET", "/foodstuff/filter-list")
    def _h(req: httpx.Request):
        assert req.url.params.get("query") == "яблуко"
        assert req.url.params.get("limit") == "5"
        return httpx.Response(200, json=raw)
    async with TablycjaClient(transport=router.transport()) as c:
        out = await catalog_tools.search_food_with_macros(c, query="яблуко", limit=5)
    assert out["count"] == 73
    assert out["items"][0]["title"] == "Яблуко червоне"
    assert out["items"][0]["protein"] == "0.4"
    assert out["items"][0]["carbohydrate"] == "17"
    assert out["items"][0]["fiber"] == "2"


@pytest.mark.asyncio
async def test_filter_foodstuff_returns_raw(router):
    raw = {
        "requestId": None,
        "count": 204581,
        "data": [
            {"id": "73a02350d55a3f8f", "title": "Вода питна", "energy": "0",
             "protein": "0", "carbohydrate": "0", "fat": "0", "energyUnit": "kcal"},
        ],
    }
    router.reply("GET", "/foodstuff/filter-list", raw)
    async with TablycjaClient(transport=router.transport()) as c:
        out = await c.catalog.filter_foodstuff(query="вода", limit=10)
    assert out["count"] == 204581
    assert out["data"][0]["title"] == "Вода питна"
