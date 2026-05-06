"""Profile + active-user endpoints."""
from __future__ import annotations

from .models import ActiveUser, Profile
from .session import TablycjaSession


class ProfileApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def active_user(self) -> ActiveUser:
        data = await self._s.get_json("/user/active-user")
        # /user/active-user returns the user object directly (no envelope wrapping).
        return ActiveUser.model_validate(data)

    async def get(self) -> Profile:
        data = await self._s.get_json("/user/settings/profile/form")
        return Profile.model_validate(data)

    async def streak(self):
        return await self._s.get_json("/user/streak")

    async def premium_data(self):
        return await self._s.get_json("/user/settings/premium/data")

    async def inapp_messages(self):
        return await self._s.get_json("/user/messages/inapp")

    async def save(self, profile: Profile) -> None:
        """Persist profile edits.

        TODO: confirm endpoint shape via recon. Best guess based on REST symmetry:
        POST /user/settings/profile/form with the same shape we receive.
        """
        await self._s.post_json(
            "/user/settings/profile/form",
            json_body=profile.model_dump(mode="json"),
        )
