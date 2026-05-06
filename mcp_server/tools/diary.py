"""Diary tools: read day, read summary, log food."""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from tablycja_client import TablycjaClient

# Mealtime IDs are constant per upstream — exposed so the model can pass either
# the numeric id or the meal name.
MEAL_NAME_TO_ID = {
    "breakfast": "1",
    "snack1": "2",
    "lunch": "3",
    "snack2": "4",
    "dinner": "5",
    "snack3": "6",
    # Ukrainian aliases as a convenience.
    "сніданок": "1",
    "перший перекус": "2",
    "обід": "3",
    "другий перекус": "4",
    "вечеря": "5",
    "третій перекус": "6",
}


def _resolve_meal(meal: str) -> str:
    if meal in {"1", "2", "3", "4", "5", "6"}:
        return meal
    key = meal.strip().lower()
    if key in MEAL_NAME_TO_ID:
        return MEAL_NAME_TO_ID[key]
    raise ValueError(
        f"Unknown meal '{meal}'. Use 1-6 or one of: "
        f"breakfast, snack1, lunch, snack2, dinner, snack3."
    )


def _parse_date(d: str) -> date_cls:
    """Accept YYYY-MM-DD (ISO) or DD.MM.YYYY (upstream)."""
    s = d.strip()
    if "-" in s:
        return date_cls.fromisoformat(s)
    parts = s.split(".")
    if len(parts) != 3:
        raise ValueError(f"Bad date '{d}'. Use YYYY-MM-DD or DD.MM.YYYY.")
    dd, mm, yy = (int(p) for p in parts)
    return date_cls(yy, mm, dd)


async def get_day(client: TablycjaClient, day: str) -> dict[str, Any]:
    """Return the diary for a date. `day` = ISO YYYY-MM-DD or DD.MM.YYYY."""
    d = _parse_date(day)
    diary = await client.diary.get_day(d)
    return {
        "date": d.isoformat(),
        "energy_unit": diary.energyUnit,
        "meals": [
            {
                "id": t.id,
                "title": t.title,
                "energy_total": t.energyTotal,
                "energy_unit": t.energyTotalUnit,
                "items": [item.model_dump() for item in t.foodstuff],
            }
            for t in diary.times
        ],
    }


async def get_summary(client: TablycjaClient, day: str) -> dict[str, Any]:
    """Daily summary: energy goal vs actual + macros."""
    d = _parse_date(day)
    s = await client.diary.get_summary(d)
    return {
        "date": d.isoformat(),
        "items": [item.model_dump() for item in s.items],
        "items_dynamic": [[c.model_dump() for c in row] for row in s.itemsDynamic],
    }


async def log_food(
    client: TablycjaClient,
    *,
    food_id: str,
    grams: float,
    meal: str,
    day: str,
) -> dict[str, Any]:
    """Add a food entry to the diary.

    Args:
      food_id: foodstuff GUID from `search_food`.
      grams: amount in grams.
      meal: meal slot name (breakfast/lunch/dinner/snack1/snack2/snack3) or 1..6.
      day: ISO YYYY-MM-DD or DD.MM.YYYY.
    """
    d = _parse_date(day)
    meal_id = _resolve_meal(meal)
    await client.diary.quick_add_food(
        food_id, day=d, meal_id=meal_id, grams=grams
    )
    return {"ok": True, "food_id": food_id, "grams": grams,
            "meal_id": meal_id, "date": d.isoformat()}
