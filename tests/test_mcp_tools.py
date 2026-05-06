"""Tool functions tested directly against a TablycjaClient w/ MockTransport."""
from __future__ import annotations

import json

import httpx
import pytest

from mcp_server import build_server
from mcp_server.tools import activity as activity_tools
from mcp_server.tools import catalog as catalog_tools
from mcp_server.tools import diary as diary_tools
from mcp_server.tools import profile as profile_tools
from mcp_server.tools import weight as weight_tools
from tablycja_client import TablycjaClient


@pytest.fixture
async def client(router):
    c = TablycjaClient(transport=router.transport())
    yield c
    await c.aclose()


@pytest.mark.asyncio
async def test_get_profile_tool(router, profile_payload, client):
    router.reply("GET", "/user/settings/profile/form", profile_payload)
    out = await profile_tools.get_profile(client)
    assert out["height_cm"] == 175.0
    assert out["weight_kg"] == 68.0
    assert out["amr"] == 1.375
    assert out["macro_goals"][0]["code"] == "protein"


@pytest.mark.asyncio
async def test_get_active_user_tool(router, active_user_payload, client):
    router.reply("GET", "/user/active-user", active_user_payload)
    out = await profile_tools.get_active_user(client)
    assert out["email"] == "taraslysun2@gmail.com"
    assert out["google_id"] == "100291413510707119917"


@pytest.mark.asyncio
async def test_get_day_iso_date(router, diary_day_payload, client):
    router.reply("GET", "/user/diary/04.05.2026/get", diary_day_payload)
    out = await diary_tools.get_day(client, "2026-05-04")
    assert out["date"] == "2026-05-04"
    assert len(out["meals"]) == 6
    assert out["meals"][0]["title"] == "Сніданок"


@pytest.mark.asyncio
async def test_get_day_dd_mm_yyyy(router, diary_day_payload, client):
    router.reply("GET", "/user/diary/04.05.2026/get", diary_day_payload)
    out = await diary_tools.get_day(client, "04.05.2026")
    assert out["date"] == "2026-05-04"


@pytest.mark.asyncio
async def test_get_summary_tool(router, summary_payload, client):
    router.reply("GET", "/user/diary/summary/04.05.2026/get", summary_payload)
    out = await diary_tools.get_summary(client, "2026-05-04")
    assert out["items"][0]["code"] == "total"


@pytest.mark.asyncio
async def test_log_food_resolves_meal_name(router, food_add_form_payload, client):
    captured: dict = {}

    @router.on("GET", "/user/foodstuff/add/form/73a02350d55a3f8f/04.05.2026/get")
    def _f(req):
        return httpx.Response(200, json=food_add_form_payload)

    @router.on("POST", "/user/foodstuff/add")
    def _add(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(200, json={"code": 0, "data": None, "message": "ok"})

    out = await diary_tools.log_food(
        client, food_id="73a02350d55a3f8f", grams=200, meal="lunch", day="2026-05-04"
    )
    assert out["meal_id"] == "3"
    assert captured["body"]["diaryTimeGuid"] == "3"
    assert captured["body"]["multiplier"] == 200


@pytest.mark.asyncio
async def test_log_food_meal_name_ukrainian(router, food_add_form_payload, client):
    @router.on("GET", "/user/foodstuff/add/form/73a02350d55a3f8f/04.05.2026/get")
    def _f(req):
        return httpx.Response(200, json=food_add_form_payload)

    @router.on("POST", "/user/foodstuff/add")
    def _add(req: httpx.Request):
        return httpx.Response(200, json={"code": 0, "data": None, "message": "ok"})

    out = await diary_tools.log_food(
        client, food_id="73a02350d55a3f8f", grams=100, meal="Вечеря", day="2026-05-04"
    )
    assert out["meal_id"] == "5"


@pytest.mark.asyncio
async def test_log_food_meal_invalid(client):
    with pytest.raises(ValueError):
        await diary_tools.log_food(
            client, food_id="x", grams=10, meal="brunch", day="2026-05-04"
        )


@pytest.mark.asyncio
async def test_log_activity(router, activity_form_payload, client):
    captured: dict = {}

    @router.on("GET", "/user/activity/add/form/7545ca65e4ce93a7")
    def _f(req):
        return httpx.Response(200, json=activity_form_payload)

    @router.on("POST", "/user/activity/add")
    def _add(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(200, json={"code": 0, "data": None, "message": "ok"})

    out = await activity_tools.log_activity(
        client, activity_id="7545ca65e4ce93a7", minutes=30, day="2026-05-04"
    )
    assert out["minutes"] == 30
    assert captured["body"]["time"] == "30"
    assert captured["body"]["timeUnit"] == "min"


@pytest.mark.asyncio
async def test_log_weight(router, client):
    captured: dict = {}

    @router.on("POST", "/user/weight/add")
    def _h(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(200, json={"code": 0, "data": None, "message": "ok"})

    out = await weight_tools.log_weight(client, weight_kg=67.5, day="2026-05-04")
    assert out["ok"] is True
    assert captured["body"] == {"weight": "67.5", "date": "04.05.2026"}


@pytest.mark.asyncio
async def test_search_food(router, autocomplete_payload, client):
    router.reply("GET", "/autocomplete/foodstuff-activity-meal", autocomplete_payload)
    out = await catalog_tools.search_food(client, query="курк", limit=5)
    assert len(out) == 2
    assert out[0]["id"] == "4363328b663259c5"
    assert out[0]["title"] == "Курка тушкована"
    assert out[0]["clazz"] == "foodstuff"


@pytest.mark.asyncio
async def test_build_server_registers_all_tools():
    """Smoke test: server constructs and registers expected tool set."""
    mcp = build_server()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_active_user",
        "get_profile",
        "get_day",
        "get_summary",
        "search_food",
        "search_activity",
        "get_food_detail",
        "log_food",
        "log_activity",
        "log_weight",
        "list_my_recipes",
        "get_my_recipe",
        "log_recipe",
        "get_diary_entry",
        "edit_diary_entry",
        "search_food_with_macros",
    }
