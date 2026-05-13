"""Qdrant-backed semantic cache for the foodstuff catalog.

Wraps `qdrant-client` async API. Reads `QDRANT_URL`, `QDRANT_API_KEY`, and
`QDRANT_COLLECTION` from env. Vectors are 384d cosine (intfloat/multilingual-e5-small).

Point IDs derive from upstream's 16-char hex foodstuff GUID:
    int(guid, 16) — fits 64-bit unsigned.
The original GUID is preserved in the payload as `id` (drop-in shape match
with `search_food_with_macros`).
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

DEFAULT_COLLECTION = "foodstuff_uk"
DEFAULT_VECTOR_SIZE = 384  # intfloat/multilingual-e5-small


def _guid_to_point_id(guid: str) -> str:
    """Upstream foodstuff GUID is 32 hex chars (128-bit). Qdrant requires
    either uint64 or UUID; format as UUID string."""
    h = guid.strip().lower().replace("-", "")
    if len(h) == 32 and all(c in "0123456789abcdef" for c in h):
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    # Fallback: shorter hex (e.g. 16 chars) — left-pad to 32.
    if len(h) < 32 and all(c in "0123456789abcdef" for c in h):
        h = h.rjust(32, "0")
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    raise ValueError(f"unexpected GUID format: {guid!r}")


def _client_kwargs() -> dict[str, Any]:
    url = os.environ.get("QDRANT_URL")
    if not url:
        raise RuntimeError("QDRANT_URL not set")
    return {
        "url": url,
        "api_key": os.environ.get("QDRANT_API_KEY") or None,
        "timeout": 60,
    }


def collection_name() -> str:
    return os.environ.get("QDRANT_COLLECTION", DEFAULT_COLLECTION)


def make_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(**_client_kwargs())


async def ensure_collection(
    client: AsyncQdrantClient,
    *,
    vector_size: int = DEFAULT_VECTOR_SIZE,
) -> None:
    """Create collection + payload indexes if missing. Idempotent."""
    name = collection_name()
    exists = await client.collection_exists(name)
    if not exists:
        await client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
        )
    # Range filters on energy. Energy is an int in upstream payloads but
    # comes through as a string in some rows — index as float to be safe.
    try:
        await client.create_payload_index(
            collection_name=name,
            field_name="energy_num",
            field_schema=qm.PayloadSchemaType.FLOAT,
        )
    except Exception:
        pass


async def upsert_rows(
    client: AsyncQdrantClient,
    rows: list[dict[str, Any]],
    vectors: list[list[float]],
) -> None:
    """Upsert a batch. `rows[i]` must have `id` (hex GUID). `vectors[i]` is
    the dense embedding of that row's title."""
    if len(rows) != len(vectors):
        raise ValueError("rows/vectors length mismatch")
    points: list[qm.PointStruct] = []
    for row, vec in zip(rows, vectors):
        guid = row.get("id")
        if not isinstance(guid, str):
            continue
        payload = dict(row)
        # Numeric energy for range filtering; tolerate strings + None.
        e = row.get("energy")
        try:
            payload["energy_num"] = float(e) if e not in (None, "") else 0.0
        except (TypeError, ValueError):
            payload["energy_num"] = 0.0
        points.append(
            qm.PointStruct(
                id=_guid_to_point_id(guid),
                vector=vec,
                payload=payload,
            )
        )
    if not points:
        return
    import asyncio as _asyncio

    # Gentle pacing — Qdrant Cloud free tier throttles under sustained writes.
    await _asyncio.sleep(0.25)

    last_exc: Exception | None = None
    for attempt in range(10):
        try:
            await client.upsert(
                collection_name=collection_name(), points=points, wait=False
            )
            return
        except Exception as e:  # noqa: BLE001
            last_exc = e
            backoff = min(2 ** attempt, 30)
            print(
                f"qdrant upsert retry {attempt + 1}/10 "
                f"({type(e).__name__}: {e!r}) sleep={backoff}s"
            )
            await _asyncio.sleep(backoff)
    raise RuntimeError(
        f"qdrant upsert failed after 10 retries: "
        f"{type(last_exc).__name__}: {last_exc!r}"
    )


async def existing_ids(
    client: AsyncQdrantClient, guids: Iterable[str]
) -> set[str]:
    """Return subset of `guids` already in the collection (for resumable ingest)."""
    name = collection_name()
    point_ids = [_guid_to_point_id(g) for g in guids]
    if not point_ids:
        return set()
    found = await client.retrieve(
        collection_name=name,
        ids=point_ids,
        with_payload=["id"],
        with_vectors=False,
    )
    out: set[str] = set()
    for rec in found:
        gid = (rec.payload or {}).get("id")
        if isinstance(gid, str):
            out.add(gid)
    return out


async def semantic_search(
    client: AsyncQdrantClient,
    *,
    vector: list[float],
    limit: int = 10,
    min_energy: float | None = None,
    max_energy: float | None = None,
) -> list[dict[str, Any]]:
    name = collection_name()
    flt: qm.Filter | None = None
    if min_energy is not None or max_energy is not None:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="energy_num",
                    range=qm.Range(gte=min_energy, lte=max_energy),
                )
            ]
        )
    res = await client.query_points(
        collection_name=name,
        query=vector,
        limit=limit,
        query_filter=flt,
        with_payload=True,
        with_vectors=False,
    )
    out: list[dict[str, Any]] = []
    for p in res.points:
        payload = dict(p.payload or {})
        payload.pop("energy_num", None)
        payload["score"] = p.score
        out.append(payload)
    return out


__all__ = [
    "make_client",
    "collection_name",
    "ensure_collection",
    "upsert_rows",
    "existing_ids",
    "semantic_search",
    "DEFAULT_VECTOR_SIZE",
]
