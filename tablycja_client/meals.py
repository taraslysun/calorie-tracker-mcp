"""Personal recipes / saved meals.

Upstream calls these "meals" (`/user/settings/meal/...`) but they are what
the UI exposes as "Мої рецепти" (My Recipes). They are user-private
compositions of foodstuffs with their own GUID, totals, and portions.

Endpoints wrapped:
- GET /user/settings/meal/list                       paginated list
- GET /recipe/detail/{guid}                          full detail (incl. content[])
- GET /user/meal/add/form/{guid}                     pre-filled add-to-diary form
- POST /user/recipe/add                              log meal to diary
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from .models import fmt_date
from .session import TablycjaSession


class MealsApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def list(
        self, *, query: str = "", page: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """Paginated list of user's saved meals/recipes.

        Returns the raw {requestId, count, data:[{guid,title,energy,energyUnit,
        visibility,portions,...}]} dict — no envelope `code` key on this one.
        """
        return await self._s.get_json(
            "/user/settings/meal/list",
            params={"page": page, "limit": limit, "query": query},
        )

    async def detail(self, recipe_guid: str) -> dict[str, Any]:
        """Full recipe detail incl. macros and `content[]` ingredients."""
        return await self._s.get_json(
            f"/recipe/detail/{recipe_guid}",
            params={"unit": "null", "multiplier": "null"},
        )

    async def get_add_form(
        self, recipe_guid: str
    ) -> dict[str, Any]:
        """Pre-filled payload skeleton for /user/recipe/add."""
        return await self._s.get_json(f"/user/meal/add/form/{recipe_guid}")

    async def add_to_diary(self, payload: dict[str, Any]) -> None:
        """POST a fully-prepared recipe-add payload."""
        await self._s.post_json("/user/recipe/add", json_body=payload)

    async def get_edit_form(self, recipe_guid: str) -> Any:
        """Fetch the editable recipe definition (items + units + tags + portions).
        Pass `0` as guid for a blank create form."""
        return await self._s.get_json(
            f"/user/settings/meal/edit/form/{recipe_guid}/"
        )

    # ---- diary-entry edit (an already-logged item in the diary) ---------

    async def get_diary_entry_form(self, entry_guid: str) -> Any:
        """Fetch the edit form for an existing diary entry.

        `entry_guid` = the `id` field of each item in
        `get_day().times[].foodstuff[]` (upstream `guidDiary`).
        """
        return await self._s.get_json(
            f"/user/diary/meal/edit/form/{entry_guid}"
        )

    async def save_diary_entry(self, payload: dict[str, Any]) -> None:
        """POST a fully-prepared diary entry edit payload."""
        await self._s.post_json("/user/meal/edit", json_body=payload)

    async def edit_diary_entry(
        self,
        entry_guid: str,
        *,
        exclude_ingredients: list[str] | None = None,
        scale_ingredients: dict[str, float] | None = None,
        meal_id: str | None = None,
    ) -> dict[str, Any]:
        """High-level: fetch entry edit form, optionally remove or scale
        ingredients (and/or move to a different meal slot), POST. Upstream
        recomputes totals from the items we send.

        Returns summary of changes applied.
        """
        form = await self.get_diary_entry_form(entry_guid)
        if not isinstance(form, dict):
            raise ValueError(f"unexpected edit-form shape for entry {entry_guid}")

        if meal_id is not None:
            form["diaryTimeGuid"] = meal_id

        excludes = [e.strip().lower() for e in (exclude_ingredients or [])]
        scales = {k.strip().lower(): float(v) for k, v in (scale_ingredients or {}).items()}

        items = form.get("foodstuff") or []
        kept: list[dict[str, Any]] = []
        excluded: list[str] = []
        scaled: list[dict[str, Any]] = []

        for it in items:
            if not isinstance(it, dict):
                kept.append(it)
                continue
            title = (it.get("title") or "").strip().lower()
            guid = (it.get("guid") or "").strip().lower()
            food_guid = (it.get("foodstuffGuid") or "").strip().lower()
            keys = {title, guid, food_guid} - {""}

            if any(k in excludes for k in keys):
                excluded.append(it.get("title") or guid)
                continue

            factor = next((scales[k] for k in keys if k in scales), None)
            if factor is not None:
                old_count = it.get("count")
                try:
                    new_count = float(old_count) * factor
                    it = {**it, "count": new_count, "countOriginal": new_count}
                    scaled.append({"title": it.get("title"), "factor": factor,
                                   "old_count": old_count, "new_count": new_count})
                except Exception:
                    pass
            kept.append(it)

        form["foodstuff"] = kept
        await self.save_diary_entry(form)
        return {
            "entry_guid": entry_guid,
            "ingredients_total": len(items),
            "ingredients_kept": len(kept),
            "excluded": excluded,
            "scaled": scaled,
            "meal_id": form.get("diaryTimeGuid"),
        }

    async def save_definition(
        self,
        *,
        recipe_guid: str,
        payload: dict[str, Any],
    ) -> Any:
        """Persist a recipe definition.
        - `recipe_guid="0"` creates a new recipe; response `data` = new GUID.
        - existing GUID updates that recipe in place.
        """
        return await self._s.post_json(
            f"/user/settings/meal/detail/edit/{recipe_guid}",
            json_body=payload,
        )

    async def quick_add_to_diary(
        self,
        recipe_guid: str,
        *,
        day: date_cls | str,
        meal_id: str,
        exclude_ingredients: list[str] | None = None,
        scale_ingredients: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Fetch add-form, override meal slot + date, optionally
        remove/scale ingredients, POST.

        `exclude_ingredients`: list of foodstuff titles or GUIDs to drop
          (case-insensitive title match, exact GUID match).
        `scale_ingredients`: {title_or_guid: factor} to multiply that
          ingredient's `count` (e.g. 0.5 = half portion, 2.0 = double).

        Upstream re-derives totals server-side from the items we send.
        Returns a summary of what was applied.
        """
        form = await self.get_add_form(recipe_guid)
        if not isinstance(form, dict):
            form = {"guid": recipe_guid}
        form["diaryTimeGuid"] = meal_id
        form["date"] = fmt_date(day)

        excludes = [e.strip().lower() for e in (exclude_ingredients or [])]
        scales = {k.strip().lower(): float(v) for k, v in (scale_ingredients or {}).items()}

        items = form.get("foodstuff") or []
        kept: list[dict[str, Any]] = []
        excluded: list[str] = []
        scaled: list[dict[str, Any]] = []

        for it in items:
            if not isinstance(it, dict):
                kept.append(it)
                continue
            title = (it.get("title") or "").strip().lower()
            guid = (it.get("guid") or "").strip().lower()
            food_guid = (it.get("foodstuffGuid") or "").strip().lower()
            keys = {title, guid, food_guid} - {""}

            if any(k in excludes for k in keys):
                excluded.append(it.get("title") or guid)
                continue

            factor = next((scales[k] for k in keys if k in scales), None)
            if factor is not None:
                old_count = it.get("count")
                try:
                    new_count = float(old_count) * factor
                    it = {**it, "count": new_count, "countOriginal": new_count}
                    scaled.append({"title": it.get("title"), "factor": factor,
                                   "old_count": old_count, "new_count": new_count})
                except Exception:
                    pass
            kept.append(it)

        form["foodstuff"] = kept
        await self.add_to_diary(form)
        return {
            "ingredients_total": len(items),
            "ingredients_kept": len(kept),
            "excluded": excluded,
            "scaled": scaled,
        }
