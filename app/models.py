"""Pydantic models — strict JSON schemas for tool inputs and outputs.

Every tool in Meal Mentor uses these models so the LLM sees a well-typed
contract and structured error responses instead of raw stack traces.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DietaryRestriction(StrEnum):
    """Common dietary restrictions the planner is aware of."""

    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    KOSHER = "kosher"
    HALAL = "halal"
    LOW_CARB = "low_carb"
    KETO = "keto"
    PESCATARIAN = "pescatarian"


class Unit(StrEnum):
    """Units allowed for pantry items so the shopping-list diff is deterministic."""

    GRAM = "g"
    KILOGRAM = "kg"
    MILLILITER = "ml"
    LITER = "l"
    PIECE = "piece"
    TABLESPOON = "tbsp"
    TEASPOON = "tsp"
    CUP = "cup"
    OUNCE = "oz"
    POUND = "lb"


class PantryItem(BaseModel):
    """A single ingredient the user has on hand."""

    name: str = Field(
        ...,
        min_length=1,
        description="Ingredient name in lowercase singular form, e.g. 'olive oil'.",
    )
    quantity: float = Field(
        ...,
        gt=0,
        description="How much of the ingredient is on hand, in the given unit.",
    )
    unit: Unit = Field(..., description="Measurement unit for the quantity.")
    expiration_date: date | None = Field(
        None, description="Optional ISO date when the item expires."
    )


class Recipe(BaseModel):
    """A recipe returned from the recipe search tool."""

    recipe_id: str = Field(
        ..., description="Stable ID that other tools use to look up this recipe."
    )
    title: str
    cuisine: str
    prep_minutes: int = Field(..., ge=0, le=600)
    ingredients: list[PantryItem]
    steps: list[str]
    tags: list[DietaryRestriction] = Field(default_factory=list)


class NutritionFacts(BaseModel):
    """Per-serving nutrition summary."""

    calories: int = Field(..., ge=0)
    protein_g: float = Field(..., ge=0)
    carbs_g: float = Field(..., ge=0)
    fat_g: float = Field(..., ge=0)
    fiber_g: float = Field(..., ge=0)


class Meal(BaseModel):
    """A meal slot on a plan."""

    day: Literal[
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    ]
    slot: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: str
    servings: int = Field(..., ge=1, le=12)


class MealPlan(BaseModel):
    """A week of meals."""

    week_start: date = Field(
        ..., description="ISO date of the Monday that starts the plan week."
    )
    meals: list[Meal]

    @field_validator("meals")
    @classmethod
    def _non_empty(cls, v: list[Meal]) -> list[Meal]:
        if not v:
            raise ValueError("A meal plan must contain at least one meal.")
        return v


class ShoppingItem(BaseModel):
    """One row on the generated shopping list."""

    name: str
    quantity: float
    unit: Unit
    estimated_cost_usd: float = Field(..., ge=0)


class ShoppingList(BaseModel):
    """The output of generate_shopping_list."""

    week_start: date
    items: list[ShoppingItem]
    total_estimated_cost_usd: float = Field(..., ge=0)


class DietaryPreferences(BaseModel):
    """User-level cooking preferences."""

    restrictions: list[DietaryRestriction] = Field(default_factory=list)
    disliked_ingredients: list[str] = Field(default_factory=list)
    preferred_cuisines: list[str] = Field(default_factory=list)
    target_calories_per_day: int | None = Field(None, ge=800, le=6000)
    household_size: int = Field(2, ge=1, le=20)


class ToolError(BaseModel):
    """Structured error returned to the model instead of raising.

    Every tool returns either a success payload or a ToolError. The model reads
    ``recovery_hint`` to decide what to do next — no stack traces, no crashes.
    """

    status: Literal["error"] = "error"
    code: str = Field(
        ..., description="Machine-readable error code, e.g. 'ITEM_NOT_FOUND'."
    )
    message: str = Field(
        ..., description="Human-readable explanation of what went wrong."
    )
    recovery_hint: str = Field(
        ...,
        description="Concrete next step the agent should take — never end with a dead-end.",
    )


class HITLPendingAction(BaseModel):
    """Returned when a tool needs human confirmation before executing."""

    status: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    action: str = Field(
        ..., description="Short verb-phrase describing what will happen."
    )
    confirmation_token: str = Field(
        ..., description="Opaque token the user must echo back to approve."
    )
    summary: str = Field(..., description="Full human-readable preview of the action.")
    expires_at_iso: str
