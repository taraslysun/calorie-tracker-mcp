"""ASGI middleware: validate Bearer JWT, decrypt embedded upstream cookies,
push them onto a ContextVar so tools can build a per-request TablycjaClient.

Stateless: no DB lookup. The access token contains the encrypted upstream
cookie jar (`upstream_enc` claim). We verify HMAC signature + exp + aud +
scope, then decrypt cookies via Fernet and stash both `sub` and `cookies`
on contextvars in `mcp_server.context`.

On failure → 401 + WWW-Authenticate w/ resource_metadata pointer (RFC 9728).
`/.well-known/*` paths bypass the middleware so the PRM is reachable
unauthenticated.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from auth_server.config import get_settings
from auth_server.tokens import unpack_access

from .context import set_current_cookies, set_current_creds, set_current_sub

REQUIRED_SCOPE = "mcp:tools"


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/.well-known/"):
            await self.app(scope, receive, send)
            return

        cfg = get_settings()
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            await _unauth(send, cfg.mcp_resource)
            return
        token = auth.split(" ", 1)[1].strip()

        try:
            claims = unpack_access(
                token, jwt_secret=cfg.jwt_secret, fernet_key=cfg.fernet_key
            )
        except (ValueError, Exception):
            await _unauth(send, cfg.mcp_resource)
            return

        if claims.get("aud") != cfg.mcp_resource:
            await _unauth(send, cfg.mcp_resource, error="invalid_token")
            return

        scope_str = (claims.get("scope") or "").split()
        if REQUIRED_SCOPE not in scope_str:
            await _unauth(send, cfg.mcp_resource, error="insufficient_scope")
            return

        sub = claims.get("sub")
        cookies = claims.get("cookies")
        if not sub or not isinstance(cookies, dict):
            await _unauth(send, cfg.mcp_resource, error="invalid_token")
            return

        creds = claims.get("creds")  # may be None for cookie-only sessions

        set_current_sub(sub)
        set_current_cookies(cookies)
        set_current_creds(creds if isinstance(creds, dict) else None)
        try:
            await self.app(scope, receive, send)
        finally:
            set_current_sub(None)
            set_current_cookies(None)
            set_current_creds(None)


async def _unauth(send: Send, resource: str, *, error: str = "invalid_token") -> None:
    parts = urlsplit(resource)
    prm_url = f"{parts.scheme}://{parts.netloc}/.well-known/oauth-protected-resource"
    challenge = (
        f'Bearer realm="mcp", error="{error}", '
        f'resource_metadata="{prm_url}"'
    )
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", challenge.encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"error":"' + error.encode() + b'"}',
    })


__all__ = ["BearerAuthMiddleware"]
