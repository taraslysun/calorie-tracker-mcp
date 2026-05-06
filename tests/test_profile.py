from __future__ import annotations

import pytest

from tablycja_client import TablycjaClient


@pytest.mark.asyncio
async def test_active_user(router, active_user_payload):
    router.reply("GET", "/user/active-user", active_user_payload)
    async with TablycjaClient(transport=router.transport()) as c:
        u = await c.profile.active_user()
    assert u.id == "fffe0599eb5f4405a41109466eb8c968"
    assert u.email == "taraslysun2@gmail.com"
    assert u.googleId == "100291413510707119917"


@pytest.mark.asyncio
async def test_get_profile(router, profile_payload):
    router.reply("GET", "/user/settings/profile/form", profile_payload)
    async with TablycjaClient(transport=router.transport()) as c:
        p = await c.profile.get()
    assert p.height == 175.0
    assert p.weight == 68.0
    assert p.amr == 1.375
    assert len(p.ownNutrients) == 2
    assert p.ownNutrients[0].code == "protein"
