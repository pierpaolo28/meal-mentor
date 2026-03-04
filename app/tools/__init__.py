"""Public tool exports grouped by concern.

Each function here is a plain ADK tool (async, typed args, JSON-schema-worthy
docstring) so the ``tools=[...]`` list in ``agent.py`` stays scannable.
"""

from app.tools.meal_plan import get_weekly_meal_plan, save_weekly_meal_plan
from app.tools.pantry import add_pantry_item, list_pantry_items, remove_pantry_item
from app.tools.preferences import get_dietary_preferences, set_dietary_preferences
from app.tools.recipes import compute_recipe_nutrition, search_recipes
from app.tools.shopping import (
    confirm_grocery_order,
    generate_shopping_list,
    place_grocery_order,
)

__all__ = [
    "add_pantry_item",
    "compute_recipe_nutrition",
    "confirm_grocery_order",
    "generate_shopping_list",
    "get_dietary_preferences",
    "get_weekly_meal_plan",
    "list_pantry_items",
    "place_grocery_order",
    "remove_pantry_item",
    "save_weekly_meal_plan",
    "search_recipes",
    "set_dietary_preferences",
]
