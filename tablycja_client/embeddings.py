"""Embedding model wrapper.

Lazy-loaded singleton `intfloat/multilingual-e5-small` (override via
`EMBED_MODEL` env). Auto-picks the best torch device available:
CUDA > MPS (Apple Silicon) > CPU.

E5-family models require role prefixes — `query: <text>` for search
queries and `passage: <text>` for stored documents. We attach them
inside `embed_passages` / `embed_query` so callers do not need to
remember. When `EMBED_MODEL` is overridden to a non-E5 model the
prefixing is a no-op for E5 but harmless for other models — they will
just embed the prefix as part of the text. If switching to a non-E5
model, also set `EMBED_NO_PREFIX=1` so prefixes are skipped.

The model is only imported when first used, so the runtime path that
never calls `embed_*` (e.g. tests of unrelated tools) doesn't pay the
import cost.
"""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: "SentenceTransformer | None" = None
_lock = threading.Lock()

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_DIM = 384


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_model() -> "SentenceTransformer":
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            name = os.environ.get("EMBED_MODEL", DEFAULT_MODEL)
            device = os.environ.get("EMBED_DEVICE") or _pick_device()
            _model = SentenceTransformer(name, device=device)
    return _model


def _use_prefix() -> bool:
    if os.environ.get("EMBED_NO_PREFIX"):
        return False
    name = os.environ.get("EMBED_MODEL", DEFAULT_MODEL)
    return "e5" in name.lower()


def embed(texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
    """Encode `texts` to normalized vectors (cosine-ready).

    No prefix is applied — use `embed_passages` / `embed_query` for E5
    models. Kept for back-compat with older ingest scripts.
    """
    if not texts:
        return []
    model = get_model()
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vecs.tolist()


def embed_passages(texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
    """Encode stored documents. Adds `passage: ` prefix for E5 models."""
    if not texts:
        return []
    prepped = [f"passage: {t}" for t in texts] if _use_prefix() else texts
    return embed(prepped, batch_size=batch_size)


def embed_query(text: str) -> list[float]:
    """Encode a single query. Adds `query: ` prefix for E5 models."""
    prepped = f"query: {text}" if _use_prefix() else text
    return embed([prepped])[0]


def embed_one(text: str) -> list[float]:
    """Back-compat alias. Treats input as a query (prefixes for E5)."""
    return embed_query(text)


__all__ = [
    "embed",
    "embed_passages",
    "embed_query",
    "embed_one",
    "get_model",
    "DEFAULT_MODEL",
    "DEFAULT_DIM",
]
