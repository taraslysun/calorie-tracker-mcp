from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from tablycja_client import TablycjaClient


@pytest.mark.asyncio
async def test_add_weight(router):
    captured: dict = {}

    @router.on("POST", "/user/weight/add")
    def _h(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(
            200, json={"code": 0, "message": "Вагу успішно збережено", "data": None}
        )

    async with TablycjaClient(transport=router.transport()) as c:
        await c.weight.add(67.5, date(2026, 5, 4))

    assert captured["body"] == {"weight": "67.5", "date": "04.05.2026"}
