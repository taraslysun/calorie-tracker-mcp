"""Profile + active-user endpoints."""
from __future__ import annotations

from .models import ActiveUser, Profile
from .session import TablycjaSession


class ProfileApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def active_user(self) -> ActiveUser:
        data = await self._s.get_json("/user/active-user")
        return ActiveUser.model_validate(data)

    async def get(self) -> Profile:
        data = await self._s.get_json("/user/settings/profile/form")
        return Profile.model_validate(data)
