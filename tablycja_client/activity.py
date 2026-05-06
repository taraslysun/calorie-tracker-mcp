"""Activity log."""
from __future__ import annotations

from datetime import date as date_cls

from .models import ActivityAddForm, fmt_date
from .session import TablycjaSession


class ActivityApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def get_add_form(self, activity_guid: str) -> ActivityAddForm:
        data = await self._s.get_json(f"/user/activity/add/form/{activity_guid}")
        return ActivityAddForm.model_validate(data)

    async def add(self, form: ActivityAddForm) -> None:
        await self._s.post_json("/user/activity/add", json_body=form.model_dump(mode="json"))

    async def quick_add(
        self,
        activity_guid: str,
        *,
        day: date_cls | str,
        minutes: float,
    ) -> None:
        form = await self.get_add_form(activity_guid)
        form.time = str(minutes)
        form.timeUnit = "min"
        form.date = fmt_date(day)
        await self.add(form)
