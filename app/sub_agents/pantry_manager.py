"""PantryAgent — CRUD over the pantry.

Fast model (Flash) because operations are simple: parse the user's utterance
and call the right pantry tool.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.config import MODEL_FLASH
from app.memory.consolidation import compact_history
from app.tools import add_pantry_item, list_pantry_items, remove_pantry_item

_INSTRUCTION = """You are the **PantryKeeper**, the meal-mentor specialist for pantry state.

Your only job is to reflect the user's real-world pantry into the database.

Rules:
- When the user says they "bought X", "have Y", or "used Z", call the
  matching tool immediately - do not ask for confirmation on simple add/remove.
- When the user asks "what do I have", call `list_pantry_items` and format the
  result as a short bulleted list, calling out items in `expiring_soon`.
- If the user's amount or unit is ambiguous, ask ONE clarifying question then
  proceed. Never guess a unit silently.
- Reply in one or two sentences after each action - no essays.
"""


def build_pantry_agent() -> Agent:
    return Agent(
        name="pantry_keeper",
        description="Adds, removes, and lists pantry items. Owns pantry CRUD tools.",
        model=Gemini(
            model=MODEL_FLASH, retry_options=types.HttpRetryOptions(attempts=3)
        ),
        instruction=_INSTRUCTION,
        tools=[add_pantry_item, remove_pantry_item, list_pantry_items],
        before_model_callback=compact_history,
    )
