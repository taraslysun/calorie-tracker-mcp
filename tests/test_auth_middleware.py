"""ASGI Bearer middleware tests (stateless tokens)."""
from __future__ import annotations

from cryptography.fernet import Fernet
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from auth_server.config import Settings
from auth_server.tokens import pack_access
from mcp_server.auth_middleware import BearerAuthMiddleware
from mcp_server.context import _current_cookies, _current_sub  # type: ignore


def _ok(request):
    return JSONResponse({
        "sub": _current_sub.get(),
        "cookies": _current_cookies.get(),
    })


def _build(monkeypatch) -> tuple[TestClient, Settings]:
    s = Settings(
        issuer="http://as",
        mcp_resource="http://mcp/mcp",
        jwt_secret="ms",
        fernet_key=Fernet.generate_key().decode(),
    )
    from auth_server import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "get_settings", lambda: s)
    from mcp_server import auth_middleware as am
    monkeypatch.setattr(am, "get_settings", lambda: s)

    inner = Starlette(routes=[Route("/probe", _ok)])
    return TestClient(BearerAuthMiddleware(inner)), s


def _make_token(s: Settings, *, sub="u1", aud=None, scope="mcp:tools",
                cookies=None, ttl=3600) -> str:
    return pack_access(
        jwt_secret=s.jwt_secret,
        fernet_key=s.fernet_key,
        issuer=s.issuer,
        sub=sub,
        aud=aud or s.mcp_resource,
        scope=scope,
        client_id="c1",
        cookies=cookies or {"JSESSIONID": "abc", "kaloricketabulky_token": "def"},
        ttl_s=ttl,
    )


def test_no_auth_header_returns_401_with_prm_pointer(monkeypatch):
    c, _ = _build(monkeypatch)
    r = c.get("/probe")
    assert r.status_code == 401
    assert "Bearer" in r.headers["www-authenticate"]
    assert "resource_metadata" in r.headers["www-authenticate"]


def test_well_known_bypasses_auth(monkeypatch):
    c, _ = _build(monkeypatch)
    r = c.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 404  # passes through to inner (no route)


def test_bad_token(monkeypatch):
    c, _ = _build(monkeypatch)
    r = c.get("/probe", headers={"Authorization": "Bearer junk.token.here"})
    assert r.status_code == 401


def test_wrong_audience(monkeypatch):
    c, s = _build(monkeypatch)
    t = _make_token(s, aud="http://other/")
    r = c.get("/probe", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401


def test_missing_scope(monkeypatch):
    c, s = _build(monkeypatch)
    t = _make_token(s, scope="other:scope")
    r = c.get("/probe", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401


def test_expired(monkeypatch):
    c, s = _build(monkeypatch)
    t = _make_token(s, ttl=-10)
    r = c.get("/probe", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401


def test_valid_token_sets_sub_and_cookies(monkeypatch):
    c, s = _build(monkeypatch)
    t = _make_token(s, sub="user-xyz", cookies={"JSESSIONID": "S1.kt3"})
    r = c.get("/probe", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200
    j = r.json()
    assert j["sub"] == "user-xyz"
    assert j["cookies"] == {"JSESSIONID": "S1.kt3"}


def test_tampered_signature_rejected(monkeypatch):
    """Sign w/ different secret → signature won't validate."""
    c, s = _build(monkeypatch)
    bad_s = Settings(
        issuer=s.issuer, mcp_resource=s.mcp_resource,
        jwt_secret="different-secret", fernet_key=s.fernet_key,
    )
    t = _make_token(bad_s)
    r = c.get("/probe", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401
