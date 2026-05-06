"""Combined ASGI app: AS endpoints + MCP resource server in one process.

Run:
    uv run python server.py [--host 0.0.0.0 --port 3000]

Routes:
    /.well-known/oauth-authorization-server   AS metadata
    /.well-known/oauth-protected-resource     PRM (also under /mcp)
    /authorize, /authorize/bind, /register, /token, /introspect   AS
    /mcp/...                                  MCP streamable HTTP (auth required)

In dev (TABLYCJA_COOKIES set), the MCP middleware can be skipped — set
MCP_AUTH_MODE=dev. In oauth mode (default if not dev), every /mcp request
must carry a valid Bearer JWT.
"""
from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI

from starlette.types import ASGIApp, Receive, Scope, Send

from auth_server.app import build_app as build_auth_app
from mcp_server.auth_middleware import BearerAuthMiddleware
from mcp_server.server import build_server as build_mcp


class _McpSlashRewrite:
    """ASGI middleware: rewrite incoming `/mcp` to `/mcp/` BEFORE routing.

    FastAPI's mount only matches `/mcp/...` (with trailing slash) once
    `redirect_slashes=False`. MCP clients hit `/mcp` without slash; instead
    of issuing a 307 (which Cloud Run mishandles, returning http:// urls
    upstream), we rewrite the scope in place.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


def build_combined() -> FastAPI:
    """AS = FastAPI app. Mount the MCP Starlette app at /mcp inside it.

    FastMCP's streamable_http app needs its session manager started in a task
    group; mounted sub-apps don't get their lifespan run, so we wrap it in the
    outer FastAPI lifespan ourselves.
    """
    mcp = build_mcp()
    # Inner FastMCP app must serve at "/" since we mount it at /mcp.
    mcp.settings.streamable_http_path = "/"
    # We're behind Cloud Run's TLS terminator, which validates Host itself.
    # Disable FastMCP's DNS-rebinding protection so it stops rejecting our
    # public hostname with HTTP 421 Misdirected Request.
    from mcp.server.transport_security import TransportSecuritySettings
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )
    mcp_app = mcp.streamable_http_app()
    if os.environ.get("MCP_AUTH_MODE", "").lower() != "dev":
        mcp_app = BearerAuthMiddleware(mcp_app)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = build_auth_app(lifespan=lifespan)
    app.mount("/mcp", mcp_app)
    return app


# Module-level ASGI app for `uvicorn server:app`. Importing this module loads
# `.env` first, then constructs the FastAPI + MCP combined app, then wraps
# the slash-rewrite middleware around it.
app = _McpSlashRewrite(build_combined())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 3000)))
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
