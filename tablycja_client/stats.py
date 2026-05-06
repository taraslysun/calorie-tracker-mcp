"""Statistics / history endpoints.

All accept a date range `from`..`to` (inclusive) in `DD.MM.YYYY` format.
Returned envelope-wrapped dicts are passed through as `data`.
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from .models import fmt_date
from .session import TablycjaSession


class StatsApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def _range(
        self, kind: str, frm: date_cls | str, to: date_cls | str
    ) -> Any:
        return await self._s.get_json(f"/statistic/{kind}/{fmt_date(frm)}/{fmt_date(to)}/get")

    async def weight(self, frm, to) -> Any:
        return await self._range("weight", frm, to)

    async def energy(self, frm, to) -> Any:
        return await self._range("energy", frm, to)

    async def nutrients(self, frm, to) -> Any:
        return await self._range("nutrients", frm, to)

    async def drink(self, frm, to) -> Any:
        return await self._range("drink", frm, to)

    async def optional(self, frm, to) -> Any:
        return await self._range("optional", frm, to)

    async def achievements(self) -> Any:
        return await self._s.get_json("/statistic/analysis/achievements/get")

    async def tips_range(
        self, frm: date_cls | str, to: date_cls | str
    ) -> Any:
        return await self._s.get_json(
            f"/statistic/analysis/tips/{fmt_date(frm)}/{fmt_date(to)}/get"
        )

    async def daily_tips(self, day: date_cls | str) -> Any:
        return await self._s.get_json(f"/user/tips/{fmt_date(day)}/get")

    async def streak(self) -> Any:
        return await self._s.get_json("/user/streak")

    async def daily_summary(self, day: date_cls | str) -> Any:
        return await self._s.get_json(f"/statistic/summary/{fmt_date(day)}/get")
