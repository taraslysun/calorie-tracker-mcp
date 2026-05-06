"""Top-level client = composition of submodule APIs over one session."""
from __future__ import annotations

from typing import Any

import httpx

from .activity import ActivityApi
from .catalog import CatalogApi
from .diary import DiaryApi
from .meals import MealsApi
from .profile import ProfileApi
from .session import BASE_URL, TablycjaSession
from .weight import WeightApi


class TablycjaClient:
    """High-level façade. Wraps one TablycjaSession + sub-APIs.

    Construct directly with cookies (post-login session restore) or call
    `await login_google(id_token)` after construction.

    For tests pass `transport=httpx.MockTransport(handler)`.
    """

    def __init__(
        self,
        *,
        cookies: httpx.Cookies | dict[str, str] | None = None,
        login_creds: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
    ) -> None:
        self.session = TablycjaSession(
            base_url=base_url,
            cookies=cookies,
            login_creds=login_creds,
            transport=transport,
            timeout=timeout,
        )
        self.profile = ProfileApi(self.session)
        self.diary = DiaryApi(self.session)
        self.activity = ActivityApi(self.session)
        self.weight = WeightApi(self.session)
        self.catalog = CatalogApi(self.session)
        self.meals = MealsApi(self.session)

    async def login_google(self, id_token: str) -> None:
        await self.session.login_google(id_token)

    async def login_password(self, email: str, password: str):
        return await self.session.login_password(email, password)

    def export_cookies(self) -> dict[str, str]:
        return self.session.export_cookies()

    async def aclose(self) -> None:
        await self.session.aclose()

    async def __aenter__(self) -> "TablycjaClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
