"""Personal recipes ("My Recipes") tools + client tests."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from mcp_server.tools import recipes as recipes_tools
from tablycja_client import TablycjaClient


@pytest.fixture
def meals_list_payload():
    return {
        "requestId": None,
        "count": 2,
        "data": [
            {
                "guid": "a5d41fa73ec54fcbb8e8503a1a70aa2f",
                "title": "Авокадо-тост",
                "energy": "248",
                "energyUnit": "kcal",
                "visibility": "private",
                "portions": 1.0,
                "guidRecipe": None,
            },
            {
                "guid": "ec182505089f43a795a61fbb28312ba6",
                "title": "Сніданок чемпіона",
                "energy": "921",
                "energyUnit": "kcal",
                "visibility": "private",
                "portions": 1.0,
                "guidRecipe": None,
            },
        ],
    }


@pytest.fixture
def meal_add_form_payload():
    """/user/meal/add/form — enveloped, returns dict ready for POST."""
    return {
        "requestId": None,
        "code": 0,
        "message": None,
        "data": {
            "guid": "a5d41fa73ec54fcbb8e8503a1a70aa2f",
            "title": "Авокадо-тост",
            "diaryTimeGuid": "1",
            "diaryTimeOptions": [
                {"id": "1", "title": "Сніданок"},
                {"id": "3", "title": "Обід"},
            ],
            "date": "05.05.2026",
            "foodstuff": [{"guid": "x", "count": 1}],
        },
    }


@pytest.fixture
def recipe_detail_payload():
    return {
        "requestId": None,
        "code": 0,
        "message": None,
        "data": {
            "id": "a5d41fa73ec54fcbb8e8503a1a70aa2f",
            "title": "Авокадо-тост",
            "energy": "248",
            "energyUnit": "kcal",
            "protein": "6.2",
            "carbohydrate": "35.6",
            "fat": "12.4",
            "fiber": "4.5",
            "visibility": "private",
            "content": [
                {"foodstuff": "Авокадо Хасс", "count": 1, "energy": "168"},
            ],
        },
    }


@pytest.mark.asyncio
async def test_list_my_recipes(router, meals_list_payload):
    @router.on("GET", "/user/settings/meal/list")
    def _h(req: httpx.Request) -> httpx.Response:
        assert req.url.params["page"] == "0"
        assert req.url.params["limit"] == "20"
        assert req.url.params["query"] == ""
        return httpx.Response(200, json=meals_list_payload)

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.list_my_recipes(c, query="", page=0, limit=20)

    assert out["count"] == 2
    assert len(out["items"]) == 2
    assert out["items"][0]["id"] == "a5d41fa73ec54fcbb8e8503a1a70aa2f"
    assert out["items"][0]["title"] == "Авокадо-тост"
    assert out["items"][0]["energy"] == "248"
    assert out["items"][1]["title"] == "Сніданок чемпіона"


@pytest.mark.asyncio
async def test_get_my_recipe(router, recipe_detail_payload):
    @router.on("GET", "/recipe/detail/a5d41fa73ec54fcbb8e8503a1a70aa2f")
    def _h(req: httpx.Request) -> httpx.Response:
        assert req.url.params["unit"] == "null"
        return httpx.Response(200, json=recipe_detail_payload)

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.get_my_recipe(
            c, recipe_id="a5d41fa73ec54fcbb8e8503a1a70aa2f"
        )

    assert out["title"] == "Авокадо-тост"
    assert out["protein"] == "6.2"
    assert len(out["content"]) == 1


@pytest.mark.asyncio
async def test_log_recipe(router, meal_add_form_payload):
    captured: dict = {}

    @router.on("GET", "/user/meal/add/form/a5d41fa73ec54fcbb8e8503a1a70aa2f")
    def _form(req):
        return httpx.Response(200, json=meal_add_form_payload)

    @router.on("POST", "/user/recipe/add")
    def _add(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200, json={"code": 0, "data": None, "message": "Успішно записано!"}
        )

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.log_recipe(
            c,
            recipe_id="a5d41fa73ec54fcbb8e8503a1a70aa2f",
            meal="lunch",
            day="2026-05-05",
        )

    assert out["ok"] is True
    assert out["meal_id"] == "3"
    body = captured["body"]
    assert body["guid"] == "a5d41fa73ec54fcbb8e8503a1a70aa2f"
    assert body["diaryTimeGuid"] == "3"  # lunch
    assert body["date"] == "05.05.2026"
    # Foodstuff array preserved from add-form skeleton
    assert body["foodstuff"][0]["guid"] == "x"


@pytest.mark.asyncio
async def test_build_server_includes_recipe_tools():
    from mcp_server import build_server
    mcp = build_server()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"list_my_recipes", "get_my_recipe", "log_recipe"} <= names
