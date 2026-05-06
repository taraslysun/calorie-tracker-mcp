from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from tablycja_client import TablycjaClient


@pytest.mark.asyncio
async def test_get_day(router, diary_day_payload):
    router.reply("GET", "/user/diary/04.05.2026/get", diary_day_payload)
    async with TablycjaClient(transport=router.transport()) as c:
        day = await c.diary.get_day(date(2026, 5, 4))
    assert len(day.times) == 6
    assert day.times[0].title == "Сніданок"
    assert day.times[2].id == "3"


@pytest.mark.asyncio
async def test_get_summary_string_date(router, summary_payload):
    router.reply("GET", "/user/diary/summary/04.05.2026/get", summary_payload)
    async with TablycjaClient(transport=router.transport()) as c:
        s = await c.diary.get_summary("04.05.2026")
    assert s.items[0].code == "total"
    assert s.items[1].title == "Питний режим"


@pytest.mark.asyncio
async def test_quick_add_food_picks_gram_unit(router, food_add_form_payload):
    captured: dict = {}

    @router.on("GET", "/user/foodstuff/add/form/73a02350d55a3f8f/04.05.2026/get")
    def _form(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=food_add_form_payload)

    @router.on("POST", "/user/foodstuff/add")
    def _add(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200,
            json={"code": 0, "message": "Їжу було успішно додано в раціон", "data": None},
        )

    async with TablycjaClient(transport=router.transport()) as c:
        await c.diary.quick_add_food(
            "73a02350d55a3f8f",
            day=date(2026, 5, 4),
            meal_id="3",  # lunch
            grams=200,
        )

    assert captured["body"]["guid"] == "73a02350d55a3f8f"
    assert captured["body"]["diaryTimeGuid"] == "3"
    assert captured["body"]["multiplier"] == 200
    assert captured["body"]["unitGuid"] == "0000000000000001"  # 1g unit
    assert captured["body"]["date"] == "04.05.2026"
