"""NutritionAgent — computes nutrition facts for recipes.

Flash model: single tool call per turn, no planning required.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.config import MODEL_FLASH
from app.memory.consolidation import compact_history
from app.tools import compute_recipe_nutrition, search_recipes

_INSTRUCTION = """You are the **Nutritionist**, meal-mentor's specialist for nutrition facts.

Rules:
- If the user gives a recipe name, first call `search_recipes` to resolve the
  recipe_id, then call `compute_recipe_nutrition`.
- Present facts as: calories, protein, carbs, fat, fiber. Round to whole
  numbers except protein/carbs/fat which get one decimal.
- Never invent macros - if a recipe has no nutrition data, say so and
  suggest what to substitute.
- Flag responses that would recommend < 1000 kcal/day for an adult and
  refuse politely (send them to a registered dietitian).
"""


def build_nutritionist_agent() -> Agent:
    return Agent(
        name="nutritionist",
        description="Computes per-serving nutrition facts for recipes.",
        model=Gemini(
            model=MODEL_FLASH, retry_options=types.HttpRetryOptions(attempts=3)
        ),
        instruction=_INSTRUCTION,
        tools=[search_recipes, compute_recipe_nutrition],
        before_model_callback=compact_history,
    )
