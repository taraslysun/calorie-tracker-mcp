"""Stateless token packing for the Authorization Server.

Everything that used to be a database row is now a signed (and optionally
encrypted) JWT. The only server-side state is:

* `AS_JWT_SECRET` — HMAC key for signing every JWT we emit.
* `AS_FERNET_KEY` — Fernet key for encrypting the upstream cookie jar
  inside access / refresh / auth-code tokens.
* In-memory `_used_codes` TTL set — single-use enforcement for auth codes
  (60-second window). Lost on restart, which is fine because codes are
  one-shot and short-lived anyway.

Token kinds and their `kind` claim:

* `kind="client"`     — DCR-issued client_id. Embeds `redirect_uris`.
* `kind="state"`      — opaque blob carried through `/authorize` round-trip.
                        Used both for cookie-mode flow and Google-bind round-trip.
* `kind="auth_code"`  — short-lived (60s) single-use auth code. Embeds
                        `client_id, redirect_uri, sub, scope, resource,
                        code_challenge, code_challenge_method, cookies_enc`.
* `kind="access"`     — bearer token for /mcp. Embeds `cookies_enc`.
* `kind="refresh"`    — long-lived (30d) refresh JWT. Embeds `cookies_enc`.

Cookies are Fernet-encrypted with a separate key so leaking the JWT secret
alone doesn't reveal upstream sessions (and vice versa).
"""
from __future__ import annotations

import time
from typing import Any

from . import crypto

# ---- TTL replay-protection set for auth codes -----------------------------


class TTLSet:
    """Tiny TTL-bounded set for tracking spent JTIs."""

    def __init__(self) -> None:
        self._d: dict[str, float] = {}

    def add(self, key: str, ttl_s: float) -> None:
        self._gc()
        self._d[key] = time.time() + ttl_s

    def __contains__(self, key: str) -> bool:
        self._gc()
        return key in self._d

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, v in self._d.items() if v < now]:
            self._d.pop(k, None)


_used_codes = TTLSet()


def reset_replay_cache() -> None:
    """Test hook."""
    global _used_codes
    _used_codes = TTLSet()


# ---- helpers ---------------------------------------------------------------


def _encrypt_cookies(fernet_key: str, cookies: dict[str, str]) -> str:
    return crypto.encrypt_json(fernet_key, cookies).decode("ascii")


def _decrypt_cookies(fernet_key: str, blob: str) -> dict[str, str]:
    out = crypto.decrypt_json(fernet_key, blob.encode("ascii"))
    if not isinstance(out, dict):
        raise ValueError("cookies blob is not a dict")
    return {str(k): str(v) for k, v in out.items()}


def _encrypt_creds(fernet_key: str, creds: dict[str, str] | None) -> str | None:
    if not creds:
        return None
    return crypto.encrypt_json(fernet_key, creds).decode("ascii")


def _decrypt_creds(fernet_key: str, blob: str | None) -> dict[str, str] | None:
    if not blob:
        return None
    out = crypto.decrypt_json(fernet_key, blob.encode("ascii"))
    if not isinstance(out, dict):
        return None
    return {str(k): str(v) for k, v in out.items()}


def _now() -> int:
    return int(time.time())


# ---- DCR client_id ---------------------------------------------------------


def pack_client_id(
    *,
    jwt_secret: str,
    redirect_uris: list[str],
    client_name: str | None,
) -> str:
    return crypto.jwt_encode(
        {
            "kind": "client",
            "redirect_uris": redirect_uris,
            "client_name": client_name,
            "iat": _now(),
        },
        jwt_secret,
    )


def unpack_client_id(token: str, *, jwt_secret: str) -> dict[str, Any]:
    claims = crypto.jwt_decode(token, jwt_secret)
    if claims.get("kind") != "client":
        raise ValueError("not a client_id token")
    return claims


# ---- /authorize round-trip state ------------------------------------------


def pack_state(
    *,
    jwt_secret: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    resource: str | None,
    code_challenge: str,
    code_challenge_method: str,
    client_state: str | None,
    ttl_s: int = 600,
) -> str:
    return crypto.jwt_encode(
        {
            "kind": "state",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "resource": resource,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "client_state": client_state,
            "iat": _now(),
            "exp": _now() + ttl_s,
            "jti": crypto.random_id(8),
        },
        jwt_secret,
    )


def unpack_state(token: str, *, jwt_secret: str) -> dict[str, Any]:
    claims = crypto.jwt_decode(token, jwt_secret)
    if claims.get("kind") != "state":
        raise ValueError("not a state token")
    return claims


# ---- auth code -------------------------------------------------------------


