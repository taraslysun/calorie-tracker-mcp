"""Password-bind mode + auto-relogin on session expiry."""
from __future__ import annotations

import json
import re

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from auth_server import build_app
from auth_server.config import Settings
from auth_server.tokens import reset_replay_cache, unpack_access
from tablycja_client import TablycjaClient


@pytest.fixture(autouse=True)
def _clear_replay():
    reset_replay_cache()
    yield
    reset_replay_cache()


@pytest.fixture
def settings():
    return Settings(
        issuer="http://test-as",
        mcp_resource="http://test-as/mcp",
        jwt_secret="test-secret",
        fernet_key=Fernet.generate_key().decode(),
        bind_mode="password",
    )


@pytest.fixture
def login_router():
    """Mock upstream: /login/create accepts (good@x, hunter2)."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/login/create" and req.method == "POST":
            body = json.loads(req.read().decode() or "{}")
            import hashlib
            md5_hunter2 = hashlib.md5(b"hunter2").hexdigest()
            if body.get("email") == "good@x" and body.get("password") == md5_hunter2:
                return httpx.Response(
                    200,
                    json={"code": 0, "data": {"id": "u1"}, "message": None},
                    headers=[
                        ("set-cookie", "JSESSIONID=PASSBOUND.kt3; Path=/"),
                    ],
                )
            return httpx.Response(200, json={"code": 1, "message": "bad creds"})
        if req.url.path == "/user/active-user" and req.method == "GET":
            cookies = req.headers.get("cookie", "")
            if "JSESSIONID=PASSBOUND" in cookies:
                return httpx.Response(200, json={
                    "id": "u1", "email": "good@x", "googleId": None,
                })
            return httpx.Response(302)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def client(settings, login_router):
    app = build_app(settings=settings, upstream_transport=login_router)
    return TestClient(app)


def test_consent_renders_password_form(client, settings):
    reg = client.post("/register", json={"redirect_uris": ["https://x/cb"]}).json()
    import base64, hashlib
    verifier = "v-" + "x" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    assert r.status_code == 200
    assert 'name=email' in r.text
    assert 'name=password' in r.text
    assert "/authorize/bind/password" in r.text


def test_password_bind_full_flow(client, settings):
    reg = client.post("/register", json={"redirect_uris": ["https://x/cb"]}).json()
    import base64, hashlib
    verifier = "vfy-" + "y" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    state = re.search(r'name=state value="([^"]+)"', r.text).group(1)

    r = client.post("/authorize/bind/password",
                    data={"state": state, "email": "good@x", "password": "hunter2"},
                    follow_redirects=False)
    assert r.status_code == 303
    code = httpx.URL(r.headers["location"]).params["code"]

    tok = client.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": reg["client_id"],
        "code_verifier": verifier,
    }).json()
    claims = unpack_access(
        tok["access_token"],
        jwt_secret=settings.jwt_secret,
        fernet_key=settings.fernet_key,
    )
    assert claims["sub"] == "u1"
    assert claims["cookies"]["JSESSIONID"] == "PASSBOUND.kt3"
    # creds embedded for auto-relogin (we store the original plaintext so the
    # session client can md5 anew on each re-login).
    assert claims["creds"] == {"email": "good@x", "password": "hunter2"}


def test_password_bind_rejects_bad_creds(client):
    reg = client.post("/register", json={"redirect_uris": ["https://x/cb"]}).json()
    import base64, hashlib
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    state = re.search(r'name=state value="([^"]+)"', r.text).group(1)
    r = client.post("/authorize/bind/password",
                    data={"state": state, "email": "x@x", "password": "wrong"},
                    follow_redirects=False)
    assert r.status_code == 400


# ---- session-level auto-relogin tests ---------------------------------


@pytest.mark.asyncio
async def test_session_auto_relogin_on_302(router):
    """Stale JSESSIONID → 302 → session re-logins via creds → retry succeeds."""
    state = {"step": 0}

    @router.on("GET", "/user/active-user")
    def _au(req: httpx.Request):
        cookies = req.headers.get("cookie", "")
        if "JSESSIONID=FRESH" in cookies:
            return httpx.Response(200, json={"id": "u1", "email": "x@y"})
        return httpx.Response(302, headers={"location": "/login"})

    @router.on("POST", "/login/create")
    def _login(req: httpx.Request):
        state["step"] += 1
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "u1"}, "message": None},
            headers=[("set-cookie", "JSESSIONID=FRESH.kt3; Path=/")],
        )

    async with TablycjaClient(
        cookies={"JSESSIONID": "STALE"},
        login_creds={"email": "x@y", "password": "p"},
        transport=router.transport(),
    ) as c:
        u = await c.profile.active_user()
    assert u.id == "u1"
    assert state["step"] == 1  # exactly one re-login attempted


@pytest.mark.asyncio
async def test_session_no_relogin_loop(router):
    """Stale cookies + bad creds = single retry, then surface AuthRequired."""
    from tablycja_client.errors import AuthRequiredError
    attempts = {"login": 0, "active": 0}

    @router.on("GET", "/user/active-user")
    def _au(req):
        attempts["active"] += 1
        return httpx.Response(302, headers={"location": "/login"})

    @router.on("POST", "/login/create")
    def _login(req):
        attempts["login"] += 1
        return httpx.Response(200, json={"code": 1, "message": "bad creds"})

    async with TablycjaClient(
        cookies={"JSESSIONID": "STALE"},
        login_creds={"email": "x@y", "password": "wrong"},
        transport=router.transport(),
    ) as c:
        with pytest.raises(AuthRequiredError):
            await c.profile.active_user()
    # 1 initial GET + 1 attempted login + 0 retries (login itself failed)
    assert attempts["login"] == 1
    assert attempts["active"] == 1
