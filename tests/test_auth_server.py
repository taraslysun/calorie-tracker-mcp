"""End-to-end OAuth 2.1 flow tests against the stateless build_app.

We test:
- Well-known metadata
- DCR (/register) — issues a self-describing client_id JWT
- /authorize → consent page (cookie bind mode)
- /authorize/bind validates cookie via mocked tablycja, issues code
- /token (auth_code grant) verifies PKCE, issues JWT pair carrying cookies
- /token (refresh_token grant) issues fresh pair, generation increments
- audience + issuer + sub claims correct
- Single-use code replay rejected
- PKCE wrong verifier rejected
- Resource indicator must match
"""
from __future__ import annotations

import base64
import hashlib
import re

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from auth_server import build_app
from auth_server.config import Settings
from auth_server.tokens import reset_replay_cache, unpack_access, unpack_refresh


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
        bind_mode="cookie",
    )


@pytest.fixture
def upstream_router():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/user/active-user" and req.method == "GET":
            return httpx.Response(200, json={
                "id": "user-abc-123",
                "email": "u@example.com",
                "googleId": "g-1",
            })
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def client(settings, upstream_router):
    app = build_app(settings=settings, upstream_transport=upstream_router)
    return TestClient(app)


def _pkce(verifier: str = "verifier-string-123456789012345678901234567890") -> tuple[str, str]:
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _do_auth_to_code(client, settings, *, verifier=None) -> tuple[str, str, str]:
    """DCR + /authorize + /authorize/bind → returns (cid, code, verifier)."""
    reg = client.post("/register", json={
        "client_name": "Test",
        "redirect_uris": ["https://x/cb"],
    }).json()
    cid = reg["client_id"]
    v, ch = _pkce(verifier or "verifier-string-123456789012345678901234567890")
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": "https://x/cb",
        "code_challenge": ch,
        "code_challenge_method": "S256",
        "resource": settings.mcp_resource,
    })
    state = re.search(r'name=state value="([^"]+)"', r.text).group(1)
    r = client.post(
        "/authorize/bind",
        data={"state": state,
              "cookie_header": "JSESSIONID=ABC.kt3; kaloricketabulky_token=DEF"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    code = httpx.URL(r.headers["location"]).params["code"]
    return cid, code, v


def test_as_metadata(client, settings):
    r = client.get("/.well-known/oauth-authorization-server")
    j = r.json()
    assert j["issuer"] == settings.issuer
    assert j["authorization_endpoint"].endswith("/authorize")
    assert "S256" in j["code_challenge_methods_supported"]
    assert "registration_endpoint" in j


def test_protected_resource_metadata(client, settings):
    j = client.get("/.well-known/oauth-protected-resource").json()
    assert j["resource"] == settings.mcp_resource
    assert j["authorization_servers"] == [settings.issuer]


def test_register_dcr_issues_jwt_client_id(client, settings):
    r = client.post("/register", json={
        "client_name": "Claude.ai",
        "redirect_uris": ["https://claude.ai/cb"],
    })
    assert r.status_code == 201
    j = r.json()
    assert "." in j["client_id"], "client_id must be a JWT"
    assert "client_secret" not in j


def test_register_requires_redirect_uris(client):
    assert client.post("/register", json={"client_name": "x"}).status_code == 400


def test_authorize_bad_client_id(client):
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": "not-a-jwt",
        "redirect_uri": "https://x/cb",
        "code_challenge": "ch",
    })
    assert r.status_code == 400


def test_authorize_redirect_not_in_client(client, settings):
    reg = client.post("/register", json={
        "redirect_uris": ["https://x/cb"],
    }).json()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://other/cb",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
    })
    assert r.status_code == 400


def test_full_auth_code_flow(client, settings):
    cid, code, verifier = _do_auth_to_code(client, settings)

    r = client.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": cid,
        "code_verifier": verifier,
    })
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["token_type"] == "Bearer"

    access_claims = unpack_access(
        tok["access_token"],
        jwt_secret=settings.jwt_secret,
        fernet_key=settings.fernet_key,
    )
    assert access_claims["iss"] == settings.issuer
    assert access_claims["aud"] == settings.mcp_resource
    assert access_claims["sub"] == "user-abc-123"
    assert access_claims["scope"] == "mcp:tools"
    assert access_claims["client_id"] == cid
    # Cookies decrypted from inside the token.
    assert access_claims["cookies"] == {
        "JSESSIONID": "ABC.kt3",
        "kaloricketabulky_token": "DEF",
    }


def test_authcode_single_use_replay_rejected(client, settings):
    cid, code, verifier = _do_auth_to_code(client, settings)
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": cid,
        "code_verifier": verifier,
    }
    assert client.post("/token", data=body).status_code == 200
    assert client.post("/token", data=body).status_code == 400


def test_pkce_wrong_verifier(client, settings):
    cid, code, _ = _do_auth_to_code(client, settings)
    r = client.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": cid,
        "code_verifier": "WRONG-VERIFIER-VALUE-VERY-WRONG-ABC123",
    })
    assert r.status_code == 400


