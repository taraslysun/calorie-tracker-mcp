"""HTTP session wrapper.

- Holds cookie jar (the only credential after login).
- Wraps `httpx.AsyncClient` with shared headers, base URL, format=json.
- Parses upstream envelope, raises typed errors.
- Login: Google one-tap (id_token) OR email/password via /login/create.
- Auto-relogin: when cached JSESSIONID expires (302 → /login), if email/password
  credentials are stored on the session, transparently re-login + retry once.

Note on password hashing: upstream's web client sends the password as
`md5(plaintext)` to /login/create — verified in recon. We reproduce that
exact transformation here. The plaintext password is never transmitted.
"""
from __future__ import annotations

import hashlib
from typing import Any

import httpx

from .errors import AuthRequiredError, UpstreamError

BASE_URL = "https://www.tablycjakalorijnosti.com.ua"

_DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": BASE_URL,
    "referer": f"{BASE_URL}/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "accept-language": "uk-UA,uk;q=0.9,en;q=0.8",
}


class TablycjaSession:
    """Async wrapper around httpx.AsyncClient with envelope parsing.

    Pass a pre-built `transport` (e.g. `httpx.MockTransport`) for tests.
    Pass `cookies` to restore a prior session. Pass `login_creds={'email','password'}`
    to enable automatic re-login on session expiry.
    """

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        cookies: httpx.Cookies | dict[str, str] | None = None,
        login_creds: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=_DEFAULT_HEADERS,
            cookies=cookies,
            transport=transport,
            timeout=timeout,
            # Do NOT follow redirects. Upstream returns 302 → /login when the
            # session cookie is invalid; following the redirect would mask the
            # auth failure as an HTML 200 and break JSON parsing downstream.
            follow_redirects=False,
        )
        self._login_creds = login_creds
        # Reentrancy guard so a re-login cycle never loops.
        self._relogin_in_flight = False

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies

    def export_cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self._client.cookies.jar if c.value is not None}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "TablycjaSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # -- core --------------------------------------------------------------

    async def login_google(self, id_token: str) -> None:
        """POST a Google ID JWT to /login/one-tap. Server sets session cookie."""
        resp = await self._client.post(
            "/login/one-tap",
            params={"format": "json"},
            json={"token": id_token},
        )
        if resp.status_code in (401, 403):
            raise AuthRequiredError("Login rejected by upstream")
        if resp.status_code >= 400:
            raise UpstreamError(
                f"login failed: HTTP {resp.status_code}",
                status=resp.status_code,
            )

    async def login_password(self, email: str, password: str) -> dict[str, Any]:
        """POST email + md5(password) to /login/create. Captures session cookies
        in the jar. Returns the upstream `data` envelope. Raises
        `AuthRequiredError` on bad credentials, including Google-only-account
        rejection.

        Upstream's own web client md5-hashes the password before sending; we
        do the same. Detect already-hashed values (32 hex chars) and pass
        through unchanged so callers can supply either form.
        """
        pw = password
        if not (len(pw) == 32 and all(c in "0123456789abcdef" for c in pw.lower())):
            pw = hashlib.md5(password.encode("utf-8")).hexdigest()

        resp = await self._client.post(
            "/login/create",
            params={"format": "json", "voucher": "false"},
            json={"email": email, "password": pw},
        )
        if resp.status_code >= 400:
            raise UpstreamError(
                f"login_password HTTP {resp.status_code}",
                status=resp.status_code,
            )
        try:
            env = resp.json()
        except ValueError as e:
            raise UpstreamError(f"non-JSON login response: {e}") from e
        if not isinstance(env, dict):
            raise UpstreamError("unexpected login response shape")
        code = env.get("code", 0)
        if code != 0:
            # Code 5 = "this is a Google account, use Google sign-in";
            # other non-zero codes = bad credentials etc. Surface upstream
            # message verbatim.
            raise AuthRequiredError(env.get("message") or f"login_password code={code}")
        return env.get("data") or {}

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        async def go() -> httpx.Response:
            return await self._client.get(path, params={"format": "json", **(params or {})})
        return self._unwrap(await self._with_relogin(go))

    async def post_json(
        self,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        async def go() -> httpx.Response:
            return await self._client.post(
                path,
                params={"format": "json", **(params or {})},
                json=json_body,
            )
        return self._unwrap(await self._with_relogin(go))

    # -- helpers -----------------------------------------------------------

    async def _with_relogin(self, req):
        """Execute `req()` once. If response is 3xx and creds are configured,
        call /login/create to refresh JSESSIONID, then retry `req()` exactly
        once. Used to transparently survive upstream session timeouts.
        """
        resp = await req()
        if (
            300 <= resp.status_code < 400
            and self._login_creds
            and not self._relogin_in_flight
        ):
            self._relogin_in_flight = True
            try:
                await self.login_password(**self._login_creds)
                resp = await req()
            except (AuthRequiredError, UpstreamError):
                # Re-login failed — surface the original 3xx via _unwrap.
                pass
            finally:
                self._relogin_in_flight = False
        return resp

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        if resp.status_code in (401, 403):
            raise AuthRequiredError(
                f"Upstream HTTP {resp.status_code} on {resp.request.url.path}"
            )
        # 3xx redirect almost always means session lapsed and upstream is
        # redirecting us to /login. Treat as auth-required.
        if 300 <= resp.status_code < 400:
            raise AuthRequiredError(
                f"Upstream redirect ({resp.status_code} → "
                f"{resp.headers.get('location', '?')}); session expired. "
                f"Re-bind the connector."
            )
        if resp.status_code >= 500:
            raise UpstreamError(
                f"Upstream HTTP {resp.status_code}",
                status=resp.status_code,
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise UpstreamError(f"non-JSON response: {e}", status=resp.status_code) from e

        # Some endpoints (e.g. /autocomplete/*) return a bare list instead of envelope.
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            raise UpstreamError(f"unexpected payload shape: {type(payload).__name__}")

        # Envelope shape: {requestId, code, message, data}
        if "code" in payload and "data" in payload:
            code = payload.get("code", 0)
            if code != 0:
                raise UpstreamError(
                    payload.get("message") or f"upstream code {code}",
                    code=code,
                    status=resp.status_code,
                )
            return payload.get("data")

        # Some endpoints (e.g. /foodstuff/detail/form) return raw object without `code`.
        return payload
