"""Pydantic models for upstream payloads. Permissive — extra fields ignored."""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


def fmt_date(d: date_cls | str) -> str:
    """Upstream uses DD.MM.YYYY in URL paths and POST bodies."""
    if isinstance(d, str):
        return d
    return d.strftime("%d.%m.%Y")


class Envelope(BaseModel, Generic[T]):
    """Standard upstream response wrapper."""

    model_config = ConfigDict(extra="ignore")

    requestId: str | None = None
    code: int = 0
    message: str | None = None
    data: T | None = None


class _Permissive(BaseModel):
    model_config = ConfigDict(extra="allow")


class ActiveUser(_Permissive):
    id: str
    email: str
    sex: str | None = None
    birthYear: int | None = None
    lang: str | None = None
    googleId: str | None = None
    facebookId: str | None = None
    appleId: str | None = None


class NutrientGoal(_Permissive):
    code: str | None = None
    title: str | None = None
    value: float | str | None = None
    computedValue: str | None = None
    active: bool | None = None


class DiaryTimeRatio(_Permissive):
    position: str
    title: str
    value: float | str | None = None


class Profile(_Permissive):
    guid: str
    email: str
    sex: str | None = None
    height: float | None = None
    weight: float | None = None
    year: int | None = None
    targetWeight: float | None = None
    drinkRegime: float | None = None
    amr: float | None = None
    energyUnit: str | None = None
    considerActivity: bool | None = None
    ownDiaryTimeRatios: list[DiaryTimeRatio] = Field(default_factory=list)
    ownNutrients: list[NutrientGoal] = Field(default_factory=list)


class FoodEntry(_Permissive):
    """Item inside diary `times[].foodstuff[]` (shape varies; permissive)."""


class DiaryTime(_Permissive):
    id: str
    title: str
    foodstuff: list[FoodEntry] = Field(default_factory=list)
    notes: list[Any] = Field(default_factory=list)
    energyTotal: str | float | None = None
    energyTotalUnit: str | None = None
    dailyTimeUserRatio: Any | None = None


class DiaryDay(_Permissive):
    date: int | None = None
    energyUnit: str | None = None
    times: list[DiaryTime] = Field(default_factory=list)


class SummaryItem(_Permissive):
    title: str | None = None
    titleShort: str | None = None
    unit: str | None = None
    goal: str | None = None
    actual: str | None = None
    percent: float | None = None
    actualValue: float | None = None
    code: str | None = None


class DaySummary(_Permissive):
    date: int | None = None
    items: list[SummaryItem] = Field(default_factory=list)
    itemsDynamic: list[list[SummaryItem]] = Field(default_factory=list)


class UnitOption(_Permissive):
    id: str
    title: str
    multiplier: float | int


class DiaryTimeOption(_Permissive):
    id: str
    title: str


class FoodAddForm(_Permissive):
    """Pre-filled add-food form. Echo most fields back when POSTing /user/foodstuff/add."""

    guid: str
    title: str
    url: str | None = None
    diaryTimeGuid: str | None = None
    diaryTimeOptions: list[DiaryTimeOption] = Field(default_factory=list)
    date: str | None = None
    multiplier: float | int | None = None
    unitGuid: str | None = None
    unitOptions: list[UnitOption] = Field(default_factory=list)
    showUnits: bool | None = None
    energyUnit: str | None = None
    favorite: bool | None = None
    status: int | None = None


class ActivityAddForm(_Permissive):
    guid: str
    title: str
    url: str | None = None
    time: float | str | None = None
    timeUnit: str | None = None
    date: str | None = None
    energy: float | str | None = None
    energyUnit: str | None = None
    favorite: bool | None = None
    timeUser: bool | None = None


class SearchHit(_Permissive):
    """Item from /autocomplete/foodstuff-activity-meal."""

    clazz: str
    id: str
    url: str | None = None
    title: str
    unit: str | None = None
    value: str | None = None
    energy: str | None = None
    energyUnit: str | None = None
    favorite: bool | None = None
    isLiquid: bool | None = None
    hasImage: bool | None = None
