"""Google OAuth helpers (used in `bind_mode=google`).

Flow:
  1. `build_authorize_url(state)` → redirect user to Google.
  2. Google redirects to our callback w/ `code` + `state`.
  3. `exchange_code(code)` → returns `id_token` (JWT).
  4. Hand `id_token` to upstream `/login/one-tap`.

For dev (`bind_mode=cookie`) this module is unused.
"""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "openid email profile",
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, str]:
    async with httpx.AsyncClient(transport=transport, timeout=15.0) as c:
        resp = await c.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()
