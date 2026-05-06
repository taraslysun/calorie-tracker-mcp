"""User meal templates."""
from __future__ import annotations

from typing import Any

from .session import TablycjaSession


class TemplatesApi:
    def __init__(self, session: TablycjaSession) -> None:
        self._s = session

    async def list(self) -> Any:
        return await self._s.get_json("/user/templates/list")

    async def get(self, template_guid: str) -> Any:
        return await self._s.get_json(f"/user/templates/form/{template_guid}")
