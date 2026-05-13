"""Drain upstream foodstuff catalog → embed → upsert to Qdrant.

Resumable: tracks last completed page in `scripts/.ingest_state.json`. Re-runs
skip already-upserted GUIDs via Qdrant retrieve.

Auth: reads `TABLYCJA_COOKIES` (JSON dict) and/or `TABLYCJA_EMAIL`+
`TABLYCJA_PASSWORD` from env. If both present, email/password enables the
auto-relogin path inside `TablycjaSession`.

Run:
    uv sync --group ingest
    uv run --group ingest python scripts/build_index.py --limit-pages 5

Full ingest (~75 min on M-series CPU, faster on MPS):
    uv run --group ingest python scripts/build_index.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Repo root on sys.path so `tablycja_client` resolves when run as script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tablycja_client import TablycjaClient  # noqa: E402
from tablycja_client import cache as qcache  # noqa: E402
from tablycja_client import embeddings as emb  # noqa: E402

STATE_PATH = ROOT / "scripts" / ".ingest_state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def build_upstream_client() -> TablycjaClient:
    cookies_raw = os.environ.get("TABLYCJA_COOKIES", "").strip()
    cookies = json.loads(cookies_raw) if cookies_raw else None
    creds = None
    email = os.environ.get("TABLYCJA_EMAIL")
    password = os.environ.get("TABLYCJA_PASSWORD")
    if email and password:
        creds = {"email": email, "password": password}
    if not cookies and not creds:
        raise SystemExit(
            "Set TABLYCJA_COOKIES (JSON) or TABLYCJA_EMAIL + TABLYCJA_PASSWORD."
        )
    # Provide a stale cookie if only creds were given — relogin path triggers
    # on first 302 → /login.
    return TablycjaClient(cookies=cookies or {"JSESSIONID": "stale"}, login_creds=creds)


async def ingest(
    *,
    page_limit: int,
    embed_batch: int,
    max_pages: int | None,
    page_concurrency: int,
) -> None:
    load_dotenv()
    state = load_state()
    last_page = state.get("last_page", -1)
    print(f"resuming from page {last_page + 1}")

    client = build_upstream_client()
    qc = qcache.make_client()
    await qcache.ensure_collection(qc, vector_size=emb.DEFAULT_DIM)

    # Pre-login so concurrent page fetches don't race on the relogin guard.
    email = os.environ.get("TABLYCJA_EMAIL")
    password = os.environ.get("TABLYCJA_PASSWORD")
    if email and password:
        try:
            await client.login_password(email, password)
            print("pre-login OK")
        except Exception as e:  # noqa: BLE001
            print(f"pre-login failed (continuing with stored cookies): {e}")

    # Probe total count + sanity-check shape.
    head = await client.catalog.filter_foodstuff(page=0, limit=1)
    total = int(head.get("count") or 0)
    total_pages = (total + page_limit - 1) // page_limit
    print(f"upstream total={total} rows, pages={total_pages} @ limit={page_limit}")

    if max_pages is not None:
        total_pages = min(total_pages, last_page + 1 + max_pages)

    sem = asyncio.Semaphore(page_concurrency)

    async def fetch_page(p: int):
        for attempt in range(3):
            async with sem:
                try:
                    resp = await client.catalog.filter_foodstuff(
                        page=p, limit=page_limit
                    )
                    data = resp.get("data") or []
                    return p, data
                except Exception as e:  # noqa: BLE001
                    print(f"page {p} fetch error attempt {attempt}: {e}")
                    # Relogin + retry.
                    if email and password:
                        try:
                            await client.login_password(email, password)
                        except Exception as e2:  # noqa: BLE001
                            print(f"page {p} relogin failed: {e2}")
                    await asyncio.sleep(1 + attempt)
        return p, []

    t0 = time.time()
    embedded = 0
    pages_iter = range(last_page + 1, total_pages)
    # Process in chunks so we can checkpoint state every chunk.
    CHUNK = max(page_concurrency, 4)
    for chunk_start in range(pages_iter.start, pages_iter.stop, CHUNK):
        chunk = list(range(chunk_start, min(chunk_start + CHUNK, pages_iter.stop)))
        results = await asyncio.gather(*(fetch_page(p) for p in chunk))
        results.sort(key=lambda x: x[0])
        rows: list[dict] = []
        for _, page_rows in results:
            rows.extend(page_rows)
        if not rows:
            print(f"pages {chunk[0]}..{chunk[-1]} | EMPTY (skipping)")
            save_state({"last_page": chunk[-1], "total": total})
            continue
        # Filter out rows already in Qdrant (resumable safety).
        guids = [r["id"] for r in rows if isinstance(r.get("id"), str)]
        try:
            already = await qcache.existing_ids(qc, guids)
        except Exception as e:  # noqa: BLE001
            print(f"existing_ids probe failed ({e}); proceeding without skip")
            already = set()
        rows = [r for r in rows if r.get("id") not in already]
        if not rows:
            save_state({"last_page": chunk[-1], "total": total})
            continue
        # Embed in mini-batches.
        for i in range(0, len(rows), embed_batch):
            batch = rows[i : i + embed_batch]
            titles = [str(r.get("title", "")).strip() for r in batch]
            vecs = emb.embed_passages(titles, batch_size=embed_batch)
            await qcache.upsert_rows(qc, batch, vecs)
            embedded += len(batch)
        save_state({"last_page": chunk[-1], "total": total})
        elapsed = time.time() - t0
        rate = embedded / max(elapsed, 1e-9)
        print(
            f"pages {chunk[0]}..{chunk[-1]} | embedded so far={embedded} "
            f"| {rate:.1f} rows/s | last_page={chunk[-1]}"
        )

    await client.aclose()
    await qc.close()
    print(f"done. embedded={embedded} in {time.time() - t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-limit", type=int, default=200, help="rows per page")
    ap.add_argument("--embed-batch", type=int, default=64, help="embed batch size")
    ap.add_argument("--max-pages", type=int, default=None, help="cap pages this run")
    ap.add_argument("--page-concurrency", type=int, default=4)
    ap.add_argument("--reset", action="store_true", help="delete state and restart")
    args = ap.parse_args()
    if args.reset and STATE_PATH.exists():
        STATE_PATH.unlink()
    asyncio.run(
        ingest(
            page_limit=args.page_limit,
            embed_batch=args.embed_batch,
            max_pages=args.max_pages,
            page_concurrency=args.page_concurrency,
        )
    )


if __name__ == "__main__":
    main()
