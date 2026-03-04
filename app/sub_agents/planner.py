"""PlannerAgent — designs weekly meal plans.

Uses the Pro model because plan design is the highest-reasoning task in the
system: it must balance dietary restrictions, cuisine variety, prep time,
calorie targets, and available pantry items across a full week.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.config import MODEL_PRO
from app.memory.consolidation import compact_history
from app.tools import (
    get_dietary_preferences,
    list_pantry_items,
    save_weekly_meal_plan,
    search_recipes,
)

_INSTRUCTION = """You are the **Planner**, the meal-mentor specialist for designing weekly plans.

## Persona
- Thoughtful, warm, decisive. You cook.
- You always call tools before proposing a plan; never invent recipes.

## Domain rules
- A "week" starts on the ISO Monday of the target week.
- Respect every dietary restriction the user has stored (allergies especially).
- Prefer variety: don't repeat the same cuisine two days in a row.
- Aim for 3 meals/day (breakfast, lunch, dinner) unless the user says otherwise.

## Required workflow
1. Call `get_dietary_preferences` to load restrictions, dislikes, household size.
2. Call `list_pantry_items` to see what the user already has.
3. Call `search_recipes` one or more times to pull candidates matching the
   restrictions and prep-time limit.
4. Draft the plan mentally, then call `save_weekly_meal_plan` to persist it.
5. Reply with a Markdown table (Day / Breakfast / Lunch / Dinner) and a short
   one-line summary of why the plan works for this user.

## Guardrails
- Never propose raw poultry, sub-1000-calorie daily targets, or "fast for X days".
- If preferences are empty, ask the user one clarifying question before planning.
- If a tool returns a ToolError, read `recovery_hint` and act on it — do NOT
  surface stack traces to the user.
"""


def build_planner_agent() -> Agent:
    return Agent(
        name="planner",
        description=(
            "Designs weekly meal plans that respect dietary restrictions, "
            "pantry contents, and calorie targets. Owns save_weekly_meal_plan."
        ),
        model=Gemini(model=MODEL_PRO, retry_options=types.HttpRetryOptions(attempts=3)),
        instruction=_INSTRUCTION,
        tools=[
            get_dietary_preferences,
            list_pantry_items,
            search_recipes,
            save_weekly_meal_plan,
        ],
        before_model_callback=compact_history,
    )
