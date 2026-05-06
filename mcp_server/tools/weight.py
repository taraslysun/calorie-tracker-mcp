"""Weight tools."""
from __future__ import annotations

from typing import Any

from tablycja_client import TablycjaClient

from .diary import _parse_date


async def log_weight(
    client: TablycjaClient, *, weight_kg: float, day: str
) -> dict[str, Any]:
    """Log body weight in kilograms for a given day."""
    d = _parse_date(day)
    await client.weight.add(weight_kg, d)
    return {"ok": True, "weight_kg": weight_kg, "date": d.isoformat()}
