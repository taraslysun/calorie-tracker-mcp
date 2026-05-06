"""Settings for AS + MCP. Loaded from env / .env once per process."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass(frozen=True)
class Settings:
    # Public URLs (no trailing slash).
    issuer: str = field(default_factory=lambda: _env("AS_ISSUER", "http://localhost:3000"))
    mcp_resource: str = field(default_factory=lambda: _env("MCP_RESOURCE", "http://localhost:3000/mcp"))

    # JWT signing key. Dev default; rotate in prod.
    jwt_secret: str = field(default_factory=lambda: _env(
        "AS_JWT_SECRET", "dev-do-not-use-this-in-production-please-rotate"
    ))
    jwt_alg: str = "HS256"
    access_token_ttl_s: int = 3600
    refresh_token_ttl_s: int = 60 * 60 * 24 * 30
    auth_code_ttl_s: int = 600

    # Storage encryption key (Fernet). Generate via:
    #   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    fernet_key: str = field(default_factory=lambda: _env(
        "AS_FERNET_KEY",
        "ZmRldl9rZXlfZG9fbm90X3VzZV9pbl9wcm9kdWN0aW9uX18zMmJ5dGVzXz0=",
    ))

    # Google OAuth (optional — only needed for `google` bind mode).
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_SECRET"))

    # Bind mode: "cookie" (paste cookie header, dev-friendly) or "google" (Google OAuth).
    bind_mode: str = field(default_factory=lambda: _env("AS_BIND_MODE", "cookie"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook — re-read env on next get_settings()."""
    get_settings.cache_clear()