def test_refresh_token_flow(client, settings):
    cid, code, verifier = _do_auth_to_code(client, settings)
    tok = client.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": cid,
        "code_verifier": verifier,
    }).json()
    refresh = tok["refresh_token"]

    r = client.post("/token", data={
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    })
    assert r.status_code == 200, r.text
    new_tok = r.json()
    assert new_tok["refresh_token"] != refresh

    new_rt_claims = unpack_refresh(
        new_tok["refresh_token"],
        jwt_secret=settings.jwt_secret,
        fernet_key=settings.fernet_key,
    )
    assert new_rt_claims["sub"] == "user-abc-123"
    assert new_rt_claims["generation"] == 1
    assert new_rt_claims["cookies"]["JSESSIONID"] == "ABC.kt3"


def test_resource_indicator_must_match(client, settings):
    reg = client.post("/register", json={
        "redirect_uris": ["https://x/cb"],
    }).json()
    _, ch = _pkce()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": ch,
        "code_challenge_method": "S256",
        "resource": "https://other/",
    })
    assert r.status_code == 400


def test_bind_rejects_invalid_state(client):
    r = client.post(
        "/authorize/bind",
        data={"state": "not-a-real-jwt", "cookie_header": "X=Y"},
        follow_redirects=False,
    )
    assert r.status_code == 400


# ---- Google bind mode tests -------------------------------------------------


@pytest.fixture
def google_settings():
    return Settings(
        issuer="http://test-as",
        mcp_resource="http://test-as/mcp",
        jwt_secret="test-secret",
        fernet_key=Fernet.generate_key().decode(),
        bind_mode="google",
        google_client_id="google-cid",
        google_client_secret="google-secret",
    )


@pytest.fixture
def google_transport():
    """Mock Google's token endpoint. Always returns a valid id_token."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com" and req.url.path == "/token":
            return httpx.Response(200, json={
                "access_token": "ga.fake",
                "expires_in": 3599,
                "scope": "openid email profile",
                "token_type": "Bearer",
                "id_token": "fake.id.token",
            })
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def upstream_login_router():
    """Mock tablycja: /login/one-tap sets cookies, /user/active-user returns user."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/login/one-tap" and req.method == "POST":
            return httpx.Response(
                200,
                json={"ok": True},
                headers=[
                    ("set-cookie", "JSESSIONID=GoogleBound.kt3; Path=/"),
                    ("set-cookie", "kaloricketabulky_token=tok-google; Path=/"),
                ],
            )
        if req.url.path == "/user/active-user" and req.method == "GET":
            return httpx.Response(200, json={
                "id": "google-user-99",
                "email": "g@example.com",
                "googleId": "111",
            })
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_google_authorize_redirects_to_google(google_settings):
    app = build_app(settings=google_settings)
    c = TestClient(app)
    reg = c.post("/register", json={"redirect_uris": ["https://x/cb"]}).json()
    _, ch = _pkce()
    r = c.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": ch,
        "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=google-cid" in loc
    # state we minted should be carried through.
    assert "state=" in loc


def test_google_callback_full_flow(
    google_settings, google_transport, upstream_login_router
):
    app = build_app(
        settings=google_settings,
        upstream_transport=upstream_login_router,
        google_transport=google_transport,
    )
    c = TestClient(app)

    # 1) DCR + /authorize → grab the AS state from the Google redirect URL.
    reg = c.post("/register", json={"redirect_uris": ["https://x/cb"]}).json()
    verifier, ch = _pkce()
    r = c.get("/authorize", params={
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": "https://x/cb",
        "code_challenge": ch,
        "code_challenge_method": "S256",
        "state": "client-xyz",
        "resource": google_settings.mcp_resource,
    }, follow_redirects=False)
    google_url = httpx.URL(r.headers["location"])
    as_state = google_url.params["state"]

    # 2) Simulate Google redirecting back to /oauth/google/callback.
    r = c.get(
        "/oauth/google/callback",
        params={"code": "google-auth-code", "state": as_state},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    cb_loc = r.headers["location"]
    assert cb_loc.startswith("https://x/cb?")
    qs = httpx.URL(cb_loc).params
    assert qs["state"] == "client-xyz"
    code = qs["code"]

    # 3) /token exchange — verify the cookies captured from upstream were
    # encrypted into the access token.
    tok = c.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://x/cb",
        "client_id": reg["client_id"],
        "code_verifier": verifier,
    })
    assert tok.status_code == 200, tok.text
    access = tok.json()["access_token"]
    claims = unpack_access(
        access,
        jwt_secret=google_settings.jwt_secret,
        fernet_key=google_settings.fernet_key,
    )
    assert claims["sub"] == "google-user-99"
    assert claims["cookies"]["JSESSIONID"] == "GoogleBound.kt3"
    assert claims["cookies"]["kaloricketabulky_token"] == "tok-google"


def test_google_callback_invalid_state(google_settings, google_transport):
    app = build_app(settings=google_settings, google_transport=google_transport)
    c = TestClient(app)
    r = c.get(
        "/oauth/google/callback",
        params={"code": "x", "state": "not-a-real-jwt"},
        follow_redirects=False,
    )
    assert r.status_code == 400
