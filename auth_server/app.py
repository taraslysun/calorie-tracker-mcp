"""Stateless FastAPI Authorization Server + Resource-Server metadata.

No database. All previously-persisted artifacts (clients, auth codes, refresh
tokens, encrypted upstream cookies) are now signed/encrypted JWTs that travel
in-band. The only server-side state is:

* `AS_JWT_SECRET` — HMAC signing key.
* `AS_FERNET_KEY` — Fernet key encrypting the upstream cookie jar inside JWTs.
* In-memory replay cache for auth codes (TTL = 120 s).

Endpoints:
  GET  /.well-known/oauth-authorization-server         RFC 8414
  GET  /.well-known/oauth-protected-resource           RFC 9728
  POST /register                                       RFC 7591 (DCR)
  GET  /authorize                                      OAuth 2.1 + PKCE + RFC 8707
  POST /authorize/bind                                 cookie-mode submit
  POST /token                                          auth_code, refresh_token
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import crypto, tokens
from .config import Settings, get_settings
from .templates import consent_cookie_page, consent_password_page, error_page


def build_app(
    *,
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    google_transport: httpx.AsyncBaseTransport | None = None,
    lifespan: Any = None,
) -> FastAPI:
    """Build a FastAPI app. `upstream_transport` and `google_transport` are
    injected by tests so external HTTP calls can be mocked. `lifespan` is
    forwarded to FastAPI so callers can wrap the FastMCP session manager.
    """
    cfg = settings or get_settings()
    # `redirect_slashes=False` so /mcp does not 307 to /mcp/. The MCP client
    # POSTs to whatever URL is registered as the resource, and any 307 (esp.
    # back to http:// behind Cloud Run's TLS terminator) breaks the session.
    app = FastAPI(title="Tablycja MCP AS", lifespan=lifespan, redirect_slashes=False)

    # ---- well-knowns -----------------------------------------------------

    @app.get("/.well-known/oauth-authorization-server")
    def as_metadata() -> JSONResponse:
        return JSONResponse({
            "issuer": cfg.issuer,
            "authorization_endpoint": f"{cfg.issuer}/authorize",
            "token_endpoint": f"{cfg.issuer}/token",
            "registration_endpoint": f"{cfg.issuer}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp:tools"],
        })

    @app.get("/.well-known/oauth-protected-resource")
    def prm() -> JSONResponse:
        return JSONResponse({
            "resource": cfg.mcp_resource,
            "authorization_servers": [cfg.issuer],
            "scopes_supported": ["mcp:tools"],
            "bearer_methods_supported": ["header"],
        })

    # ---- DCR -------------------------------------------------------------

    @app.post("/register")
    async def register(req: Request) -> JSONResponse:
        try:
            body = await req.json()
        except Exception:
            raise HTTPException(400, "invalid JSON")
        redirect_uris = body.get("redirect_uris") or []
        if not isinstance(redirect_uris, list) or not redirect_uris:
            raise HTTPException(400, "redirect_uris required")
        client_name = body.get("client_name")
        client_id = tokens.pack_client_id(
            jwt_secret=cfg.jwt_secret,
            redirect_uris=redirect_uris,
            client_name=client_name,
        )
        return JSONResponse(
            {
                "client_id": client_id,
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    # ---- /authorize (start) ---------------------------------------------

    @app.get("/authorize")
    def authorize(
        response_type: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: str = "mcp:tools",
        state: str | None = None,
        resource: str | None = None,
    ) -> Response:
        if response_type != "code":
            return _error_redirect(redirect_uri, "unsupported_response_type", state)
        if code_challenge_method not in ("S256", "plain"):
            return _error_redirect(redirect_uri, "invalid_request", state)
        try:
            client = tokens.unpack_client_id(client_id, jwt_secret=cfg.jwt_secret)
        except ValueError:
            return HTMLResponse(*error_page("unknown or malformed client_id"))
        if redirect_uri not in client.get("redirect_uris", []):
            return HTMLResponse(*error_page("redirect_uri not registered"))
        if resource is not None and resource != cfg.mcp_resource:
            return HTMLResponse(*error_page(
                f"resource indicator must be {cfg.mcp_resource}"
            ))

        as_state = tokens.pack_state(
            jwt_secret=cfg.jwt_secret,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            resource=resource,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            client_state=state,
        )

        if cfg.bind_mode == "cookie":
            return HTMLResponse(consent_cookie_page(
                state=as_state,
                client_name=client.get("client_name") or "",
                scope=scope,
                resource=resource,
            ))

        if cfg.bind_mode == "password":
            return HTMLResponse(consent_password_page(
                state=as_state,
                client_name=client.get("client_name") or "",
                scope=scope,
                resource=resource,
            ))

        if not cfg.google_client_id:
            return HTMLResponse(*error_page(
                "Google bind mode enabled but GOOGLE_CLIENT_ID not configured"
            ))
        from .google import build_authorize_url
        google_redirect = f"{cfg.issuer}/oauth/google/callback"
        return RedirectResponse(build_authorize_url(
            client_id=cfg.google_client_id,
            redirect_uri=google_redirect,
            state=as_state,
        ))

    # ---- /authorize/bind (cookie-mode submit) ---------------------------

    @app.post("/authorize/bind")
    async def authorize_bind(
        state: str = Form(...),
        cookie_header: str = Form(...),
        email: str | None = Form(None),
    ) -> Response:
        try:
            pending = tokens.unpack_state(state, jwt_secret=cfg.jwt_secret)
        except ValueError:
            return HTMLResponse(*error_page("invalid or expired state"))

        cookies = _parse_cookie_header(cookie_header)
        if not cookies:
            return HTMLResponse(*error_page("no cookies parsed from input"))

        async with httpx.AsyncClient(
            base_url="https://www.tablycjakalorijnosti.com.ua",
            cookies=cookies,
            transport=upstream_transport,
            timeout=10.0,
        ) as cli:
            r = await cli.get("/user/active-user", params={"format": "json"})
        if r.status_code != 200:
            return HTMLResponse(*error_page(
                f"upstream rejected cookie (HTTP {r.status_code})"
            ))
        try:
            user_obj = r.json()
        except Exception:
            return HTMLResponse(*error_page("upstream returned non-JSON"))
        sub = user_obj.get("id") or crypto.random_id(16)

        code = tokens.pack_auth_code(
            jwt_secret=cfg.jwt_secret,
            fernet_key=cfg.fernet_key,
            client_id=pending["client_id"],
            redirect_uri=pending["redirect_uri"],
            sub=sub,
            scope=pending["scope"],
            resource=pending["resource"],
            code_challenge=pending["code_challenge"],
            code_challenge_method=pending["code_challenge_method"],
            cookies=cookies,
        )
        params: dict[str, str] = {"code": code}
        if pending.get("client_state"):
            params["state"] = pending["client_state"]
        sep = "&" if "?" in pending["redirect_uri"] else "?"
        return RedirectResponse(
            f"{pending['redirect_uri']}{sep}{urlencode(params)}",
            status_code=303,
        )

    # ---- /authorize/bind/password (password bind mode) ------------------

    @app.post("/authorize/bind/password")
    async def authorize_bind_password(
        state: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
    ) -> Response:
        try:
            pending = tokens.unpack_state(state, jwt_secret=cfg.jwt_secret)
        except ValueError:
            return HTMLResponse(*error_page("invalid or expired state"))

        # Upstream expects md5(password). Reproduce browser-side hashing.
        import hashlib
        pw_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()

        # Submit credentials directly to upstream. Capture cookies + active user.
        async with httpx.AsyncClient(
            base_url="https://www.tablycjakalorijnosti.com.ua",
            transport=upstream_transport,
            timeout=15.0,
            follow_redirects=False,
            headers={
                "accept": "application/json, text/plain, */*",
                "origin": "https://www.tablycjakalorijnosti.com.ua",
                "referer": "https://www.tablycjakalorijnosti.com.ua/login",
            },
        ) as cli:
            r = await cli.post(
                "/login/create",
                params={"format": "json", "voucher": "false"},
                json={"email": email, "password": pw_md5},
            )
            # Do NOT log r.text — upstream's active-user probe response
            # contains the user's stored password hash, which is sensitive.
            print(f"[bind/password] /login/create status={r.status_code}",
                  flush=True)
            if r.status_code >= 400:
                return HTMLResponse(*error_page(
                    f"upstream login HTTP {r.status_code}"
                ))
            try:
                env = r.json()
            except Exception:
                return HTMLResponse(*error_page("upstream login non-JSON"))
            code = env.get("code", 0) if isinstance(env, dict) else None
            if code != 0:
                msg = env.get("message") if isinstance(env, dict) else "login failed"
                return HTMLResponse(*error_page(
                    f"upstream rejected credentials (code={code}): {msg}"
                ))
            cookies = {
                c.name: c.value
                for c in cli.cookies.jar
                if c.value is not None
            }
            if not cookies:
                return HTMLResponse(*error_page(
                    "upstream did not set any session cookies"
                ))
            probe = await cli.get("/user/active-user", params={"format": "json"})
            # Do NOT log probe.text — contains the stored password hash.
            print(f"[bind/password] active-user probe status={probe.status_code}",
                  flush=True)
            if probe.status_code != 200:
                return HTMLResponse(*error_page(
                    "login succeeded but session probe failed "
                    f"(HTTP {probe.status_code}); upstream may have flagged "
                    "this still as a Google-only account."
                ))
            try:
                user_obj = probe.json()
                if not isinstance(user_obj, dict) or not user_obj.get("id"):
                    raise ValueError("no user id")
            except Exception:
                return HTMLResponse(*error_page(
                    "session probe returned non-JSON or no user id"
                ))
        sub = user_obj["id"]

        auth_code = tokens.pack_auth_code(
            jwt_secret=cfg.jwt_secret,
            fernet_key=cfg.fernet_key,
            client_id=pending["client_id"],
            redirect_uri=pending["redirect_uri"],
            sub=sub,
            scope=pending["scope"],
            resource=pending["resource"],
            code_challenge=pending["code_challenge"],
            code_challenge_method=pending["code_challenge_method"],
            cookies=cookies,
            creds={"email": email, "password": password},
        )
        params: dict[str, str] = {"code": auth_code}
        if pending.get("client_state"):
            params["state"] = pending["client_state"]
        sep = "&" if "?" in pending["redirect_uri"] else "?"
        return RedirectResponse(
            f"{pending['redirect_uri']}{sep}{urlencode(params)}",
            status_code=303,
        )

    # ---- /oauth/google/callback (google bind mode) ----------------------

    @app.get("/oauth/google/callback")
    async def google_callback(code: str, state: str) -> Response:
        """Google OAuth redirect target. Exchanges code → id_token → posts to
        upstream /login/one-tap → captures session cookies → issues our auth
        code → redirects browser back to the original MCP client.
        """
        try:
            pending = tokens.unpack_state(state, jwt_secret=cfg.jwt_secret)
        except ValueError:
            return HTMLResponse(*error_page("invalid or expired state"))

        if not (cfg.google_client_id and cfg.google_client_secret):
            return HTMLResponse(*error_page(
                "Google bind mode requires GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET"
            ))

        from .google import exchange_code
        google_redirect = f"{cfg.issuer}/oauth/google/callback"
        try:
            tok = await exchange_code(
                client_id=cfg.google_client_id,
                client_secret=cfg.google_client_secret,
                redirect_uri=google_redirect,
                code=code,
                transport=google_transport,
            )
        except httpx.HTTPError as e:
            return HTMLResponse(*error_page(f"Google token exchange failed: {e}"))
        id_token = tok.get("id_token")
        if not id_token:
            return HTMLResponse(*error_page("Google response missing id_token"))

        # Hand id_token to upstream /login/one-tap; capture session cookies from jar.
        # Do NOT follow redirects — the auth probe must hit /user/active-user
        # directly so we can detect a non-authenticated 302 → /login.
        async with httpx.AsyncClient(
            base_url="https://www.tablycjakalorijnosti.com.ua",
            transport=upstream_transport,
            timeout=15.0,
            follow_redirects=False,
        ) as cli:
            r = await cli.post(
                "/login/one-tap",
                params={"format": "json"},
                json={"token": id_token},
                headers={
                    "origin": "https://www.tablycjakalorijnosti.com.ua",
                    "referer": "https://www.tablycjakalorijnosti.com.ua/login",
                },
            )
            if r.status_code >= 400:
                return HTMLResponse(*error_page(
                    f"upstream /login/one-tap rejected (HTTP {r.status_code}): "
                    f"{r.text[:300]}"
                ))
            # Upstream returns the standard envelope. code != 0 ⇒ login failed
            # even though HTTP status is 200.
            try:
                env = r.json()
            except Exception:
                env = {}
            env_code = env.get("code") if isinstance(env, dict) else None
            if env_code not in (0, None):
                return HTMLResponse(*error_page(
                    f"upstream rejected Google sign-in (envelope code={env_code}): "
                    f"{env.get('message') or r.text[:200]}"
                ))
            cookies = {
                c.name: c.value
                for c in cli.cookies.jar
                if c.value is not None
            }
            if not cookies:
                return HTMLResponse(*error_page(
                    "upstream did not set any session cookies"
                ))
            # Probe must succeed with a 200 + JSON envelope; otherwise the
            # session isn't actually authenticated (e.g. cookies set but
            # id_token aud mismatched and upstream silently failed login).
            probe = await cli.get("/user/active-user", params={"format": "json"})
            if probe.status_code != 200:
                return HTMLResponse(*error_page(
                    "Google sign-in did not establish a session "
                    f"(active-user probe HTTP {probe.status_code}). Likely cause: "
                    "upstream pins token audience to its own Google client and "
                    "rejects ours. Use cookie bind mode instead."
                ))
            try:
                user_obj = probe.json()
                if not isinstance(user_obj, dict) or not user_obj.get("id"):
                    raise ValueError("no user id in probe response")
            except Exception as e:
                return HTMLResponse(*error_page(
                    f"upstream session probe returned non-JSON or no user id: {e}"
                ))
        sub = user_obj["id"]

        auth_code = tokens.pack_auth_code(
            jwt_secret=cfg.jwt_secret,
            fernet_key=cfg.fernet_key,
            client_id=pending["client_id"],
            redirect_uri=pending["redirect_uri"],
            sub=sub,
            scope=pending["scope"],
            resource=pending["resource"],
            code_challenge=pending["code_challenge"],
            code_challenge_method=pending["code_challenge_method"],
            cookies=cookies,
        )
        params: dict[str, str] = {"code": auth_code}
        if pending.get("client_state"):
            params["state"] = pending["client_state"]
        sep = "&" if "?" in pending["redirect_uri"] else "?"
        return RedirectResponse(
            f"{pending['redirect_uri']}{sep}{urlencode(params)}",
            status_code=303,
        )

    # ---- /token ---------------------------------------------------------

    @app.post("/token")
    async def token(
        grant_type: str = Form(...),
        code: str | None = Form(None),
        redirect_uri: str | None = Form(None),
        client_id: str | None = Form(None),
        code_verifier: str | None = Form(None),
        refresh_token: str | None = Form(None),
        resource: str | None = Form(None),
    ) -> JSONResponse:
        if grant_type == "authorization_code":
            if not (code and redirect_uri and client_id and code_verifier):
                raise HTTPException(400, "missing parameter")
            try:
                row = tokens.unpack_auth_code(
                    code, jwt_secret=cfg.jwt_secret, fernet_key=cfg.fernet_key
                )
            except ValueError:
                raise HTTPException(400, "invalid_grant")
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                raise HTTPException(400, "invalid_grant")
            if not crypto.verify_pkce(
                code_verifier, row["code_challenge"], row["code_challenge_method"]
            ):
                raise HTTPException(400, "invalid_grant")
            return _issue_tokens(
                cfg,
                sub=row["sub"],
                client_id=client_id,
                scope=row["scope"],
                resource=row["resource"],
                cookies=row["cookies"],
                creds=row.get("creds"),
            )

        if grant_type == "refresh_token":
            if not refresh_token:
                raise HTTPException(400, "missing refresh_token")
            try:
                rt = tokens.unpack_refresh(
                    refresh_token,
                    jwt_secret=cfg.jwt_secret,
                    fernet_key=cfg.fernet_key,
                )
            except ValueError:
                raise HTTPException(400, "invalid_grant")
            return _issue_tokens(
                cfg,
                sub=rt["sub"],
                client_id=rt["client_id"],
                scope=rt["scope"],
                resource=rt["resource"],
                cookies=rt["cookies"],
                creds=rt.get("creds"),
                family_id=rt.get("family_id"),
                generation=int(rt.get("generation", 0)) + 1,
            )

        raise HTTPException(400, f"unsupported grant_type {grant_type}")

    return app


# ---- helpers ---------------------------------------------------------------


def _issue_tokens(
    cfg: Settings,
    *,
    sub: str,
    client_id: str,
    scope: str,
    resource: str | None,
    cookies: dict[str, str],
    creds: dict[str, str] | None = None,
    family_id: str | None = None,
    generation: int = 0,
) -> JSONResponse:
    access = tokens.pack_access(
        jwt_secret=cfg.jwt_secret,
        fernet_key=cfg.fernet_key,
        issuer=cfg.issuer,
        sub=sub,
        aud=resource or cfg.mcp_resource,
        scope=scope,
        client_id=client_id,
        cookies=cookies,
        creds=creds,
        ttl_s=cfg.access_token_ttl_s,
    )
    refresh = tokens.pack_refresh(
        jwt_secret=cfg.jwt_secret,
        fernet_key=cfg.fernet_key,
        sub=sub,
        scope=scope,
        resource=resource,
        client_id=client_id,
        cookies=cookies,
        creds=creds,
        ttl_s=cfg.refresh_token_ttl_s,
        family_id=family_id,
        generation=generation,
    )
    return JSONResponse({
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": cfg.access_token_ttl_s,
        "refresh_token": refresh,
        "scope": scope,
    })


def _parse_cookie_header(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in raw.strip().split(";"):
        if "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if name and value:
            out[name] = value
    return out


def _error_redirect(redirect_uri: str, error: str, state: str | None) -> RedirectResponse:
    params: dict[str, str] = {"error": error}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=303)
