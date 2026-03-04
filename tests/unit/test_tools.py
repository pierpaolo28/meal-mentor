"""Unit tests for the tool layer.

Runs against the in-memory Firestore fallback so no GCP creds are required.
"""

from __future__ import annotations

import os

import pytest

os.environ["USE_IN_MEMORY_STORE"] = "1"

from app.memory.firestore_store import get_store
from app.tools.meal_plan import (
    get_weekly_meal_plan,
    save_weekly_meal_plan,
)
from app.tools.pantry import (
    add_pantry_item,
    list_pantry_items,
    remove_pantry_item,
)
from app.tools.preferences import (
    get_dietary_preferences,
    set_dietary_preferences,
)
from app.tools.recipes import compute_recipe_nutrition, search_recipes
from app.tools.shopping import (
    confirm_grocery_order,
    generate_shopping_list,
    place_grocery_order,
)


class _Ctx:
    """Minimal ADK ToolContext stand-in."""

    def __init__(self, user_id: str = "test_user"):
        self.state = {"user_id": user_id}


@pytest.fixture(autouse=True)
def _reset_store():
    # in-memory backend is shared - wipe between tests
    store = get_store()
    store._memory._data.clear()  # type: ignore[attr-defined]
    yield


@pytest.mark.asyncio
async def test_add_and_list_pantry():
    ctx = _Ctx()
    out = await add_pantry_item(name="pasta", quantity=500, unit="g", tool_context=ctx)
    assert out["status"] == "ok"
    listed = await list_pantry_items(tool_context=ctx)
    assert listed["status"] == "ok"
    assert any(i["name"] == "pasta" for i in listed["items"])


@pytest.mark.asyncio
async def test_add_pantry_invalid_unit_returns_guided_error():
    ctx = _Ctx()
    out = await add_pantry_item(
        name="pasta", quantity=1, unit="parsecs", tool_context=ctx
    )
    assert out["status"] == "error"
    assert out["code"] == "INVALID_PANTRY_ITEM"
    assert "unit" in out["recovery_hint"].lower()


@pytest.mark.asyncio
async def test_remove_missing_item_returns_guided_error():
    ctx = _Ctx()
    out = await remove_pantry_item(name="unicorn steak", tool_context=ctx)
    assert out["status"] == "error"
    assert out["code"] == "ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_search_recipes_filters_by_restriction():
    out = await search_recipes(restrictions=["vegan"], tool_context=_Ctx())
    assert out["status"] == "ok"
    assert all("vegan" in r["tags"] for r in out["recipes"])


@pytest.mark.asyncio
async def test_compute_nutrition_for_unknown_recipe():
    out = await compute_recipe_nutrition(
        recipe_id="does_not_exist", tool_context=_Ctx()
    )
    assert out["status"] == "error"
    assert out["code"] == "RECIPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_preferences_roundtrip():
    ctx = _Ctx()
    await set_dietary_preferences(
        restrictions=["vegetarian"],
        household_size=3,
        tool_context=ctx,
    )
    got = await get_dietary_preferences(tool_context=ctx)
    assert got["preferences"]["household_size"] == 3
    assert "vegetarian" in got["preferences"]["restrictions"]


@pytest.mark.asyncio
async def test_meal_plan_and_shopping_list_end_to_end():
    ctx = _Ctx()
    week = "2026-10-05"
    meals = [
        {
            "day": "monday",
            "slot": "lunch",
            "recipe_id": "r_pasta_pomodoro",
            "servings": 2,
        },
        {
            "day": "tuesday",
            "slot": "dinner",
            "recipe_id": "r_lentil_curry",
            "servings": 2,
        },
    ]
    save_result = await save_weekly_meal_plan(
        week_start=week, meals=meals, tool_context=ctx
    )
    assert save_result["status"] == "ok"

    fetched = await get_weekly_meal_plan(week_start=week, tool_context=ctx)
    assert fetched["plan"]["meals"][0]["recipe_id"] == "r_pasta_pomodoro"

    shopping = await generate_shopping_list(week_start=week, tool_context=ctx)
    assert shopping["status"] == "ok"
    assert shopping["shopping_list"]["total_estimated_cost_usd"] > 0


@pytest.mark.asyncio
async def test_generate_shopping_list_without_plan_returns_error():
    ctx = _Ctx()
    out = await generate_shopping_list(week_start="2099-01-01", tool_context=ctx)
    assert out["status"] == "error"
    assert out["code"] == "NO_MEAL_PLAN"


@pytest.mark.asyncio
async def test_hitl_order_requires_confirmation_token():
    ctx = _Ctx()
    week = "2026-10-12"
    await save_weekly_meal_plan(
        week_start=week,
        meals=[
            {
                "day": "monday",
                "slot": "lunch",
                "recipe_id": "r_greek_salad",
                "servings": 2,
            }
        ],
        tool_context=ctx,
    )
    pending = await place_grocery_order(week_start=week, tool_context=ctx)
    assert pending["status"] == "awaiting_confirmation"
    token = pending["confirmation_token"]

    bad = await confirm_grocery_order(
        confirmation_token="wrong_token", tool_context=ctx
    )
    assert bad["status"] == "error"
    assert bad["code"] == "TOKEN_UNKNOWN"

    good = await confirm_grocery_order(confirmation_token=token, tool_context=ctx)
    assert good["status"] == "ok"
    assert good["order_id"].startswith("ord_")

    # Token must be single-use.
    replay = await confirm_grocery_order(confirmation_token=token, tool_context=ctx)
    assert replay["status"] == "error"
