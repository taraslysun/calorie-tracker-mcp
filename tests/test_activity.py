from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from tablycja_client import TablycjaClient


@pytest.mark.asyncio
async def test_quick_add_activity(router, activity_form_payload):
    captured: dict = {}

    @router.on("GET", "/user/activity/add/form/7545ca65e4ce93a7")
    def _form(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=activity_form_payload)

    @router.on("POST", "/user/activity/add")
    def _add(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200, json={"code": 0, "message": "Активність успішно збережена", "data": None}
        )

    async with TablycjaClient(transport=router.transport()) as c:
        await c.activity.quick_add(
            "7545ca65e4ce93a7", day=date(2026, 5, 4), minutes=15
        )

    assert captured["body"]["guid"] == "7545ca65e4ce93a7"
    assert captured["body"]["time"] == "15"
    assert captured["body"]["timeUnit"] == "min"
    assert captured["body"]["date"] == "04.05.2026"
