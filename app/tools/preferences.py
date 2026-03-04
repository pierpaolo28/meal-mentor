"""Dietary preferences tools.

Preferences are persisted per user and read by the planner before every plan
so that suggestions respect allergies, dislikes, and calorie targets. Setting
preferences is a HITL-lite action: the tool always echoes back the fully
resolved preference set so the model can read it to the user for confirmation.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.memory.firestore_store import get_store
from app.models import DietaryPreferences, DietaryRestriction, ToolError
from app.observability.tracing import traced_tool
from app.tools.pantry import _user_id


@traced_tool("set_dietary_preferences")
async def set_dietary_preferences(
    restrictions: list[str] | None = None,
    disliked_ingredients: list[str] | None = None,
    preferred_cuisines: list[str] | None = None,
    target_calories_per_day: int | None = None,
    household_size: int = 2,
    tool_context: Any = None,
) -> dict:
    """Persist the user's dietary preferences for future meal plans.

    This tool OVERWRITES the whole preference document. To merge with existing
    values, call ``get_dietary_preferences`` first, then re-send the union.

    Args:
        restrictions: Dietary restriction strings. Valid values: ``vegetarian``,
            ``vegan``, ``gluten_free``, ``dairy_free``, ``nut_free``, ``kosher``,
            ``halal``, ``low_carb``, ``keto``, ``pescatarian``.
        disliked_ingredients: Lower-case ingredient names the user won't eat
            (e.g. ``["cilantro", "beets"]``).
        preferred_cuisines: Cuisines the user gravitates toward
            (e.g. ``["italian", "japanese"]``).
        target_calories_per_day: Daily calorie target, 800-6000. ``None`` if
            not tracking.
        household_size: Number of people the plan needs to feed. Default 2.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'preferences': {...}}`` on success or ``ToolError``.
    """
    try:
        prefs = DietaryPreferences(
            restrictions=[DietaryRestriction(r) for r in (restrictions or [])],
            disliked_ingredients=[
                i.lower().strip() for i in (disliked_ingredients or [])
            ],
            preferred_cuisines=[c.lower().strip() for c in (preferred_cuisines or [])],
            target_calories_per_day=target_calories_per_day,
            household_size=household_size,
        )
    except (ValidationError, ValueError) as exc:
        allowed = ", ".join(r.value for r in DietaryRestriction)
        return ToolError(
            code="INVALID_PREFERENCES",
            message=str(exc),
            recovery_hint=(
                f"Valid restrictions are: {allowed}. "
                "Household size must be 1-20; calories 800-6000."
            ),
        ).model_dump()

    store = get_store()
    await store.put_preferences(_user_id(tool_context), prefs.model_dump(mode="json"))
    return {"status": "ok", "preferences": prefs.model_dump(mode="json")}


@traced_tool("get_dietary_preferences")
async def get_dietary_preferences(tool_context: Any = None) -> dict:
    """Read the user's stored dietary preferences.

    Use this at the start of any planning request so the planner never
    proposes food the user can't eat.

    Returns:
        ``{'status': 'ok', 'preferences': {...}}`` or, if none stored yet,
        ``{'status': 'ok', 'preferences': null}`` (no error - just empty).
    """
    store = get_store()
    prefs = await store.get_preferences(_user_id(tool_context))
    return {"status": "ok", "preferences": prefs}
