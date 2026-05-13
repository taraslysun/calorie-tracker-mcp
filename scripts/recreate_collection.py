"""Drop + recreate the Qdrant foodstuff collection with the current
embedding dimension. Run after switching embedding models."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tablycja_client import cache as qcache  # noqa: E402
from tablycja_client import embeddings as emb  # noqa: E402


async def main() -> None:
    load_dotenv()
    client = qcache.make_client()
    try:
        name = qcache.collection_name()
        exists = await client.collection_exists(name)
        if exists:
            print(f"deleting collection {name!r}")
            await client.delete_collection(name)
        print(f"creating collection {name!r} dim={emb.DEFAULT_DIM}")
        await qcache.ensure_collection(client, vector_size=emb.DEFAULT_DIM)
        info = await client.get_collection(name)
        print(f"collection ready: points={info.points_count}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
