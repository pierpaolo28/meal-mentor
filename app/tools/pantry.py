"""Pantry CRUD tools.

The pantry is the user's list of ingredients currently on hand. The planner
subtracts pantry contents from the meal-plan bill-of-materials to produce a
shopping list. All three tools persist to Firestore via the shared store.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from app.memory.firestore_store import get_store
from app.models import PantryItem, ToolError, Unit
from app.observability.tracing import traced_tool


def _user_id(tool_context: Any) -> str:
    """Extract user id from ADK ToolContext, defaulting to 'anonymous'."""
    if tool_context is None:
        return "anonymous"
    state = getattr(tool_context, "state", None)
    if state is None:
        return "anonymous"
    return state.get("user_id", "anonymous")


def _item_key(name: str, unit: str) -> str:
    return f"{name.lower().strip().replace(' ', '_')}:{unit}"


@traced_tool("add_pantry_item")
async def add_pantry_item(
    name: str,
    quantity: float,
    unit: str,
    expiration_date: str | None = None,
    tool_context: Any = None,
) -> dict:
    """Add or top-up an ingredient in the user's pantry.

    Use this when the user says something like "I just bought 500g of pasta" or
    "we still have 2 cups of rice at home". If the same (name, unit) pair
    already exists in the pantry the quantities are summed - use
    ``remove_pantry_item`` first if the user wants to overwrite.

    Args:
        name: Lower-case singular ingredient name, for example "olive oil"
            or "chicken breast". The tool normalizes casing/spacing.
        quantity: Positive amount in the given unit.
        unit: One of ``g``, ``kg``, ``ml``, ``l``, ``piece``, ``tbsp``,
            ``tsp``, ``cup``, ``oz``, ``lb``.
        expiration_date: Optional ISO-8601 date (``YYYY-MM-DD``) when the item
            expires. Pass ``None`` if not tracked.
        tool_context: Injected ADK context - do NOT set from the model.

    Returns:
        On success, a dict with ``status='ok'`` and the stored ``PantryItem``.
        On invalid input, a ``ToolError`` with a concrete ``recovery_hint``.
    """
    try:
        parsed = PantryItem(
            name=name.lower().strip(),
            quantity=quantity,
            unit=Unit(unit),
            expiration_date=date.fromisoformat(expiration_date)
            if expiration_date
            else None,
        )
    except (ValidationError, ValueError) as exc:
        allowed = ", ".join(u.value for u in Unit)
        return ToolError(
            code="INVALID_PANTRY_ITEM",
            message=str(exc),
            recovery_hint=(
                f"Ensure quantity > 0 and unit is one of: {allowed}. "
                "Ask the user to clarify amount and unit if unclear."
            ),
        ).model_dump()

    store = get_store()
    key = _item_key(parsed.name, parsed.unit.value)
    existing = await store.get("pantry_items", _user_id(tool_context), key)
    if existing:
        parsed = parsed.model_copy(
            update={"quantity": parsed.quantity + float(existing.get("quantity", 0))}
        )
    await store.put_pantry_item(
        _user_id(tool_context),
        key,
        parsed.model_dump(mode="json"),
    )
    return {"status": "ok", "item": parsed.model_dump(mode="json")}


@traced_tool("remove_pantry_item")
async def remove_pantry_item(
    name: str,
    quantity: float | None = None,
    unit: str | None = None,
    tool_context: Any = None,
) -> dict:
    """Remove or decrement an ingredient from the pantry.

    Two modes:

    * If ``quantity`` and ``unit`` are provided, subtract that amount and
      delete the row when the balance hits zero.
    * If both are omitted, delete every entry matching ``name`` regardless
      of unit.

    Args:
        name: Ingredient name (matched case-insensitively).
        quantity: Amount to subtract, or ``None`` to delete the whole entry.
        unit: Unit of ``quantity``; required when ``quantity`` is set.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'removed': [...]}`` on success or a ``ToolError``.
    """
    store = get_store()
    user_id = _user_id(tool_context)
    all_items = await store.get_pantry(user_id)
    target_name = name.lower().strip()

    matches = [it for it in all_items if it.get("name") == target_name]
    if not matches:
        return ToolError(
            code="ITEM_NOT_FOUND",
            message=f"No pantry entry for '{name}'.",
            recovery_hint=(
                "Call ``list_pantry_items`` first to see exactly what the "
                "user has, then try again with the exact name."
            ),
        ).model_dump()

    removed: list[dict] = []
    if quantity is None:
        for it in matches:
            key = _item_key(it["name"], it["unit"])
            await store.delete_pantry_item(user_id, key)
            removed.append(it)
        return {"status": "ok", "removed": removed}

    if unit is None:
        return ToolError(
            code="MISSING_UNIT",
            message="Unit is required when subtracting a specific quantity.",
            recovery_hint="Re-call with the unit that matches the pantry entry, or omit quantity to delete outright.",
        ).model_dump()

    for it in matches:
        if it.get("unit") != unit:
            continue
        remaining = float(it.get("quantity", 0)) - float(quantity)
        key = _item_key(it["name"], it["unit"])
        if remaining <= 0:
            await store.delete_pantry_item(user_id, key)
            removed.append(it)
        else:
            it["quantity"] = remaining
            await store.put_pantry_item(user_id, key, it)
            removed.append(it | {"remaining": remaining})
    if not removed:
        return ToolError(
            code="UNIT_MISMATCH",
            message=f"'{name}' exists in the pantry but not in unit '{unit}'.",
            recovery_hint="Call ``list_pantry_items`` to see the actual unit and retry.",
        ).model_dump()
    return {"status": "ok", "removed": removed}


@traced_tool("list_pantry_items")
async def list_pantry_items(tool_context: Any = None) -> dict:
    """Return every pantry item the user currently has.

    Use this before generating a shopping list or when the user asks
    "what do I have?". Items expiring within 7 days are flagged.

    Returns:
        ``{'status': 'ok', 'items': [...], 'expiring_soon': [...]}``.
    """
    store = get_store()
    user_id = _user_id(tool_context)
    items = await store.get_pantry(user_id)

    today = date.today()
    expiring: list[dict] = []
    for it in items:
        exp = it.get("expiration_date")
        if not exp:
            continue
        try:
            parsed = datetime.fromisoformat(exp).date()
        except (TypeError, ValueError):
            continue
        days_left = (parsed - today).days
        if 0 <= days_left <= 7:
            expiring.append(it | {"days_left": days_left})

    return {"status": "ok", "items": items, "expiring_soon": expiring}
