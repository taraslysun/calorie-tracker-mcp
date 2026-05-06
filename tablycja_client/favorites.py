"""Favorites + common items for foodstuff, activity, drink."""
from __future__ import annotations

from typing import Any

from .session import TablycjaSession


class FavoritesApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def favorite_foodstuff(self) -> Any:
        return await self._s.get_json("/user/settings/favorite/foodstuff")

    async def favorite_activity(self) -> Any:
        return await self._s.get_json("/user/settings/favorite/activity")

    async def favorite_drink(self) -> Any:
        return await self._s.get_json("/user/settings/favorite/drink")

    async def common_activity(self) -> Any:
        return await self._s.get_json("/user/settings/common/activity")

    async def common_drink(self) -> Any:
        return await self._s.get_json("/user/settings/common/drink")

    async def regular_activity(self) -> Any:
        return await self._s.get_json("/user/settings/activity/regular")
