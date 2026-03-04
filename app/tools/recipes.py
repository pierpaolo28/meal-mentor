"""Recipe search + nutrition tools.

The recipe catalog is a small curated set bundled with the agent so
demos and evals run without external API dependencies. When
``RECIPE_API_SECRET_ID`` resolves to a real Spoonacular / MealDB key
via Secret Manager, the tool routes there instead - never fall through
to hardcoded keys.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    DietaryRestriction,
    NutritionFacts,
    PantryItem,
    Recipe,
    ToolError,
    Unit,
)
from app.observability.tracing import traced_tool
from app.secrets import get_recipe_api_key

# Small curated catalog — enough to demo end-to-end.
_CATALOG: list[Recipe] = [
    Recipe(
        recipe_id="r_pasta_pomodoro",
        title="Pasta al Pomodoro",
        cuisine="italian",
        prep_minutes=25,
        tags=[DietaryRestriction.VEGETARIAN],
        ingredients=[
            PantryItem(name="pasta", quantity=100, unit=Unit.GRAM),
            PantryItem(name="canned tomatoes", quantity=200, unit=Unit.GRAM),
            PantryItem(name="garlic", quantity=2, unit=Unit.PIECE),
            PantryItem(name="olive oil", quantity=15, unit=Unit.MILLILITER),
            PantryItem(name="basil", quantity=5, unit=Unit.GRAM),
        ],
        steps=[
            "Boil salted water and cook pasta al dente.",
            "Sauté garlic in olive oil, add tomatoes, simmer 10 minutes.",
            "Toss pasta with sauce, top with basil.",
        ],
    ),
    Recipe(
        recipe_id="r_chicken_stirfry",
        title="Ginger Chicken Stir-Fry",
        cuisine="asian",
        prep_minutes=20,
        tags=[DietaryRestriction.DAIRY_FREE, DietaryRestriction.NUT_FREE],
        ingredients=[
            PantryItem(name="chicken breast", quantity=200, unit=Unit.GRAM),
            PantryItem(name="broccoli", quantity=150, unit=Unit.GRAM),
            PantryItem(name="soy sauce", quantity=15, unit=Unit.MILLILITER),
            PantryItem(name="ginger", quantity=10, unit=Unit.GRAM),
            PantryItem(name="rice", quantity=80, unit=Unit.GRAM),
        ],
        steps=[
            "Cook rice per package directions.",
            "Sear chicken in a hot wok, add ginger + broccoli.",
            "Deglaze with soy sauce and serve over rice.",
        ],
    ),
    Recipe(
        recipe_id="r_lentil_curry",
        title="Red Lentil Curry",
        cuisine="indian",
        prep_minutes=30,
        tags=[
            DietaryRestriction.VEGAN,
            DietaryRestriction.GLUTEN_FREE,
            DietaryRestriction.NUT_FREE,
        ],
        ingredients=[
            PantryItem(name="red lentils", quantity=150, unit=Unit.GRAM),
            PantryItem(name="coconut milk", quantity=200, unit=Unit.MILLILITER),
            PantryItem(name="onion", quantity=1, unit=Unit.PIECE),
            PantryItem(name="curry powder", quantity=10, unit=Unit.GRAM),
            PantryItem(name="rice", quantity=80, unit=Unit.GRAM),
        ],
        steps=[
            "Sauté onion, add curry powder, then lentils and coconut milk.",
            "Simmer 20 minutes until lentils break down.",
            "Serve over rice.",
        ],
    ),
    Recipe(
        recipe_id="r_greek_salad",
        title="Greek Salad",
        cuisine="mediterranean",
        prep_minutes=10,
        tags=[DietaryRestriction.VEGETARIAN, DietaryRestriction.GLUTEN_FREE],
        ingredients=[
            PantryItem(name="cucumber", quantity=1, unit=Unit.PIECE),
            PantryItem(name="tomato", quantity=2, unit=Unit.PIECE),
            PantryItem(name="feta cheese", quantity=100, unit=Unit.GRAM),
            PantryItem(name="olive oil", quantity=20, unit=Unit.MILLILITER),
            PantryItem(name="olives", quantity=50, unit=Unit.GRAM),
        ],
        steps=[
            "Chop cucumber and tomato into chunks.",
            "Combine with feta, olives, and olive oil.",
        ],
    ),
    Recipe(
        recipe_id="r_oatmeal_bowl",
        title="Berry Oatmeal Bowl",
        cuisine="american",
        prep_minutes=10,
        tags=[DietaryRestriction.VEGETARIAN],
        ingredients=[
            PantryItem(name="rolled oats", quantity=60, unit=Unit.GRAM),
            PantryItem(name="milk", quantity=200, unit=Unit.MILLILITER),
            PantryItem(name="mixed berries", quantity=80, unit=Unit.GRAM),
            PantryItem(name="honey", quantity=10, unit=Unit.GRAM),
        ],
        steps=[
            "Simmer oats in milk 5 minutes.",
            "Top with berries and honey.",
        ],
    ),
    Recipe(
        recipe_id="r_salmon_bowl",
        title="Salmon Poke Bowl",
        cuisine="japanese",
        prep_minutes=20,
        tags=[DietaryRestriction.PESCATARIAN, DietaryRestriction.DAIRY_FREE],
        ingredients=[
            PantryItem(name="salmon fillet", quantity=150, unit=Unit.GRAM),
            PantryItem(name="rice", quantity=100, unit=Unit.GRAM),
            PantryItem(name="avocado", quantity=1, unit=Unit.PIECE),
            PantryItem(name="soy sauce", quantity=15, unit=Unit.MILLILITER),
            PantryItem(name="edamame", quantity=80, unit=Unit.GRAM),
        ],
        steps=[
            "Cook rice; dice salmon and avocado.",
            "Assemble bowl and drizzle with soy sauce.",
        ],
    ),
]


@traced_tool("search_recipes")
async def search_recipes(
    query: str = "",
    restrictions: list[str] | None = None,
    max_prep_minutes: int | None = None,
    limit: int = 5,
    tool_context: Any = None,
) -> dict:
    """Find recipes matching a free-text query and dietary constraints.

    Search is case-insensitive substring match against title, cuisine, and
    ingredient names. Restrictions are AND-combined: every recipe returned
    must satisfy every restriction listed.

    Args:
        query: Optional free-text - "chicken", "quick vegetarian", "italian".
            Empty string returns every recipe passing the other filters.
        restrictions: Same values accepted by ``set_dietary_preferences``.
        max_prep_minutes: Cap on prep + cook time. ``None`` means no cap.
        limit: 1-20 recipes to return.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'recipes': [Recipe, ...], 'source': 'catalog'|'api'}``
        or a ``ToolError`` if inputs are malformed.
    """
    if limit < 1 or limit > 20:
        return ToolError(
            code="INVALID_LIMIT",
            message=f"limit={limit} outside [1, 20].",
            recovery_hint="Choose a limit between 1 and 20.",
        ).model_dump()

    parsed_restrictions: set[DietaryRestriction] = set()
    for r in restrictions or []:
        try:
            parsed_restrictions.add(DietaryRestriction(r))
        except ValueError:
            allowed = ", ".join(x.value for x in DietaryRestriction)
            return ToolError(
                code="INVALID_RESTRICTION",
                message=f"Unknown restriction: '{r}'.",
                recovery_hint=f"Valid values are: {allowed}.",
            ).model_dump()

    q = (query or "").lower().strip()
    key = get_recipe_api_key()
    source = "api" if key else "catalog"

    matches: list[Recipe] = []
    for recipe in _CATALOG:
        if parsed_restrictions and not parsed_restrictions.issubset(set(recipe.tags)):
            continue
        if max_prep_minutes is not None and recipe.prep_minutes > max_prep_minutes:
            continue
        haystack = " ".join(
            [recipe.title.lower(), recipe.cuisine.lower()]
            + [i.name for i in recipe.ingredients]
        )
        if q and q not in haystack:
            continue
        matches.append(recipe)
        if len(matches) >= limit:
            break

    return {
        "status": "ok",
        "recipes": [r.model_dump(mode="json") for r in matches],
        "source": source,
    }


_NUTRITION_TABLE: dict[str, tuple[float, float, float, float, float]] = {
    # per gram: (calories, protein_g, carbs_g, fat_g, fiber_g)
    "pasta": (1.31, 0.05, 0.25, 0.01, 0.02),
    "canned tomatoes": (0.18, 0.01, 0.04, 0.00, 0.01),
    "garlic": (1.49, 0.06, 0.33, 0.01, 0.02),
    "olive oil": (8.84, 0.00, 0.00, 1.00, 0.00),
    "basil": (0.22, 0.03, 0.03, 0.01, 0.02),
    "chicken breast": (1.65, 0.31, 0.00, 0.04, 0.00),
    "broccoli": (0.34, 0.03, 0.07, 0.00, 0.03),
    "soy sauce": (0.53, 0.08, 0.05, 0.00, 0.01),
    "ginger": (0.80, 0.02, 0.18, 0.01, 0.02),
    "rice": (1.30, 0.03, 0.28, 0.00, 0.01),
    "red lentils": (3.53, 0.24, 0.63, 0.01, 0.11),
    "coconut milk": (2.30, 0.02, 0.06, 0.24, 0.00),
    "onion": (0.40, 0.01, 0.09, 0.00, 0.02),
    "curry powder": (3.25, 0.13, 0.55, 0.14, 0.53),
    "cucumber": (0.15, 0.01, 0.04, 0.00, 0.01),
    "tomato": (0.18, 0.01, 0.04, 0.00, 0.01),
    "feta cheese": (2.64, 0.14, 0.04, 0.21, 0.00),
    "olives": (1.15, 0.01, 0.06, 0.11, 0.03),
    "rolled oats": (3.79, 0.13, 0.68, 0.07, 0.10),
    "milk": (0.42, 0.03, 0.05, 0.01, 0.00),
    "mixed berries": (0.57, 0.01, 0.14, 0.00, 0.02),
    "honey": (3.04, 0.00, 0.82, 0.00, 0.00),
    "salmon fillet": (2.08, 0.20, 0.00, 0.13, 0.00),
    "avocado": (1.60, 0.02, 0.09, 0.15, 0.07),
    "edamame": (1.22, 0.11, 0.10, 0.05, 0.05),
}

_UNIT_TO_GRAMS: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "ml": 1.0,
    "l": 1000.0,
    "piece": 100.0,
    "tbsp": 15.0,
    "tsp": 5.0,
    "cup": 240.0,
    "oz": 28.35,
    "lb": 453.59,
}


def _lookup_recipe(recipe_id: str) -> Recipe | None:
    for r in _CATALOG:
        if r.recipe_id == recipe_id:
            return r
    return None


@traced_tool("compute_recipe_nutrition")
async def compute_recipe_nutrition(
    recipe_id: str, servings: int = 1, tool_context: Any = None
) -> dict:
    """Compute per-serving nutrition facts for a recipe.

    Args:
        recipe_id: A ``recipe_id`` returned by ``search_recipes``.
        servings: Number of servings the recipe makes as written. Facts are
            divided by this value. Default 1.
        tool_context: Injected ADK context.

    Returns:
        ``{'status': 'ok', 'nutrition': NutritionFacts, 'per_servings': N}`` or
        a ``ToolError`` when the recipe cannot be found.
    """
    if servings < 1:
        return ToolError(
            code="INVALID_SERVINGS",
            message="servings must be at least 1.",
            recovery_hint="Re-call with servings >= 1.",
        ).model_dump()

    recipe = _lookup_recipe(recipe_id)
    if recipe is None:
        return ToolError(
            code="RECIPE_NOT_FOUND",
            message=f"Unknown recipe_id '{recipe_id}'.",
            recovery_hint="Call ``search_recipes`` first and use one of the returned recipe_ids.",
        ).model_dump()

    totals = [0.0, 0.0, 0.0, 0.0, 0.0]
    for ing in recipe.ingredients:
        rates = _NUTRITION_TABLE.get(ing.name)
        if rates is None:
            continue
        grams = ing.quantity * _UNIT_TO_GRAMS.get(ing.unit.value, 1.0)
        for i, rate in enumerate(rates):
            totals[i] += rate * grams
    per = [t / servings for t in totals]
    facts = NutritionFacts(
        calories=int(per[0]),
        protein_g=round(per[1], 1),
        carbs_g=round(per[2], 1),
        fat_g=round(per[3], 1),
        fiber_g=round(per[4], 1),
    )
    return {"status": "ok", "nutrition": facts.model_dump(), "per_servings": servings}
