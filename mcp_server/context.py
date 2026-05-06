"""Per-request TablycjaClient resolver.

Two modes (selected by `MCP_AUTH_MODE`, auto-detected if unset):

* `dev`: single user, cookies from env `TABLYCJA_COOKIES`. One process-wide
  client. No auth on transport.

* `oauth`: per-request lookup. The Bearer JWT (validated by
  `BearerAuthMiddleware`) carries the encrypted upstream cookie jar; the
  middleware decrypts it and stores cookies + sub on ContextVars. Tools call
  `get_client()` to obtain a fresh per-request `TablycjaClient`.

Stateless: no database lookup, no shared store.
"""
from __future__ import annotations

import json
import os
from contextvars import ContextVar

from tablycja_client import TablycjaClient

_dev_client: TablycjaClient | None = None

_current_sub: ContextVar[str | None] = ContextVar("_current_sub", default=None)
_current_cookies: ContextVar[dict[str, str] | None] = ContextVar(
    "_current_cookies", default=None
)
_current_creds: ContextVar[dict[str, str] | None] = ContextVar(
    "_current_creds", default=None
)


def _auth_mode() -> str:
    m = os.environ.get("MCP_AUTH_MODE", "").lower().strip()
    if m:
        return m
    return "dev" if os.environ.get("TABLYCJA_COOKIES") else "oauth"


def set_current_sub(sub: str | None) -> None:
    _current_sub.set(sub)


def set_current_cookies(cookies: dict[str, str] | None) -> None:
    _current_cookies.set(cookies)


def set_current_creds(creds: dict[str, str] | None) -> None:
    _current_creds.set(creds)


def _load_dev_cookies() -> dict[str, str]:
    raw = os.environ.get("TABLYCJA_COOKIES", "").strip()
    if not raw:
        raise RuntimeError("TABLYCJA_COOKIES env var not set in dev mode.")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("TABLYCJA_COOKIES must be a JSON object.")
    return {str(k): str(v) for k, v in parsed.items()}


async def get_client() -> TablycjaClient:
    mode = _auth_mode()
    if mode == "dev":
        global _dev_client
        if _dev_client is None:
            _dev_client = TablycjaClient(cookies=_load_dev_cookies())
        return _dev_client

    cookies = _current_cookies.get()
    if not cookies:
        raise RuntimeError("no upstream cookies on this request (auth missing)")
    creds = _current_creds.get()
    return TablycjaClient(cookies=cookies, login_creds=creds)


def set_client(client: TablycjaClient | None) -> None:
    """Test hook — overrides dev singleton."""
    global _dev_client
    _dev_client = client


async def shutdown() -> None:
    global _dev_client
    if _dev_client is not None:
        await _dev_client.aclose()
        _dev_client = None


__all__ = [
    "get_client",
    "set_client",
    "set_current_sub",
    "set_current_cookies",
    "set_current_creds",
    "shutdown",
]
