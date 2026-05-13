"""Quality smoke-test: intfloat/multilingual-e5-small vs current BGE-M3
Qdrant collection. Samples ~5000 titles from Qdrant, embeds them locally
with e5-small (`passage:` prefix), then runs UA + EN test queries through
both the new e5 index and the existing BGE-M3 Qdrant index. Prints
top-5 side-by-side so a human can eyeball whether e5-small is good enough.

Run:
    uv run --group ingest python scripts/quality_check_e5.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tablycja_client import cache as qcache  # noqa: E402

SAMPLE_N = 5000

QUERIES = [
    "cottage cheese",
    "халва",
    "риба",
    "щось солодке з горіхами",
    "high-protein breakfast",
    "куряча грудка",
    "peanut butter",
    "yogurt with berries",
    "білковий перекус",
]


async def sample_titles(n: int) -> list[dict]:
    client = qcache.make_client()
    try:
        out: list[dict] = []
        next_page = None
        while len(out) < n:
            res, next_page = await client.scroll(
                collection_name=qcache.collection_name(),
                limit=min(1000, n - len(out)),
                with_payload=True,
                with_vectors=False,
                offset=next_page,
            )
            for p in res:
                pay = p.payload or {}
                t = str(pay.get("title", "")).strip()
                if t:
                    out.append({"id": pay.get("id"), "title": t})
            if next_page is None:
                break
        return out
    finally:
        await client.close()


def cosine_topk(query_vec: np.ndarray, matrix: np.ndarray, k: int = 5) -> list[int]:
    # vectors already L2-normalized
    scores = matrix @ query_vec
    idx = np.argpartition(-scores, k)[:k]
    return list(idx[np.argsort(-scores[idx])])


async def main() -> None:
    load_dotenv()
    print(f"sampling {SAMPLE_N} titles from Qdrant ...")
    rows = await sample_titles(SAMPLE_N)
    print(f"got {len(rows)} titles")

    from sentence_transformers import SentenceTransformer
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"loading intfloat/multilingual-e5-small on {device} ...")
    t0 = time.time()
    model = SentenceTransformer("intfloat/multilingual-e5-small", device=device)
    print(f"load took {time.time() - t0:.1f}s")

    titles = [r["title"] for r in rows]
    passages = [f"passage: {t}" for t in titles]
    print("embedding sample (passage prefix) ...")
    t0 = time.time()
    pmat = model.encode(
        passages, batch_size=64, normalize_embeddings=True, show_progress_bar=True
    )
    pmat = np.asarray(pmat, dtype=np.float32)
    print(f"embed sample: {time.time() - t0:.1f}s shape={pmat.shape}")

    # Probe BGE-M3 index in parallel for the same queries.
    qc = qcache.make_client()
    from tablycja_client import embeddings as bge

    print("\n=== quality comparison (top-5) ===")
    for q in QUERIES:
        print(f"\n--- query: {q!r} ---")

        # e5-small over sample.
        qv = model.encode([f"query: {q}"], normalize_embeddings=True)[0]
        qv = np.asarray(qv, dtype=np.float32)
        idxs = cosine_topk(qv, pmat, k=5)
        print("[e5-small / 5k sample]")
        for i in idxs:
            score = float(pmat[i] @ qv)
            print(f"  {score:.3f}  {rows[i]['title']}")

        # BGE-M3 over full 205k Qdrant.
        bvec = bge.embed_one(q)
        items = await qcache.semantic_search(qc, vector=bvec, limit=5)
        print("[BGE-M3 / 205k full]")
        for it in items:
            print(f"  {it.get('score'):.3f}  {it.get('title')}")

    await qc.close()


if __name__ == "__main__":
    asyncio.run(main())
