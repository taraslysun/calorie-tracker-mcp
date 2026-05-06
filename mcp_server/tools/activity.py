"""Activity tools."""
from __future__ import annotations

from typing import Any

from tablycja_client import TablycjaClient

from .diary import _parse_date


async def log_activity(
    client: TablycjaClient,
    *,
    activity_id: str,
    minutes: float,
    day: str,
) -> dict[str, Any]:
    """Log an activity entry. `activity_id` = GUID from `search_activity`."""
    d = _parse_date(day)
    await client.activity.quick_add(activity_id, day=d, minutes=minutes)
    return {"ok": True, "activity_id": activity_id, "minutes": minutes,
            "date": d.isoformat()}
