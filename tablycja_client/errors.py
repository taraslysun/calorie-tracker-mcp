"""Exceptions for tablycja client."""
from __future__ import annotations


class TablycjaError(Exception):
    """Base error."""


class AuthRequiredError(TablycjaError):
    """Session cookie missing or rejected. Caller must re-login."""


class UpstreamError(TablycjaError):
    """Upstream returned non-zero envelope code or unexpected payload."""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
