"""ShoppingAgent — generates shopping lists and stages grocery orders.

Ordering is HITL-guarded via ``place_grocery_order`` → ``confirm_grocery_order``.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.config import MODEL_FLASH
from app.memory.consolidation import compact_history
from app.tools import (
    confirm_grocery_order,
    generate_shopping_list,
    get_weekly_meal_plan,
    place_grocery_order,
)

_INSTRUCTION = """You are the **Shopper**, meal-mentor's specialist for shopping lists and orders.

## Read-only requests
- If the user asks "what do I need to buy", call `generate_shopping_list` and
  format the result as a grouped, priced Markdown list.

## Order requests (HIGH STAKES)
When the user asks you to place a real grocery order:
1. Call `place_grocery_order` FIRST. It returns an `awaiting_confirmation`
   payload with a `confirmation_token`.
2. Read the `summary` back to the user and explicitly ask them to reply
   "confirm ORDER-{token}" to authorize the charge. Never skip this step.
3. Only after the user echoes the token, call `confirm_grocery_order` with it.
4. If the user backs out, tell them the order was NOT placed and move on -
   the token expires in 10 minutes anyway.

Never call `confirm_grocery_order` in the same turn as `place_grocery_order`.
"""


def build_shopper_agent() -> Agent:
    return Agent(
        name="shopper",
        description=(
            "Generates shopping lists from meal plans and stages grocery orders "
            "with mandatory human confirmation before charging."
        ),
        model=Gemini(
            model=MODEL_FLASH, retry_options=types.HttpRetryOptions(attempts=3)
        ),
        instruction=_INSTRUCTION,
        tools=[
            get_weekly_meal_plan,
            generate_shopping_list,
            place_grocery_order,
            confirm_grocery_order,
        ],
        before_model_callback=compact_history,
    )
