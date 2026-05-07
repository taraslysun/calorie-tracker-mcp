"""Food diary: read day, read summary, add foodstuff entry."""
from __future__ import annotations

from datetime import date as date_cls

from .models import DaySummary, DiaryDay, FoodAddForm, fmt_date
from .session import TablycjaSession


class DiaryApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def get_day(self, day: date_cls | str) -> DiaryDay:
        data = await self._s.get_json(f"/user/diary/{fmt_date(day)}/get")
        return DiaryDay.model_validate(data)

    async def get_summary(self, day: date_cls | str) -> DaySummary:
        data = await self._s.get_json(f"/user/diary/summary/{fmt_date(day)}/get")
        return DaySummary.model_validate(data)

    async def get_food_add_form(
        self,
        foodstuff_guid: str,
        day: date_cls | str,
    ) -> FoodAddForm:
        data = await self._s.get_json(
            f"/user/foodstuff/add/form/{foodstuff_guid}/{fmt_date(day)}/get"
        )
        return FoodAddForm.model_validate(data)

    async def add_food(self, form: FoodAddForm) -> str | None:
        """POST a fully-prepared add-food payload. Returns the upstream success message."""
        body = form.model_dump(mode="json")
        # Upstream URL has trailing `&=` on this endpoint (observed in capture);
        # not strictly required — httpx will normalize. Keep `format=json` only.
        await self._s.post_json("/user/foodstuff/add", json_body=body)
        return "ok"

    async def quick_add_food(
        self,
        foodstuff_guid: str,
        *,
        day: date_cls | str,
        meal_id: str,
        grams: float,
    ) -> None:
        """Convenience: fetch add-form, override meal+grams, POST."""
        form = await self.get_food_add_form(foodstuff_guid, day)
        form.diaryTimeGuid = meal_id
        form.multiplier = grams
        # Force the "1 г" unit so multiplier is grams directly.
        gram_unit = next(
            (u for u in form.unitOptions if float(u.multiplier) == 1),
            None,
        )
        if gram_unit:
            form.unitGuid = gram_unit.id
        await self.add_food(form)
