"""Semantic foodstuff search tool.

Reads the local Qdrant mirror built by `scripts/build_index.py`. No upstream
calls on this path — independent of cookie/session state.
"""
from __future__ import annotations

from typing import Any

from tablycja_client import cache as qcache
from tablycja_client import embeddings as emb


async def semantic_search_food(
    *,
    query: str,
    limit: int = 10,
    min_energy: float | None = None,
    max_energy: float | None = None,
) -> dict[str, Any]:
    """Vector search foods by meaning, not substring. Output shape mirrors
    `search_food_with_macros` (`{count, items}`)."""
    q = (query or "").strip()
    if not q:
        return {"count": 0, "items": []}
    vec = emb.embed_query(q)
    client = qcache.make_client()
    try:
        items = await qcache.semantic_search(
            client,
            vector=vec,
            limit=limit,
            min_energy=min_energy,
            max_energy=max_energy,
        )
    finally:
        await client.close()
    return {"count": len(items), "items": items}


__all__ = ["semantic_search_food"]
