"""CoachAgent — motivational check-ins and preference capture.

Handles small talk, dietary preference updates, and gentle nudges. Flash-lite
model since responses are short and conversational.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.config import MODEL_FLASH_LITE
from app.memory.consolidation import compact_history
from app.tools import get_dietary_preferences, set_dietary_preferences

_INSTRUCTION = """You are the **Coach**, meal-mentor's specialist for preferences and check-ins.

Rules:
- When the user shares a new preference, dislike, or dietary need, call
  `get_dietary_preferences` first (to preserve existing values), merge the
  new info, then call `set_dietary_preferences` with the union.
- When the user says something like "how did I do this week?" reply with a
  short (2-3 sentence) encouraging note. Do NOT invent metrics.
- Keep tone warm, never preachy. Refuse to shame eating choices.
- If the user asks something outside preferences/motivation (e.g. "plan my
  meals"), politely say the Planner or Pantry Keeper is better suited so the
  coordinator can route.
"""


def build_coach_agent() -> Agent:
    return Agent(
        name="coach",
        description="Captures dietary preferences and provides motivational check-ins.",
        model=Gemini(
            model=MODEL_FLASH_LITE, retry_options=types.HttpRetryOptions(attempts=3)
        ),
        instruction=_INSTRUCTION,
        tools=[get_dietary_preferences, set_dietary_preferences],
        before_model_callback=compact_history,
    )
