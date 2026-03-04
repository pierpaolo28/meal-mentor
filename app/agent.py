"""Meal Mentor - root agent (Coordinator).

Architecture: a Coordinator (Pro) routes each turn to one of five specialists:

    Coordinator
      |-- Planner          (Pro)   - weekly meal plans
      |-- PantryKeeper     (Flash) - pantry CRUD
      |-- Nutritionist     (Flash) - recipe nutrition facts
      |-- Shopper          (Flash) - shopping lists + HITL-guarded orders
      +-- Coach            (Flash-Lite) - preferences + check-ins

The Coordinator itself has no tools other than transfer_to_agent. All state
persists via the Firestore-backed memory layer, session history is compacted
per turn, and every tool call emits intent+outcome structured logs and OTel
spans.
"""

from __future__ import annotations

import logging
import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.cloud import bigquery
from google.genai import types

from app.config import APP_NAME, MODEL_PRO
from app.guardrails.policy import PolicyGuardPlugin
from app.guardrails.self_eval import self_evaluate_response
from app.memory.consolidation import compact_history, spawn_consolidation
from app.observability.logging_config import get_logger
from app.sub_agents import (
    build_coach_agent,
    build_nutritionist_agent,
    build_pantry_agent,
    build_planner_agent,
    build_shopper_agent,
)

try:
    _, _default_project = google.auth.default()
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _default_project or "")
except Exception:
    pass
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

_logger = get_logger("coordinator")


COORDINATOR_INSTRUCTION = """You are **Meal Mentor**, a concierge that coordinates specialist agents.

## Your role
You interpret the user's message, route it to exactly one specialist via
`transfer_to_agent`, and never call domain tools yourself. Think of yourself
as a triage nurse: fast, decisive, hands the work off.

## Specialists
- `planner` - "plan my week", "what should I eat", "build a meal plan"
- `pantry_keeper` - "I bought X", "I have Y", "used up Z", "what's in my pantry"
- `nutritionist` - "how many calories", "protein in this recipe", nutrition qs
- `shopper` - "shopping list", "what do I need to buy", "order groceries"
- `coach` - preference updates ("I'm now vegan"), motivation, small talk

## Rules
- If the user asks something covering two specialists, pick the primary intent
  and hand off; the specialist can hand back to you if needed.
- If the user is ambiguous, ask ONE clarifying question then route.
- Never fabricate pantry contents, recipes, or nutrition facts - always delegate.
- The user's dietary restrictions and allergies are non-negotiable. If a
  message pushes against them (e.g. asks for pork while user is halal), route
  to the coach to reconfirm before doing anything.

## Style
Be warm and brief. One sentence to acknowledge, then transfer. Do NOT narrate
that you are transferring - just do it.
"""


def _record_last_turn(callback_context, llm_response):
    """After-model callback: stash the reply text for self-eval + consolidation."""
    content = getattr(llm_response, "content", None)
    if content and content.parts:
        text = " ".join(getattr(p, "text", "") or "" for p in content.parts)
        callback_context.state["last_agent_response"] = text
    return None


async def _after_agent(callback_context):
    """After-agent: run self-eval then spawn async memory consolidation."""
    await self_evaluate_response(callback_context)
    spawn_consolidation(callback_context)


root_agent = Agent(
    name="meal_mentor",
    description=(
        "Concierge that coordinates a planner, pantry keeper, nutritionist, "
        "shopper, and coach to help the user plan meals and shop."
    ),
    model=Gemini(model=MODEL_PRO, retry_options=types.HttpRetryOptions(attempts=3)),
    instruction=COORDINATOR_INSTRUCTION,
    sub_agents=[
        build_planner_agent(),
        build_pantry_agent(),
        build_nutritionist_agent(),
        build_shopper_agent(),
        build_coach_agent(),
    ],
    before_model_callback=compact_history,
    after_model_callback=_record_last_turn,
    after_agent_callback=_after_agent,
)


_plugins = [PolicyGuardPlugin()]
_project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
_dataset_id = os.environ.get("BQ_ANALYTICS_DATASET_ID", "adk_agent_analytics")
_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

if _project_id:
    try:
        bq = bigquery.Client(project=_project_id)
        bq.create_dataset(f"{_project_id}.{_dataset_id}", exists_ok=True)
        _plugins.append(
            BigQueryAgentAnalyticsPlugin(
                project_id=_project_id,
                dataset_id=_dataset_id,
                location=_location,
                config=BigQueryLoggerConfig(
                    gcs_bucket_name=os.environ.get("BQ_ANALYTICS_GCS_BUCKET"),
                    connection_id=os.environ.get("BQ_ANALYTICS_CONNECTION_ID"),
                ),
            )
        )
    except Exception as exc:
        logging.warning("BigQuery analytics disabled: %s", exc)

app = App(
    root_agent=root_agent,
    name=APP_NAME,
    plugins=_plugins,
)
