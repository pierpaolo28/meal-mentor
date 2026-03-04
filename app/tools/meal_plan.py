"""Meal-plan persistence tools.

A meal plan is a keyed-by-week (Monday date) collection of ``Meal`` slots.
Saving is idempotent — re-saving with the same ``week_start`` overwrites.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from app.memory.firestore_store import get_store
from app.models import Meal, MealPlan, ToolError
from app.observability.tracing import traced_tool
from app.tools.pantry import _user_id


@traced_tool("save_weekly_meal_plan")
async def save_weekly_meal_plan(
    week_start: str,
    meals: list[dict],
    tool_context: Any = None,
) -> dict:
    """Persist a weekly meal plan for the user.

    Args:
        week_start: ISO-8601 date (``YYYY-MM-DD``) of the plan's Monday.
        meals: List of meal dicts, each with keys ``day`` (lowercase weekday),
            ``slot`` (``breakfast|lunch|dinner|snack``), ``recipe_id``
            (returned by ``search_recipes``), and ``servings`` (1-12).
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'week_start': ..., 'meal_count': N}`` on success or
        a ``ToolError`` describing which meal failed validation.
    """
    try:
        parsed_meals = [Meal(**m) for m in meals]
        plan = MealPlan(week_start=date.fromisoformat(week_start), meals=parsed_meals)
    except (ValidationError, ValueError, TypeError) as exc:
        return ToolError(
            code="INVALID_MEAL_PLAN",
            message=str(exc),
            recovery_hint=(
                "Each meal needs day, slot, recipe_id (from search_recipes), "
                "and servings (1-12). week_start must be an ISO date."
            ),
        ).model_dump()

    store = get_store()
    await store.put_meal_plan(
        _user_id(tool_context), week_start, plan.model_dump(mode="json")
    )
    return {"status": "ok", "week_start": week_start, "meal_count": len(parsed_meals)}


@traced_tool("get_weekly_meal_plan")
async def get_weekly_meal_plan(week_start: str, tool_context: Any = None) -> dict:
    """Fetch a previously-saved meal plan.

    Args:
        week_start: ISO-8601 date of the plan's Monday.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'plan': {...} | null}``. A missing plan is NOT an
        error - the model should then offer to create one.
    """
    store = get_store()
    plan = await store.get_meal_plan(_user_id(tool_context), week_start)
    return {"status": "ok", "plan": plan}
