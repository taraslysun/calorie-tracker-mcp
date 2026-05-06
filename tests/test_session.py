"""Session: envelope unwrap, error mapping, login cookie capture."""
from __future__ import annotations

import httpx
import pytest

from tablycja_client import AuthRequiredError, TablycjaClient, UpstreamError
from tablycja_client.session import TablycjaSession


@pytest.mark.asyncio
async def test_envelope_unwrap_returns_data(router):
    router.reply("GET", "/anything", {"requestId": None, "code": 0, "message": None,
                                       "data": {"hello": "world"}})
    async with TablycjaSession(transport=router.transport()) as s:
        data = await s.get_json("/anything")
    assert data == {"hello": "world"}


@pytest.mark.asyncio
async def test_envelope_nonzero_code_raises_upstream(router):
    router.reply("GET", "/bad", {"code": 7, "message": "broken", "data": None})
    async with TablycjaSession(transport=router.transport()) as s:
        with pytest.raises(UpstreamError) as ei:
            await s.get_json("/bad")
    assert ei.value.code == 7
    assert "broken" in str(ei.value)


@pytest.mark.asyncio
async def test_401_raises_auth_required(router):
    router.routes[("GET", "/p")] = lambda _r: httpx.Response(401, content=b"")
    async with TablycjaSession(transport=router.transport()) as s:
        with pytest.raises(AuthRequiredError):
            await s.get_json("/p")


@pytest.mark.asyncio
async def test_bare_list_response_passes_through(router):
    router.reply("GET", "/autocomplete/foodstuff-activity-meal", [{"a": 1}, {"a": 2}])
    async with TablycjaSession(transport=router.transport()) as s:
        out = await s.get_json("/autocomplete/foodstuff-activity-meal",
                               params={"query": "x"})
    assert out == [{"a": 1}, {"a": 2}]


@pytest.mark.asyncio
async def test_format_json_param_added(router):
    received: dict[str, str] = {}

    @router.on("GET", "/probe")
    def _h(req: httpx.Request) -> httpx.Response:
        received.update(dict(req.url.params))
        return httpx.Response(200, json={"code": 0, "data": None})

    async with TablycjaSession(transport=router.transport()) as s:
        await s.get_json("/probe", params={"x": "1"})
    assert received == {"format": "json", "x": "1"}


@pytest.mark.asyncio
async def test_login_google_sends_id_token_and_captures_cookie(router):
    @router.on("POST", "/login/one-tap")
    def _h(req: httpx.Request) -> httpx.Response:
        body = req.read().decode()
        assert '"token":"jwt-here"' in body
        return httpx.Response(
            200,
            content=b'{}',
            headers={
                "content-type": "application/json",
                "set-cookie": "PHPSESSID=abc123; Path=/",
            },
        )

    client = TablycjaClient(transport=router.transport())
    try:
        await client.login_google("jwt-here")
        assert client.export_cookies().get("PHPSESSID") == "abc123"
    finally:
        await client.aclose()
