"""FastMCP server exposing tablycjakalorijnosti as MCP tools.

Phase 3 (dev): no auth on the MCP transport. Single user via TABLYCJA_COOKIES env.
Phase 4 will wrap in OAuth 2.1 (resource server) per MCP spec.

Run streamable-http:
    TABLYCJA_COOKIES='{"PHPSESSID":"..."}' uv run python -m mcp_server

Run stdio (for Claude Desktop / Cursor / VS Code):
    TABLYCJA_COOKIES='{...}' uv run python -m mcp_server --stdio
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .context import get_client
from .tools import activity as activity_tools
from .tools import catalog as catalog_tools
from .tools import diary as diary_tools
from .tools import profile as profile_tools
from .tools import recipes as recipes_tools
from .tools import weight as weight_tools


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="tablycja",
        instructions=(
            "Bridge to tablycjakalorijnosti.com.ua. "
            "Use search_food / search_activity to resolve names → GUIDs, "
            "then log_food / log_activity / log_weight to write entries. "
            "get_day and get_summary read the diary. Dates: ISO YYYY-MM-DD."
        ),
    )

    @mcp.tool()
    async def get_active_user() -> dict[str, Any]:
        """Compact account record (id, email, sex, lang). Useful as auth probe."""
        return await profile_tools.get_active_user(await get_client())

    @mcp.tool()
    async def get_profile() -> dict[str, Any]:
        """Full user profile: height, weight, target, AMR, energy + macro goals."""
        return await profile_tools.get_profile(await get_client())

    @mcp.tool()
    async def get_day(day: str) -> dict[str, Any]:
        """Diary for a date. `day` = ISO YYYY-MM-DD or DD.MM.YYYY."""
        return await diary_tools.get_day(await get_client(), day)

    @mcp.tool()
    async def get_summary(day: str) -> dict[str, Any]:
        """Daily totals + macro breakdown. `day` = ISO YYYY-MM-DD or DD.MM.YYYY."""
        return await diary_tools.get_summary(await get_client(), day)

    @mcp.tool()
    async def search_food(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Autocomplete foods/activities/meals by name. Returns id, title, energy."""
        return await catalog_tools.search_food(await get_client(), query=query, limit=limit)

    @mcp.tool()
    async def search_activity(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Autocomplete activities by name."""
        return await catalog_tools.search_activity(await get_client(), query=query, limit=limit)

    @mcp.tool()
    async def get_food_detail(food_id: str) -> dict[str, Any]:
        """Full nutrient detail + unit options for a foodstuff GUID."""
        return await catalog_tools.get_food_detail(await get_client(), food_id=food_id)

    @mcp.tool()
    async def search_food_with_macros(
        query: str,
        limit: int = 10,
        min_energy: int = 0,
        max_energy: int = 3800,
    ) -> dict[str, Any]:
        """Search foodstuff DB with per-100g macros (energy, protein,
        carbohydrate, fat, fiber, sugar, salt, calcium, sodium, ...).
        Use this instead of `search_food` when you need macros up front,
        or when you want to filter by calorie range. `id` from items can
        be passed to `log_food` directly."""
        return await catalog_tools.search_food_with_macros(
            await get_client(),
            query=query,
            limit=limit,
            min_energy=min_energy,
            max_energy=max_energy,
        )

    @mcp.tool()
    async def log_food(
        food_id: str,
        grams: float,
        meal: str,
        day: str,
    ) -> dict[str, Any]:
        """Add a food entry to the diary.

        food_id = GUID from search_food. meal = breakfast/snack1/lunch/snack2/dinner/snack3
        or 1-6. day = ISO YYYY-MM-DD or DD.MM.YYYY.
        """
        return await diary_tools.log_food(
            await get_client(), food_id=food_id, grams=grams, meal=meal, day=day
        )

    @mcp.tool()
    async def log_activity(
        activity_id: str, minutes: float, day: str
    ) -> dict[str, Any]:
        """Log an activity entry. activity_id = GUID from search_activity."""
        return await activity_tools.log_activity(
            await get_client(), activity_id=activity_id, minutes=minutes, day=day
        )

    @mcp.tool()
    async def log_weight(weight_kg: float, day: str) -> dict[str, Any]:
        """Log body weight in kilograms for a given day."""
        return await weight_tools.log_weight(
            await get_client(), weight_kg=weight_kg, day=day
        )

    @mcp.tool()
    async def list_my_recipes(
        query: str = "", page: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """List the user's saved personal recipes ("Мої рецепти"). Returns
        each recipe's id (GUID), title, energy, energy_unit, portions,
        visibility. Use the `id` with `get_my_recipe` or `log_recipe`."""
        return await recipes_tools.list_my_recipes(
            await get_client(), query=query, page=page, limit=limit
        )

    @mcp.tool()
    async def get_my_recipe(recipe_id: str) -> dict[str, Any]:
        """Full detail for a personal recipe: macros, ingredients, portions."""
        return await recipes_tools.get_my_recipe(
            await get_client(), recipe_id=recipe_id
        )

    @mcp.tool()
    async def get_diary_entry(entry_id: str) -> dict[str, Any]:
        """Editable form for an already-logged diary entry. Returns the
        full ingredient list with counts + units. Use `edit_diary_entry`
        to mutate (remove ingredients, scale counts, change meal slot).

        entry_id = the `id` field of any item in get_day().meals[].items[].
        """
        return await recipes_tools.get_diary_entry(
            await get_client(), entry_id=entry_id
        )

    @mcp.tool()
    async def edit_diary_entry(
        entry_id: str,
        exclude_ingredients: list[str] | None = None,
        scale_ingredients: dict[str, float] | None = None,
        meal: str | None = None,
    ) -> dict[str, Any]:
        """Edit a diary entry that's already in today's (or any day's)
        diary. Use this to fix a recipe entry that didn't actually contain
        every ingredient (e.g. cocktail without banana), to scale a portion
        (half the avocado), or to move the entry to a different meal slot.

        Upstream recomputes calories + macros from what we send.

        entry_id = the `id` field of an item in get_day().meals[].items[].
        exclude_ingredients = titles or ingredient GUIDs to drop.
        scale_ingredients = {title_or_guid: factor} (e.g. {"Авокадо Хасс": 0.5}).
        meal = move to breakfast/snack1/lunch/snack2/dinner/snack3 or 1-6
          (omit to keep current slot).
        """
        return await recipes_tools.edit_diary_entry(
            await get_client(),
            entry_id=entry_id,
            exclude_ingredients=exclude_ingredients,
            scale_ingredients=scale_ingredients,
            meal=meal,
        )

    @mcp.tool()
    async def log_recipe(
        recipe_id: str,
        meal: str,
        day: str,
        exclude_ingredients: list[str] | None = None,
        scale_ingredients: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Add a personal recipe entry to the diary, optionally removing or
        scaling individual ingredients. Upstream recomputes calories/macros
        from the items sent.

        recipe_id = GUID from list_my_recipes.
        meal = breakfast/snack1/lunch/snack2/dinner/snack3 or 1-6.
        day = ISO YYYY-MM-DD or DD.MM.YYYY.
        exclude_ingredients = list of titles or ingredient GUIDs to drop
          (e.g. ["Йогурт"] removes that ingredient before logging).
        scale_ingredients = {title_or_guid: factor} to multiply count
          (e.g. {"Авокадо Хасс": 0.5} = half portion of avocado).
        """
        return await recipes_tools.log_recipe(
            await get_client(),
            recipe_id=recipe_id,
            meal=meal,
            day=day,
            exclude_ingredients=exclude_ingredients,
            scale_ingredients=scale_ingredients,
        )

    return mcp


__all__ = ["build_server"]
