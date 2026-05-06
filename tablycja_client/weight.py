"""Weight log."""
from __future__ import annotations

from datetime import date as date_cls

from .models import fmt_date
from .session import TablycjaSession


class WeightApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def add(self, weight_kg: float, day: date_cls | str) -> None:
        await self._s.post_json(
            "/user/weight/add",
            json_body={"weight": str(weight_kg), "date": fmt_date(day)},
        )
