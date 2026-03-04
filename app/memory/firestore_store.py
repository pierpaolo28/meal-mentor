"""Firestore-backed persistent store for pantry / meal plans / preferences.

All reads and writes are wrapped so the tool layer never touches the Firestore
client directly. Falls back to an in-memory dict when ``USE_IN_MEMORY_STORE=1``
so unit tests and local playground runs work without GCP credentials.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any

from app.config import (
    COLLECTION_LEARNINGS,
    COLLECTION_MEAL_PLANS,
    COLLECTION_ORDERS,
    COLLECTION_PANTRY,
    COLLECTION_PREFERENCES,
    FIRESTORE_DATABASE,
)

logger = logging.getLogger(__name__)


class _InMemoryDoc:
    def __init__(self, data: dict[str, Any] | None):
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self._data


class _InMemoryBackend:
    """Dict-backed fallback used in tests and offline playground."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def set(self, collection: str, doc_id: str, payload: dict[str, Any]) -> None:
        self._data.setdefault(collection, {})[doc_id] = payload

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        return self._data.get(collection, {}).get(doc_id)

    def delete(self, collection: str, doc_id: str) -> None:
        self._data.get(collection, {}).pop(doc_id, None)

    def list(self, collection: str, user_prefix: str) -> list[dict[str, Any]]:
        return [
            doc | {"_id": doc_id}
            for doc_id, doc in self._data.get(collection, {}).items()
            if doc_id.startswith(f"{user_prefix}:")
        ]


class FirestoreStore:
    """Thin async facade over Firestore with an in-memory fallback."""

    def __init__(self) -> None:
        self._mode = "firestore"
        self._client: Any | None = None
        self._memory = _InMemoryBackend()

        if os.environ.get("USE_IN_MEMORY_STORE", "").lower() in ("1", "true", "yes"):
            self._mode = "memory"
            logger.info("FirestoreStore initialized in in-memory mode")
            return

        try:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(database=FIRESTORE_DATABASE)
            logger.info(
                "FirestoreStore connected to Firestore db=%s", FIRESTORE_DATABASE
            )
        except Exception as exc:
            self._mode = "memory"
            logger.warning(
                "Firestore unavailable (%s) - falling back to in-memory store", exc
            )

    @staticmethod
    def _doc_id(user_id: str, key: str) -> str:
        return f"{user_id}:{key}"

    async def upsert(
        self, collection: str, user_id: str, key: str, payload: dict[str, Any]
    ) -> None:
        doc_id = self._doc_id(user_id, key)
        if self._mode == "memory":
            self._memory.set(collection, doc_id, payload)
            return
        assert self._client is not None
        await self._client.collection(collection).document(doc_id).set(payload)

    async def get(
        self, collection: str, user_id: str, key: str
    ) -> dict[str, Any] | None:
        doc_id = self._doc_id(user_id, key)
        if self._mode == "memory":
            return self._memory.get(collection, doc_id)
        assert self._client is not None
        snap = await self._client.collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    async def delete(self, collection: str, user_id: str, key: str) -> None:
        doc_id = self._doc_id(user_id, key)
        if self._mode == "memory":
            self._memory.delete(collection, doc_id)
            return
        assert self._client is not None
        await self._client.collection(collection).document(doc_id).delete()

    async def list_for_user(
        self, collection: str, user_id: str
    ) -> list[dict[str, Any]]:
        if self._mode == "memory":
            return self._memory.list(collection, user_id)
        assert self._client is not None
        prefix = f"{user_id}:"
        results: list[dict[str, Any]] = []
        stream = (
            self._client.collection(collection)
            .where("_user_id", "==", user_id)
            .stream()
        )
        async for snap in stream:
            payload = snap.to_dict() or {}
            payload["_id"] = snap.id.replace(prefix, "", 1)
            results.append(payload)
        return results

    # Convenience wrappers used by the tools ---------------------------------
    async def get_pantry(self, user_id: str) -> list[dict[str, Any]]:
        return await self.list_for_user(COLLECTION_PANTRY, user_id)

    async def put_pantry_item(
        self, user_id: str, item_id: str, payload: dict[str, Any]
    ) -> None:
        payload = payload | {"_user_id": user_id}
        await self.upsert(COLLECTION_PANTRY, user_id, item_id, payload)

    async def delete_pantry_item(self, user_id: str, item_id: str) -> None:
        await self.delete(COLLECTION_PANTRY, user_id, item_id)

    async def put_meal_plan(
        self, user_id: str, week_start: str, plan: dict[str, Any]
    ) -> None:
        payload = plan | {"_user_id": user_id}
        await self.upsert(COLLECTION_MEAL_PLANS, user_id, week_start, payload)

    async def get_meal_plan(
        self, user_id: str, week_start: str
    ) -> dict[str, Any] | None:
        return await self.get(COLLECTION_MEAL_PLANS, user_id, week_start)

    async def put_preferences(self, user_id: str, prefs: dict[str, Any]) -> None:
        payload = prefs | {"_user_id": user_id}
        await self.upsert(COLLECTION_PREFERENCES, user_id, "profile", payload)

    async def get_preferences(self, user_id: str) -> dict[str, Any] | None:
        return await self.get(COLLECTION_PREFERENCES, user_id, "profile")

    async def put_learning(self, user_id: str, key: str, text: str) -> None:
        await self.upsert(
            COLLECTION_LEARNINGS,
            user_id,
            key,
            {"text": text, "_user_id": user_id},
        )

    async def list_learnings(self, user_id: str) -> list[dict[str, Any]]:
        return await self.list_for_user(COLLECTION_LEARNINGS, user_id)

    async def stash_order(
        self, user_id: str, token: str, payload: dict[str, Any]
    ) -> None:
        payload = payload | {"_user_id": user_id}
        await self.upsert(COLLECTION_ORDERS, user_id, token, payload)

    async def pop_order(self, user_id: str, token: str) -> dict[str, Any] | None:
        payload = await self.get(COLLECTION_ORDERS, user_id, token)
        if payload:
            await self.delete(COLLECTION_ORDERS, user_id, token)
        return payload


@functools.cache
def get_store() -> FirestoreStore:
    """Process-wide singleton so every tool shares one Firestore client."""
    return FirestoreStore()
