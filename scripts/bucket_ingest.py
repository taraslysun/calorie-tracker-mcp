"""Bigram-bucket ingest: workaround for upstream's 10k offset cap.

Upstream `/foodstuff/filter-list` returns at most ~10k unique rows per
filter, no matter what `count` claims. To enumerate the full ~206k corpus
we issue many `query=` searches and drain each (up to 50 pages × 200).

Buckets = single-char + bigram prefixes drawn from Ukrainian Cyrillic +
Latin + digits. `query=` does substring matching, so coverage is messy
but broad; rows are deduped by upstream GUID (we skip GUIDs already in
Qdrant before embedding).

Resumable: completed buckets recorded in `scripts/.bucket_state.json`.
Re-run picks up where it left off.

Run:
    uv run --group ingest python scripts/bucket_ingest.py
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tablycja_client import TablycjaClient  # noqa: E402
from tablycja_client import cache as qcache  # noqa: E402
from tablycja_client import embeddings as emb  # noqa: E402

STATE_PATH = ROOT / "scripts" / ".bucket_state.json"

# Coverage alphabet: Ukrainian Cyrillic + apostrophe + Latin + digits.
UK = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
LAT = "abcdefghijklmnopqrstuvwxyz"
DIG = "0123456789"
ALPHA = UK + LAT + DIG


def all_buckets() -> list[str]:
    """Single chars + all bigrams from ALPHA."""
    singles = list(ALPHA)
    bigrams = ["".join(p) for p in itertools.product(UK + LAT, repeat=2)]
    return singles + bigrams


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"done": []}


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
        raise SystemExit("set TABLYCJA_COOKIES or TABLYCJA_EMAIL+TABLYCJA_PASSWORD")
    return TablycjaClient(cookies=cookies or {"JSESSIONID": "stale"}, login_creds=creds)


async def drain_bucket(
    client: TablycjaClient,
    bucket: str,
    *,
    page_limit: int,
    max_pages: int,
) -> list[dict]:
    """Pull all pages for one query bucket until upstream returns empty or
    hits the offset cap (50 pages @ 200)."""
    rows: list[dict] = []
    email = os.environ.get("TABLYCJA_EMAIL")
    password = os.environ.get("TABLYCJA_PASSWORD")
    for page in range(max_pages):
        for attempt in range(3):
            try:
                r = await client.catalog.filter_foodstuff(
                    page=page, limit=page_limit, query=bucket
                )
                data = r.get("data") or []
                break
            except Exception as e:  # noqa: BLE001
                if email and password and attempt < 2:
                    try:
                        await client.login_password(email, password)
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(1 + attempt)
                    continue
                print(f"  bucket={bucket!r} page={page} hard fail: {e}")
                data = []
                break
        if not data:
            break
        rows.extend(data)
    return rows


async def run(
    *,
    page_limit: int,
    embed_batch: int,
    bucket_concurrency: int,
    max_pages_per_bucket: int,
) -> None:
    load_dotenv()
    state = load_state()
    done: set[str] = set(state.get("done", []))

    client = build_upstream_client()
    qc = qcache.make_client()
    await qcache.ensure_collection(qc, vector_size=emb.DEFAULT_DIM)

    email = os.environ.get("TABLYCJA_EMAIL")
    password = os.environ.get("TABLYCJA_PASSWORD")
    if email and password:
        try:
            await client.login_password(email, password)
            print("pre-login OK")
        except Exception as e:  # noqa: BLE001
            print(f"pre-login failed (continuing): {e}")

    buckets = [b for b in all_buckets() if b not in done]
    print(f"total buckets={len(all_buckets())} pending={len(buckets)}")

    sem = asyncio.Semaphore(bucket_concurrency)
    t0 = time.time()
    embedded_total = 0
    seen_session: set[str] = set()  # in-process dedupe across buckets

    async def handle(b: str) -> tuple[str, int]:
        async with sem:
            rows = await drain_bucket(
                client, b,
                page_limit=page_limit, max_pages=max_pages_per_bucket,
            )
            # Dedupe within session.
            uniq: list[dict] = []
            for r in rows:
                gid = r.get("id")
                if not isinstance(gid, str) or gid in seen_session:
                    continue
                seen_session.add(gid)
                uniq.append(r)
            if not uniq:
                return b, 0
            # Skip GUIDs already in Qdrant.
            guids = [r["id"] for r in uniq]
            try:
                already = await qcache.existing_ids(qc, guids)
            except Exception:  # noqa: BLE001
                already = set()
            uniq = [r for r in uniq if r["id"] not in already]
            if not uniq:
                return b, 0
            # Embed + upsert in mini-batches.
            n = 0
            for i in range(0, len(uniq), embed_batch):
                batch = uniq[i:i + embed_batch]
                titles = [str(r.get("title", "")).strip() for r in batch]
                vecs = emb.embed_passages(titles, batch_size=embed_batch)
                await qcache.upsert_rows(qc, batch, vecs)
                n += len(batch)
            return b, n

    # Run buckets in chunks so we can checkpoint state regularly.
    CHUNK = max(bucket_concurrency * 4, 16)
    for i in range(0, len(buckets), CHUNK):
        sub = buckets[i:i + CHUNK]
        results = await asyncio.gather(*(handle(b) for b in sub))
        for b, n in results:
            embedded_total += n
            done.add(b)
        save_state({"done": sorted(done)})
        elapsed = time.time() - t0
        progress = len(done) / len(all_buckets()) * 100
        # Live points count after each chunk.
        try:
            info = await qc.get_collection(qcache.collection_name())
            pts = info.points_count
        except Exception:  # noqa: BLE001
            pts = "?"
        print(
            f"chunk done | buckets {len(done)}/{len(all_buckets())} "
            f"({progress:.1f}%) | new this run={embedded_total} | "
            f"qdrant_total={pts} | elapsed={elapsed:.0f}s"
        )

    await client.aclose()
    await qc.close()
    print(f"all buckets done. new this run={embedded_total} in {time.time()-t0:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-limit", type=int, default=200)
    ap.add_argument("--embed-batch", type=int, default=64)
    ap.add_argument("--bucket-concurrency", type=int, default=2)
    ap.add_argument("--max-pages-per-bucket", type=int, default=50)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset and STATE_PATH.exists():
        STATE_PATH.unlink()
    asyncio.run(
        run(
            page_limit=args.page_limit,
            embed_batch=args.embed_batch,
            bucket_concurrency=args.bucket_concurrency,
            max_pages_per_bucket=args.max_pages_per_bucket,
        )
    )


if __name__ == "__main__":
    main()
