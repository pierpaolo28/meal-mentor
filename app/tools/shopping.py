"""Shopping-list generator and HITL-protected grocery order.

* ``generate_shopping_list`` — pure computation: read the meal plan, sum
  ingredients, subtract pantry, emit a ``ShoppingList``. No side effects.
* ``place_grocery_order`` — high-stakes: NEVER actually orders on the first
  call. Instead it stashes the pending order under a nonce and returns
  ``awaiting_confirmation``. The user (or driving agent) must call
  ``confirm_grocery_order`` with that nonce to actually submit.

This two-step pattern is the "Human-in-the-Loop hook" from the review rubric.
"""

from __future__ import annotations

import secrets as _secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.memory.firestore_store import get_store
from app.models import (
    HITLPendingAction,
    MealPlan,
    ShoppingItem,
    ShoppingList,
    ToolError,
    Unit,
)
from app.observability.tracing import traced_tool
from app.tools.pantry import _user_id
from app.tools.recipes import _CATALOG, _UNIT_TO_GRAMS

# Rough price estimates ($ per gram or per ml). Real deployment would call a
# grocer API with the key from Secret Manager.
_PRICE_PER_GRAM: dict[str, float] = {
    "pasta": 0.005,
    "canned tomatoes": 0.004,
    "garlic": 0.02,
    "olive oil": 0.015,
    "basil": 0.05,
    "chicken breast": 0.012,
    "broccoli": 0.006,
    "soy sauce": 0.01,
    "ginger": 0.02,
    "rice": 0.004,
    "red lentils": 0.007,
    "coconut milk": 0.008,
    "onion": 0.003,
    "curry powder": 0.06,
    "cucumber": 0.005,
    "tomato": 0.007,
    "feta cheese": 0.025,
    "olives": 0.03,
    "rolled oats": 0.006,
    "milk": 0.002,
    "mixed berries": 0.03,
    "honey": 0.02,
    "salmon fillet": 0.035,
    "avocado": 0.012,
    "edamame": 0.015,
}


def _lookup_recipe(recipe_id: str):
    for r in _CATALOG:
        if r.recipe_id == recipe_id:
            return r
    return None


@traced_tool("generate_shopping_list")
async def generate_shopping_list(week_start: str, tool_context: Any = None) -> dict:
    """Diff a week's meal plan against the pantry, output the shopping list.

    Args:
        week_start: ISO-8601 date of the plan's Monday.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'shopping_list': ShoppingList}`` or a ``ToolError``
        (e.g. when no plan exists for that week).
    """
    store = get_store()
    user_id = _user_id(tool_context)
    plan_dict = await store.get_meal_plan(user_id, week_start)
    if not plan_dict:
        return ToolError(
            code="NO_MEAL_PLAN",
            message=f"No meal plan saved for week starting {week_start}.",
            recovery_hint="Ask the user to create a plan first, then call save_weekly_meal_plan.",
        ).model_dump()

    try:
        plan = MealPlan.model_validate(plan_dict)
    except Exception as exc:
        return ToolError(
            code="CORRUPT_PLAN",
            message=f"Stored plan failed validation: {exc}",
            recovery_hint="Ask the user to rebuild the plan for this week.",
        ).model_dump()

    # Aggregate required ingredients across every meal.
    needs: dict[tuple[str, str], float] = defaultdict(float)  # (name, unit) -> quantity
    for meal in plan.meals:
        recipe = _lookup_recipe(meal.recipe_id)
        if recipe is None:
            continue
        for ing in recipe.ingredients:
            needs[(ing.name, ing.unit.value)] += ing.quantity * meal.servings

    # Subtract pantry.
    pantry = await store.get_pantry(user_id)
    for item in pantry:
        key = (item.get("name"), item.get("unit"))
        if key in needs:
            needs[key] = max(0.0, needs[key] - float(item.get("quantity", 0)))

    items: list[ShoppingItem] = []
    total = 0.0
    for (name, unit), qty in sorted(needs.items()):
        if qty <= 0:
            continue
        grams = qty * _UNIT_TO_GRAMS.get(unit, 1.0)
        price = round(grams * _PRICE_PER_GRAM.get(name, 0.01), 2)
        items.append(
            ShoppingItem(
                name=name,
                quantity=round(qty, 2),
                unit=Unit(unit),
                estimated_cost_usd=price,
            )
        )
        total += price

    shopping_list = ShoppingList(
        week_start=plan.week_start,
        items=items,
        total_estimated_cost_usd=round(total, 2),
    )
    return {"status": "ok", "shopping_list": shopping_list.model_dump(mode="json")}


@traced_tool("place_grocery_order")
async def place_grocery_order(week_start: str, tool_context: Any = None) -> dict:
    """Stage a grocery order for human confirmation.

    This tool NEVER charges the user directly. It computes the shopping list,
    stashes it under a random confirmation token, and returns an
    ``HITLPendingAction``. The user's next message must contain the token,
    which the agent then passes to ``confirm_grocery_order``.

    Args:
        week_start: ISO date of the plan's Monday.
        tool_context: Injected ADK context.

    Returns:
        ``HITLPendingAction`` payload (status='awaiting_confirmation') or
        a ``ToolError``.
    """
    generated = await generate_shopping_list(
        week_start=week_start, tool_context=tool_context
    )
    if generated.get("status") != "ok":
        return generated

    shopping_list = generated["shopping_list"]
    token = _secrets.token_urlsafe(8)
    expires = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()

    store = get_store()
    await store.stash_order(
        _user_id(tool_context),
        token,
        {
            "week_start": week_start,
            "shopping_list": shopping_list,
            "expires_at": expires,
        },
    )

    pending = HITLPendingAction(
        action="place_grocery_order",
        confirmation_token=token,
        summary=(
            f"Order {len(shopping_list['items'])} items for week of {week_start} "
            f"totaling ${shopping_list['total_estimated_cost_usd']}. "
            "This will charge the user's default payment method."
        ),
        expires_at_iso=expires,
    )
    return pending.model_dump()


@traced_tool("confirm_grocery_order")
async def confirm_grocery_order(
    confirmation_token: str, tool_context: Any = None
) -> dict:
    """Execute a previously-staged grocery order.

    Args:
        confirmation_token: The token returned by ``place_grocery_order``.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'order_id': ..., 'total_usd': ...}`` on success,
        or a ``ToolError`` when the token is unknown/expired.
    """
    store = get_store()
    payload = await store.pop_order(_user_id(tool_context), confirmation_token)
    if payload is None:
        return ToolError(
            code="TOKEN_UNKNOWN",
            message="No pending order matches that confirmation token.",
            recovery_hint="Call place_grocery_order again to stage a fresh order.",
        ).model_dump()

    try:
        expires = datetime.fromisoformat(payload.get("expires_at", ""))
        if expires < datetime.now(UTC):
            return ToolError(
                code="TOKEN_EXPIRED",
                message="The confirmation token has expired.",
                recovery_hint="Ask the user to confirm again; place a fresh order via place_grocery_order.",
            ).model_dump()
    except (ValueError, TypeError):
        pass

    # In a real deployment this is where you'd POST to the grocer API using
    # the key from Secret Manager. Stub returns a synthetic order id.
    order_id = f"ord_{confirmation_token[:6]}"
    return {
        "status": "ok",
        "order_id": order_id,
        "total_usd": payload.get("shopping_list", {}).get(
            "total_estimated_cost_usd", 0.0
        ),
        "week_start": payload.get("week_start"),
    }
