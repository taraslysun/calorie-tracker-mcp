"""Personal recipes ("My Recipes" / saved meals) tools."""
from __future__ import annotations

from typing import Any

from tablycja_client import TablycjaClient

from .diary import _parse_date, _resolve_meal


async def list_my_recipes(
    client: TablycjaClient,
    *,
    query: str = "",
    page: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Paginated list of the user's saved personal recipes ("Мої рецепти").

    Each item exposes `guid` (use as `recipe_id`), `title`, `energy`,
    `energyUnit`, `visibility`, `portions`.
    """
    raw = await client.meals.list(query=query, page=page, limit=limit)
    items = raw.get("data", []) if isinstance(raw, dict) else []
    return {
        "count": raw.get("count") if isinstance(raw, dict) else None,
        "items": [
            {
                "id": it.get("guid"),
                "title": it.get("title"),
                "energy": it.get("energy"),
                "energy_unit": it.get("energyUnit"),
                "portions": it.get("portions"),
                "visibility": it.get("visibility"),
                "guid_recipe": it.get("guidRecipe"),
            }
            for it in items
            if isinstance(it, dict)
        ],
    }


async def get_my_recipe(
    client: TablycjaClient, *, recipe_id: str
) -> dict[str, Any]:
    """Full detail for a personal recipe: macros + ingredient breakdown."""
    raw = await client.meals.detail(recipe_id)
    # /recipe/detail returns enveloped response — session._unwrap returns data already
    if not isinstance(raw, dict):
        return {"raw": raw}
    return raw


async def get_diary_entry(
    client: TablycjaClient, *, entry_id: str
) -> dict[str, Any]:
    """Editable form for an already-logged diary entry. `entry_id` = the `id`
    field on each item in `get_day().meals[].items[]`."""
    raw = await client.meals.get_diary_entry_form(entry_id)
    return raw if isinstance(raw, dict) else {"raw": raw}


async def edit_diary_entry(
    client: TablycjaClient,
    *,
    entry_id: str,
    exclude_ingredients: list[str] | None = None,
    scale_ingredients: dict[str, float] | None = None,
    meal: str | None = None,
) -> dict[str, Any]:
    """Edit a diary entry: remove ingredients, scale ingredient counts,
    and/or move to a different meal slot. Upstream recomputes calories +
    macros from what we send."""
    meal_id = _resolve_meal(meal) if meal else None
    return await client.meals.edit_diary_entry(
        entry_id,
        exclude_ingredients=exclude_ingredients,
        scale_ingredients=scale_ingredients,
        meal_id=meal_id,
    )


async def log_recipe(
    client: TablycjaClient,
    *,
    recipe_id: str,
    meal: str,
    day: str,
    exclude_ingredients: list[str] | None = None,
    scale_ingredients: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Add a personal recipe entry to the diary, optionally removing or
    scaling individual ingredients before logging. Upstream recomputes
    totals from the items we send.

    Args:
      recipe_id: GUID from `list_my_recipes`.
      meal: breakfast/snack1/lunch/snack2/dinner/snack3 or 1-6.
      day: ISO YYYY-MM-DD or DD.MM.YYYY.
      exclude_ingredients: titles or GUIDs to drop (e.g. ["Йогурт"]).
      scale_ingredients: {title_or_guid: factor}, e.g. {"Авокадо Хасс": 0.5}.
    """
    d = _parse_date(day)
    meal_id = _resolve_meal(meal)
    summary = await client.meals.quick_add_to_diary(
        recipe_id,
        day=d,
        meal_id=meal_id,
        exclude_ingredients=exclude_ingredients,
        scale_ingredients=scale_ingredients,
    )
    return {
        "ok": True,
        "recipe_id": recipe_id,
        "meal_id": meal_id,
        "date": d.isoformat(),
        **summary,
    }
