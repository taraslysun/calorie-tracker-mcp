"""Catalog search: foodstuff, activity, recipe, drink autocomplete + filter."""
from __future__ import annotations

from typing import Any

from .models import SearchHit
from .session import TablycjaSession


class CatalogApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def autocomplete(self, query: str) -> list[SearchHit]:
        """Mixed search: foodstuff + activity + meal."""
        data = await self._s.get_json(
            "/autocomplete/foodstuff-activity-meal",
            params={"query": query},
        )
        if not isinstance(data, list):
            return []
        return [SearchHit.model_validate(d) for d in data]

    async def autocomplete_activity(self, query: str) -> list[SearchHit]:
        data = await self._s.get_json("/autocomplete/activity", params={"query": query})
        if not isinstance(data, list):
            return []
        return [SearchHit.model_validate(d) for d in data]

    async def autocomplete_drink(self, query: str) -> list[SearchHit]:
        data = await self._s.get_json("/autocomplete/drink", params={"query": query})
        if not isinstance(data, list):
            return []
        return [SearchHit.model_validate(d) for d in data]

    async def filter_foodstuff(
        self,
        *,
        query: str = "",
        page: int = 0,
        limit: int = 50,
        type_: int = 0,
        brand: str = "",
        min_energy: int = 0,
        max_energy: int = 3800,
        slider_type: int = 0,
    ) -> dict[str, Any]:
        """Full paginated food list with macros. Returns raw {count, data:[...]}."""
        params = {
            "page": page,
            "limit": limit,
            "query": query,
            "type": type_,
            "brand": brand,
            "min": min_energy,
            "max": max_energy,
            "sliderType": slider_type,
        }
        # /foodstuff/filter-list returns {requestId, count, data: [...]} — no `code` key,
        # so session._unwrap returns the raw dict.
        return await self._s.get_json("/foodstuff/filter-list", params=params)

    async def food_detail(self, foodstuff_guid: str) -> dict[str, Any]:
        return await self._s.get_json(
            f"/foodstuff/detail/form/{foodstuff_guid}",
            params={"default": "true"},
        )

    async def recipe_detail(self, recipe_guid: str) -> dict[str, Any]:
        return await self._s.get_json(f"/recipe/detail/{recipe_guid}")

    async def autocomplete_foodstuff(self, query: str) -> list[SearchHit]:
        """Foodstuff-only autocomplete (no activities or meals)."""
        data = await self._s.get_json("/autocomplete/foodstuff", params={"query": query})
        if not isinstance(data, list):
            return []
        return [SearchHit.model_validate(d) for d in data]

    async def food_tags(self, scope: str = "all") -> Any:
        """Food filter tags. scope: 'all' or 'top'."""
        if scope not in ("all", "top"):
            raise ValueError(f"scope must be 'all' or 'top', got {scope}")
        return await self._s.get_json(f"/foodstuff/tag/filters/{scope}")

    async def public_recipes(
        self,
        *,
        query: str = "",
        page: int = 0,
        limit: int = 20,
    ) -> Any:
        """Filter the public recipe catalogue."""
        return await self._s.get_json(
            "/recipe/public/filter",
            params={"page": page, "limit": limit, "query": query},
        )

    async def recipe_tags(self) -> Any:
        return await self._s.get_json("/recipe/tag/filters")

    async def recipe_images(self, recipe_guid: str) -> Any:
        return await self._s.get_json(f"/recipe/{recipe_guid}/image/list")
