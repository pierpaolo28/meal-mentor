"""Central configuration for Meal Mentor.

Keeping model IDs, thresholds, and collection names in one place makes it easy
to swap models or environments without editing every agent file.
"""

from __future__ import annotations

import os

MODEL_PRO = os.environ.get("MODEL_PRO", "gemini-2.5-pro")
MODEL_FLASH = os.environ.get("MODEL_FLASH", "gemini-2.5-flash")
MODEL_FLASH_LITE = os.environ.get("MODEL_FLASH_LITE", "gemini-2.5-flash-lite")

FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "(default)")
COLLECTION_PANTRY = "pantry_items"
COLLECTION_MEAL_PLANS = "meal_plans"
COLLECTION_PREFERENCES = "user_preferences"
COLLECTION_LEARNINGS = "user_learnings"
COLLECTION_ORDERS = "pending_orders"

MAX_HISTORY_TOKENS = int(os.environ.get("MAX_HISTORY_TOKENS", "8000"))
SELF_EVAL_THRESHOLD = float(os.environ.get("SELF_EVAL_THRESHOLD", "0.7"))

HITL_ORDER_THRESHOLD_USD = float(os.environ.get("HITL_ORDER_THRESHOLD_USD", "0"))

APP_NAME = "meal_mentor"
