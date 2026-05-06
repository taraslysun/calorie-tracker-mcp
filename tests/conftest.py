"""Shared test infrastructure: a routable MockTransport with recon-shaped fixtures."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

import httpx
import pytest

Handler = Callable[[httpx.Request], httpx.Response]


def envelope(data: Any = None, *, code: int = 0, message: str | None = None) -> dict[str, Any]:
    return {"requestId": None, "code": code, "message": message, "data": data}


def json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


class Router:
    """Tiny request router for httpx.MockTransport.

    Routes match `(method, path)` exactly. Handlers receive the full request and
    return an httpx.Response. Unmatched routes 404.
    The router records all received requests for assertion.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Handler] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, path: str) -> Callable[[Handler], Handler]:
        def deco(h: Handler) -> Handler:
            self.routes[(method.upper(), path)] = h
            return h

        return deco

    def reply(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.routes[(method.upper(), path)] = lambda _r: json_response(payload, status)

    def transport(self) -> httpx.MockTransport:
        def dispatch(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            handler = self.routes.get((request.method, request.url.path))
            if handler is None:
                return httpx.Response(
                    404,
                    content=f"no route for {request.method} {request.url.path}".encode(),
                )
            return handler(request)

        return httpx.MockTransport(dispatch)

    def calls_to(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method.upper() and r.url.path == path]


@pytest.fixture
def router() -> Router:
    return Router()


@pytest.fixture
def transport(router: Router) -> httpx.MockTransport:
    return router.transport()


# --- recon-shaped fixtures (subset of real responses) ----------------------

@pytest.fixture
def active_user_payload() -> dict[str, Any]:
    return {
        "id": "fffe0599eb5f4405a41109466eb8c968",
        "email": "taraslysun2@gmail.com",
        "sex": "M",
        "birthYear": 2005,
        "lang": "ua",
        "googleId": "100291413510707119917",
        "facebookId": None,
        "appleId": None,
    }


@pytest.fixture
def profile_payload() -> dict[str, Any]:
    return envelope(
        {
            "guid": "fffe0599eb5f4405a41109466eb8c968",
            "email": "taraslysun2@gmail.com",
            "sex": "M",
            "height": 175.0,
            "weight": 68.0,
            "year": 2005,
            "targetWeight": None,
            "drinkRegime": 2.72,
            "amr": 1.375,
            "energyUnit": "kcal",
            "considerActivity": True,
            "ownDiaryTimeRatios": [
                {"position": "1", "title": "Сніданок", "value": None},
                {"position": "3", "title": "Обід", "value": None},
            ],
            "ownNutrients": [
                {"code": "protein", "title": "Білки", "value": None,
                 "computedValue": "135", "active": True},
                {"code": "carbohydrate", "title": "Вуглеводи", "value": None,
                 "computedValue": "207", "active": True},
            ],
        }
    )


@pytest.fixture
def diary_day_payload() -> dict[str, Any]:
    times = [
        {"id": str(i), "title": title, "foodstuff": [], "notes": [],
         "energyTotal": None, "energyTotalUnit": None, "dailyTimeUserRatio": None}
        for i, title in enumerate(
            ["Сніданок", "Перший перекус", "Обід", "Другий перекус", "Вечеря", "Третій перекус"],
            start=1,
        )
    ]
    return envelope(
        {"date": 1777845600000, "energyUnit": "kcal", "times": times}
    )


@pytest.fixture
def summary_payload() -> dict[str, Any]:
    return envelope(
        {
            "date": None,
            "items": [
                {"title": None, "unit": "ккал", "goal": "1,995", "actual": "0",
                 "percent": 0, "actualValue": 0.0, "code": "total"},
                {"title": "Питний режим", "unit": "л", "goal": "2.72", "actual": "0",
                 "percent": 0, "actualValue": 0.0, "code": None},
            ],
            "itemsDynamic": [],
        }
    )


@pytest.fixture
def food_add_form_payload() -> dict[str, Any]:
    return envelope(
        {
            "guid": "73a02350d55a3f8f",
            "title": "Вода питна",
            "url": "stravy/voda-pytna",
            "diaryTimeGuid": "1",
            "diaryTimeOptions": [
                {"id": str(i), "title": t}
                for i, t in enumerate(
                    ["Сніданок", "Перший перекус", "Обід",
                     "Другий перекус", "Вечеря", "Третій перекус"],
                    start=1,
                )
            ],
            "date": "04.05.2026",
            "multiplier": 100,
            "unitGuid": "0000000000000001",
            "unitOptions": [
                {"id": "267851935868959d", "title": "100 г", "multiplier": 100},
                {"id": "0000000000000001", "title": "1 г", "multiplier": 1},
            ],
            "showUnits": True,
            "energyUnit": "kcal",
            "favorite": False,
            "status": 2,
        }
    )


@pytest.fixture
def activity_form_payload() -> dict[str, Any]:
    return envelope(
        {
            "guid": "7545ca65e4ce93a7",
            "title": "Легкий біг",
            "url": "diyalnist/lehkyy-bih",
            "time": 1.0,
            "timeUnit": "hrs",
            "date": "04.05.2026",
            "energy": None,
            "energyUnit": "kcal",
            "favorite": False,
            "timeUser": False,
        }
    )


@pytest.fixture
def autocomplete_payload() -> list[dict[str, Any]]:
    return [
        {
            "clazz": "foodstuff",
            "id": "4363328b663259c5",
            "url": "kurka-tushkovana",
            "title": "Курка тушкована",
            "unit": "г",
            "value": "169",
            "favorite": False,
            "energy": None,
            "energyUnit": "ккал",
            "isLiquid": False,
            "hasImage": True,
        },
        {
            "clazz": "foodstuff",
            "id": "07abc353388d3fa4",
            "url": "kurka-zapechena",
            "title": "Курка запечена",
            "unit": "г",
            "value": "190",
            "favorite": False,
            "energy": None,
            "energyUnit": "ккал",
        },
    ]


__all__: Iterable[str] = []