def pack_auth_code(
    *,
    jwt_secret: str,
    fernet_key: str,
    client_id: str,
    redirect_uri: str,
    sub: str,
    scope: str,
    resource: str | None,
    code_challenge: str,
    code_challenge_method: str,
    cookies: dict[str, str],
    creds: dict[str, str] | None = None,
    ttl_s: int = 60,
) -> str:
    return crypto.jwt_encode(
        {
            "kind": "auth_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "sub": sub,
            "scope": scope,
            "resource": resource,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "upstream_enc": _encrypt_cookies(fernet_key, cookies),
            "creds_enc": _encrypt_creds(fernet_key, creds),
            "iat": _now(),
            "exp": _now() + ttl_s,
            "jti": crypto.random_id(12),
        },
        jwt_secret,
    )


def unpack_auth_code(
    token: str, *, jwt_secret: str, fernet_key: str
) -> dict[str, Any]:
    claims = crypto.jwt_decode(token, jwt_secret)
    if claims.get("kind") != "auth_code":
        raise ValueError("not an auth_code")
    jti = claims.get("jti")
    if not jti:
        raise ValueError("auth_code missing jti")
    if jti in _used_codes:
        raise ValueError("auth_code replayed")
    _used_codes.add(jti, ttl_s=120)
    claims["cookies"] = _decrypt_cookies(fernet_key, claims["upstream_enc"])
    claims["creds"] = _decrypt_creds(fernet_key, claims.get("creds_enc"))
    return claims


# ---- access token ----------------------------------------------------------


def pack_access(
    *,
    jwt_secret: str,
    fernet_key: str,
    issuer: str,
    sub: str,
    aud: str,
    scope: str,
    client_id: str,
    cookies: dict[str, str],
    creds: dict[str, str] | None = None,
    ttl_s: int,
) -> str:
    return crypto.jwt_encode(
        {
            "kind": "access",
            "iss": issuer,
            "aud": aud,
            "sub": sub,
            "scope": scope,
            "client_id": client_id,
            "upstream_enc": _encrypt_cookies(fernet_key, cookies),
            "creds_enc": _encrypt_creds(fernet_key, creds),
            "iat": _now(),
            "exp": _now() + ttl_s,
            "jti": crypto.random_id(8),
        },
        jwt_secret,
    )


def unpack_access(
    token: str, *, jwt_secret: str, fernet_key: str
) -> dict[str, Any]:
    """Verify signature, exp, kind. Returns claims with `cookies` and `creds`
    decrypted. `creds` is None for cookie-bound tokens, populated for
    password-bound tokens."""
    claims = crypto.jwt_decode(token, jwt_secret)
    if claims.get("kind") != "access":
        raise ValueError("not an access token")
    claims["cookies"] = _decrypt_cookies(fernet_key, claims["upstream_enc"])
    claims["creds"] = _decrypt_creds(fernet_key, claims.get("creds_enc"))
    return claims


# ---- refresh token ---------------------------------------------------------


def pack_refresh(
    *,
    jwt_secret: str,
    fernet_key: str,
    sub: str,
    scope: str,
    resource: str | None,
    client_id: str,
    cookies: dict[str, str],
    creds: dict[str, str] | None = None,
    ttl_s: int,
    family_id: str | None = None,
    generation: int = 0,
) -> str:
    return crypto.jwt_encode(
        {
            "kind": "refresh",
            "sub": sub,
            "scope": scope,
            "resource": resource,
            "client_id": client_id,
            "upstream_enc": _encrypt_cookies(fernet_key, cookies),
            "creds_enc": _encrypt_creds(fernet_key, creds),
            "family_id": family_id or crypto.random_id(8),
            "generation": generation,
            "iat": _now(),
            "exp": _now() + ttl_s,
            "jti": crypto.random_id(8),
        },
        jwt_secret,
    )


def unpack_refresh(
    token: str, *, jwt_secret: str, fernet_key: str
) -> dict[str, Any]:
    claims = crypto.jwt_decode(token, jwt_secret)
    if claims.get("kind") != "refresh":
        raise ValueError("not a refresh token")
    claims["cookies"] = _decrypt_cookies(fernet_key, claims["upstream_enc"])
    claims["creds"] = _decrypt_creds(fernet_key, claims.get("creds_enc"))
    return claims


__all__ = [
    "TTLSet",
    "pack_client_id",
    "unpack_client_id",
    "pack_state",
    "unpack_state",
    "pack_auth_code",
    "unpack_auth_code",
    "pack_access",
    "unpack_access",
    "pack_refresh",
    "unpack_refresh",
    "reset_replay_cache",
]
