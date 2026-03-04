"""Persistent memory layer for Meal Mentor.

Data lives in Firestore so pantry state, meal plans, and learned preferences
survive across sessions and are shared between the different specialist agents.
"""

from app.memory.firestore_store import FirestoreStore, get_store

__all__ = ["FirestoreStore", "get_store"]
