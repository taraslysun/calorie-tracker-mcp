"""Crypto primitives: Fernet for cookie storage, JWT for tokens, PKCE verify."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def random_id(n_bytes: int = 16) -> str:
    return secrets.token_urlsafe(n_bytes)


def random_secret(n_bytes: int = 32) -> str:
    return secrets.token_urlsafe(n_bytes)


# ---------- Fernet for cookie jar storage --------------------------------

def fernet(key: str) -> Fernet:
    return Fernet(key.encode("utf-8"))


def encrypt_json(key: str, payload: Any) -> bytes:
    return fernet(key).encrypt(json.dumps(payload).encode("utf-8"))


def decrypt_json(key: str, blob: bytes) -> Any:
    try:
        return json.loads(fernet(key).decrypt(blob).decode("utf-8"))
    except InvalidToken as e:
        raise ValueError("decryption failed") from e


# ---------- JWT (HS256) --------------------------------------------------

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b}.{payload_b}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b}.{payload_b}.{_b64url(sig)}"


def jwt_decode(token: str, secret: str) -> dict[str, Any]:
    """Verify signature + exp. Raise ValueError on any failure."""
    try:
        header_b, payload_b, sig_b = token.split(".")
    except ValueError as e:
        raise ValueError("malformed JWT") from e
    signing_input = f"{header_b}.{payload_b}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_b)):
        raise ValueError("bad signature")
    payload = json.loads(_b64url_decode(payload_b))
    exp = payload.get("exp")
    if exp is not None and time.time() >= float(exp):
        raise ValueError("expired")
    return payload


# ---------- PKCE ---------------------------------------------------------

def verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method == "plain":
        return hmac.compare_digest(verifier, challenge)
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        derived = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(derived, challenge)
    return False


# ---------- Misc ---------------------------------------------------------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def now_s() -> int:
    return int(time.time())


__all__ = [
    "random_id",
    "random_secret",
    "encrypt_json",
    "decrypt_json",
    "jwt_encode",
    "jwt_decode",
    "verify_pkce",
    "hash_token",
    "constant_time_eq",
    "now_s",
]


# Generate a dev fernet key on import if user hasn't set one (helper).
def ensure_fernet_key(key: str) -> str:
    """If key is empty or invalid, return a fresh one. Otherwise echo back."""
    try:
        Fernet(key.encode())
        return key
    except Exception:
        return Fernet.generate_key().decode()


def _gen_dev_fernet_env() -> str:  # pragma: no cover
    return Fernet.generate_key().decode()


# Avoid F401 on os/secrets if linter complains (used by callers via this module).
_ = (os, secrets)
