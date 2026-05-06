"""Catalog search tools."""
from __future__ import annotations

from typing import Any

from tablycja_client import TablycjaClient


async def search_food(
    client: TablycjaClient, *, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Search foodstuffs/activities/meals by name. Returns up to `limit` hits.

    Each hit includes `id` (use as `food_id` / `activity_id` for logging),
    `clazz` (`foodstuff` | `activity` | `meal`), `title`, `unit`, `value`,
    `energy`, `energy_unit`.
    """
    hits = await client.catalog.autocomplete(query)
    return [
        {
            "id": h.id,
            "clazz": h.clazz,
            "title": h.title,
            "unit": h.unit,
            "value": h.value,
            "energy": h.energy,
            "energy_unit": h.energyUnit,
            "url": h.url,
        }
        for h in hits[:limit]
    ]


async def search_activity(
    client: TablycjaClient, *, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    hits = await client.catalog.autocomplete_activity(query)
    return [
        {
            "id": h.id,
            "title": h.title,
            "unit": h.unit,
            "energy": h.energy,
            "energy_unit": h.energyUnit,
            "url": h.url,
        }
        for h in hits[:limit]
    ]


async def get_food_detail(
    client: TablycjaClient, *, food_id: str
) -> dict[str, Any]:
    """Full detail: macros, units, default portion."""
    return await client.catalog.food_detail(food_id)


async def search_food_with_macros(
    client: TablycjaClient,
    *,
    query: str,
    limit: int = 10,
    min_energy: int = 0,
    max_energy: int = 3800,
) -> dict[str, Any]:
    """Full-DB foodstuff search with per-100g macros (energy, protein,
    carbohydrate, fat, fiber, sugar, salt, ...).

    Returns `{count, items: [...]}` — `count` is the total matching DB rows,
    `items` is up to `limit` results with id (use as food_id) + nutrients.
    """
    raw = await client.catalog.filter_foodstuff(
        query=query, page=0, limit=limit,
        min_energy=min_energy, max_energy=max_energy,
    )
    items_raw = raw.get("data", []) if isinstance(raw, dict) else []
    items = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        items.append({
            "id": it.get("id"),
            "title": it.get("title"),
            "url": it.get("url"),
            "energy": it.get("energy"),
            "energy_unit": it.get("energyUnit"),
            "protein": it.get("protein"),
            "carbohydrate": it.get("carbohydrate"),
            "fat": it.get("fat"),
            "fiber": it.get("fiber"),
            "sugar": it.get("sugar"),
            "saturated_fatty_acid": it.get("saturatedFattyAcid"),
            "salt": it.get("salt"),
            "water": it.get("water"),
            "calcium": it.get("calcium"),
            "sodium": it.get("sodium"),
            "cholesterol": it.get("cholesterol"),
        })
    return {
        "count": raw.get("count") if isinstance(raw, dict) else None,
        "items": items,
    }
