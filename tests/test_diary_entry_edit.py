"""Edit-an-already-logged diary entry: remove/scale ingredients."""
from __future__ import annotations

import json

import httpx
import pytest

from mcp_server.tools import recipes as recipes_tools
from tablycja_client import TablycjaClient


@pytest.fixture
def diary_edit_form_payload():
    return {
        "requestId": None,
        "code": 0,
        "message": None,
        "data": {
            "guid": "a5d41fa73ec54fcbb8e8503a1a70aa2f",  # the recipe
            "title": "Авокадо-тост",
            "diaryTimeGuid": "1",
            "diaryTimeOptions": [
                {"id": "1", "title": "Сніданок"},
                {"id": "3", "title": "Обід"},
            ],
            "date": "05.05.2026",
            "foodstuff": [
                {
                    "selected": True,
                    "guid": "dea3fc40c7cd4a6a80f31f537ec88766",
                    "foodstuffGuid": "dea3fc40c7cd4a6a80f31f537ec88766",
                    "title": "Авокадо Хасс",
                    "count": 1.0,
                    "countOriginal": 1.0,
                    "selectedUnitGuid": "u1",
                    "weight": 75.0,
                },
                {
                    "selected": True,
                    "guid": "b4aa2ba5a8034e8a9c3fe5fda02c8a4c",
                    "foodstuffGuid": "b4aa2ba5a8034e8a9c3fe5fda02c8a4c",
                    "title": "Хліб житній",
                    "count": 70.0,
                    "countOriginal": 70.0,
                    "selectedUnitGuid": "u1",
                    "weight": 70.0,
                },
                {
                    "selected": True,
                    "guid": "ban-guid-xyz",
                    "foodstuffGuid": "ban-guid-xyz",
                    "title": "Банан",
                    "count": 1.0,
                    "countOriginal": 1.0,
                    "selectedUnitGuid": "u1",
                    "weight": 120.0,
                },
            ],
            "guidDiary": "027b47ac715a412c9a06860a8a21859b",
        },
    }


@pytest.mark.asyncio
async def test_edit_diary_entry_excludes_ingredient_by_title(
    router, diary_edit_form_payload
):
    captured: dict = {}

    @router.on(
        "GET",
        "/user/diary/meal/edit/form/027b47ac715a412c9a06860a8a21859b",
    )
    def _form(req):
        return httpx.Response(200, json=diary_edit_form_payload)

    @router.on("POST", "/user/meal/edit")
    def _save(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200, json={"code": 0, "data": None, "message": "Успішно записано!"}
        )

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.edit_diary_entry(
            c,
            entry_id="027b47ac715a412c9a06860a8a21859b",
            exclude_ingredients=["Банан"],
        )

    assert out["ingredients_total"] == 3
    assert out["ingredients_kept"] == 2
    assert "Банан" in out["excluded"]
    titles = [it["title"] for it in captured["body"]["foodstuff"]]
    assert "Банан" not in titles
    assert "Авокадо Хасс" in titles
    assert "Хліб житній" in titles


@pytest.mark.asyncio
async def test_edit_diary_entry_scales_ingredient(
    router, diary_edit_form_payload
):
    captured: dict = {}

    @router.on(
        "GET",
        "/user/diary/meal/edit/form/027b47ac715a412c9a06860a8a21859b",
    )
    def _form(req):
        return httpx.Response(200, json=diary_edit_form_payload)

    @router.on("POST", "/user/meal/edit")
    def _save(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200, json={"code": 0, "data": None, "message": "ok"}
        )

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.edit_diary_entry(
            c,
            entry_id="027b47ac715a412c9a06860a8a21859b",
            scale_ingredients={"Авокадо Хасс": 0.5},
        )

    assert any(s["title"] == "Авокадо Хасс" and s["factor"] == 0.5
               for s in out["scaled"])
    av = next(it for it in captured["body"]["foodstuff"]
              if it["title"] == "Авокадо Хасс")
    assert av["count"] == 0.5  # 1.0 * 0.5


@pytest.mark.asyncio
async def test_edit_diary_entry_changes_meal(
    router, diary_edit_form_payload
):
    captured: dict = {}

    @router.on(
        "GET",
        "/user/diary/meal/edit/form/027b47ac715a412c9a06860a8a21859b",
    )
    def _form(req):
        return httpx.Response(200, json=diary_edit_form_payload)

    @router.on("POST", "/user/meal/edit")
    def _save(req: httpx.Request):
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(200, json={"code": 0, "data": None})

    async with TablycjaClient(transport=router.transport()) as c:
        out = await recipes_tools.edit_diary_entry(
            c,
            entry_id="027b47ac715a412c9a06860a8a21859b",
            meal="lunch",
        )

    assert captured["body"]["diaryTimeGuid"] == "3"
    assert out["meal_id"] == "3"
