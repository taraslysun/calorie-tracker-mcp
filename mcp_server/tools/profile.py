"""Profile tools."""
from __future__ import annotations

from typing import Any

from tablycja_client import TablycjaClient


async def get_profile(client: TablycjaClient) -> dict[str, Any]:
    """Full profile: height, weight, sex, birth year, target weight, daily energy goal,
    activity multiplier (AMR), drink regime, macro goals."""
    p = await client.profile.get()
    return {
        "guid": p.guid,
        "email": p.email,
        "sex": p.sex,
        "height_cm": p.height,
        "weight_kg": p.weight,
        "birth_year": p.year,
        "target_weight_kg": p.targetWeight,
        "drink_regime_l": p.drinkRegime,
        "amr": p.amr,
        "energy_unit": p.energyUnit,
        "consider_activity": p.considerActivity,
        "macro_goals": [
            {
                "code": n.code,
                "title": n.title,
                "value": n.value,
                "computed": n.computedValue,
                "active": n.active,
            }
            for n in p.ownNutrients
        ],
    }


async def get_active_user(client: TablycjaClient) -> dict[str, Any]:
    """Compact account record. Useful as auth probe."""
    u = await client.profile.active_user()
    return {
        "id": u.id,
        "email": u.email,
        "sex": u.sex,
        "birth_year": u.birthYear,
        "lang": u.lang,
        "google_id": u.googleId,
    }
